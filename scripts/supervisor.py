#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Any

HARNESS_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_DIR = HARNESS_ROOT / "schema"
TEMPLATES_DIR = HARNESS_ROOT / "templates"
OVERLAY_ROOT = TEMPLATES_DIR / "project-overlay"
BOOTSTRAP_MANIFEST_PATH = pathlib.Path("SUPERVISOR/bootstrap-manifest.json")
CODEX_BLOCK_BEGIN = "# >>> ai_supervisor managed block >>>"
CODEX_BLOCK_END = "# <<< ai_supervisor managed block <<<"


def die(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def run(cmd: list[str], cwd: pathlib.Path | None = None, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        capture_output=capture,
    )


def load_json(path: pathlib.Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        value = json.load(fh)
    if not isinstance(value, dict):
        die(f"expected JSON object in {path}")
    return value


def save_text(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def save_json(path: pathlib.Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_command(name: str) -> None:
    if shutil.which(name) is None:
        die(f"required command not found on PATH: {name}")


def repo_root(path: pathlib.Path) -> pathlib.Path:
    try:
        result = run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture=True)
    except subprocess.CalledProcessError:
        die(f"{path} is not inside a git repository")
    return pathlib.Path(result.stdout.strip()).resolve()


def bootstrap_overlay(target_repo: pathlib.Path) -> None:
    target_repo = repo_root(target_repo)

    for rel in [
        "AGENTS.md",
        "SUPERVISOR/REQUIREMENTS.md",
        "SUPERVISOR/INVARIANTS.md",
        "SUPERVISOR/ALLOWED_PATHS.md",
        "SUPERVISOR/DONE_CRITERIA.md",
        "SUPERVISOR/TASKS/.gitkeep",
        "SUPERVISOR/RUNS/.gitkeep",
        "SUPERVISOR/REVIEWS/.gitkeep",
        ".gitignore.ai-supervisor",
    ]:
        src = OVERLAY_ROOT / rel
        dst = target_repo / rel
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    print(f"Bootstrapped overlay into {target_repo}")


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def default_worktree_parent(target_repo: pathlib.Path) -> pathlib.Path:
    return target_repo.parent / ".ai_supervisor_worktrees" / target_repo.name


def validate_task_packet(packet: dict[str, Any], packet_path: pathlib.Path) -> None:
    required = [
        "task_id",
        "title",
        "role",
        "target_repo_name",
        "base_ref",
        "goal",
        "allowed_write_paths",
        "constraints",
        "done_criteria",
    ]
    missing = [k for k in required if k not in packet]
    if missing:
        die(f"task packet missing required keys {missing}: {packet_path}")

    if not isinstance(packet["allowed_write_paths"], list) or not packet["allowed_write_paths"]:
        die("task packet must contain a non-empty allowed_write_paths array")
    if not isinstance(packet["constraints"], list) or not packet["constraints"]:
        die("task packet must contain a non-empty constraints array")
    if not isinstance(packet["done_criteria"], list) or not packet["done_criteria"]:
        die("task packet must contain a non-empty done_criteria array")


def build_worker_prompt(packet: dict[str, Any], target_repo: pathlib.Path, run_dir: pathlib.Path) -> str:
    ro_paths = packet.get("read_only_context_paths", [])
    constraints = packet.get("constraints", [])
    validations = packet.get("validation_commands", [])
    deliverables = packet.get("deliverables", [])
    done = packet.get("done_criteria", [])
    appendix = packet.get("prompt_appendix", "")

    packet_copy = json.dumps(packet, indent=2, ensure_ascii=False)

    return f"""You are a supervised Codex worker operating inside an isolated Git worktree.

You must obey the task packet exactly.

TASK PACKET
{packet_copy}

AUTHORITATIVE PROJECT DOCUMENTS
- {target_repo / 'AGENTS.md'}
- {target_repo / 'SUPERVISOR/REQUIREMENTS.md'}
- {target_repo / 'SUPERVISOR/INVARIANTS.md'}
- {target_repo / 'SUPERVISOR/ALLOWED_PATHS.md'}
- {target_repo / 'SUPERVISOR/DONE_CRITERIA.md'}

READ-ONLY CONTEXT PATHS
{os.linesep.join('- ' + p for p in ro_paths) if ro_paths else '- (none declared)'}

WRITABLE PATH ALLOWLIST
{os.linesep.join('- ' + p for p in packet['allowed_write_paths'])}

HARD CONSTRAINTS
{os.linesep.join('- ' + c for c in constraints)}

DONE CRITERIA
{os.linesep.join('- ' + c for c in done)}

DELIVERABLES
{os.linesep.join('- ' + d for d in deliverables) if deliverables else '- (no extra deliverables declared)'}

VALIDATION COMMANDS
{os.linesep.join('- ' + v for v in validations) if validations else '- (none declared)'}

RULES
- Do not modify files outside the writable allowlist.
- Do not silently add features, refactors, or behavioral changes beyond the packet.
- If the request is ambiguous, state that ambiguity in the final report rather than improvising.
- Prefer narrow, auditable edits.
- Run validation commands if feasible inside the sandbox. If not feasible, report that accurately.
- Return only content that conforms to the provided output schema.

OUTPUT
Your final response must conform to the worker report JSON schema.

OPTIONAL APPENDIX
{appendix if appendix else '(none)'}

RUN DIRECTORY
{run_dir}
"""


def build_review_prompt(packet: dict[str, Any], changed_files: list[str], scope_violations: list[str]) -> str:
    packet_copy = json.dumps(packet, indent=2, ensure_ascii=False)
    scope_text = os.linesep.join(f"- {p}" for p in scope_violations) if scope_violations else "- none detected mechanically"
    changed_text = os.linesep.join(f"- {p}" for p in changed_files) if changed_files else "- no changed files detected"

    return f"""You are a supervising review lane.

Review the worker's uncommitted diff against the task packet below.

TASK PACKET
{packet_copy}

CHANGED FILES DETECTED
{changed_text}

MECHANICAL SCOPE VIOLATIONS
{scope_text}

REVIEW GOALS
- Determine whether the returned work should be approved, sent for rework, or rejected.
- Treat scope violations as material.
- Treat silent requirement expansion as material.
- Treat ignored invariants as material.
- Prefer precise blocking findings over vague commentary.
- Return only content that conforms to the provided review report JSON schema.

REVIEW STANDARD
- approve: good enough to accept
- rework: directionally correct but requires changes
- reject: materially wrong, unsafe, or out of bounds
"""


def safe_branch_name(packet: dict[str, Any]) -> str:
    raw = packet.get("worker_branch") or f"ai-supervisor/{packet['task_id']}"
    return raw


def create_worktree(target_repo: pathlib.Path, packet: dict[str, Any], worktree_parent: pathlib.Path) -> tuple[str, pathlib.Path]:
    task_id = packet["task_id"]
    stamp = utc_stamp().lower()
    branch = safe_branch_name(packet)
    worktree_path = worktree_parent / f"{task_id}-{stamp}"
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    existing = run(["git", "-C", str(target_repo), "branch", "--list", branch], capture=True).stdout.strip()
    if existing:
        branch = f"{branch}-{stamp}"

    run([
        "git", "-C", str(target_repo), "worktree", "add",
        "-b", branch,
        str(worktree_path),
        packet["base_ref"],
    ])
    return branch, worktree_path


def relative_changed_files(worktree_path: pathlib.Path) -> list[str]:
    result = run(["git", "-C", str(worktree_path), "status", "--porcelain"], capture=True)
    files: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path.strip())
    return sorted(set(files))


def path_allowed(path: str, allowlist: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    for rule in allowlist:
        rule = rule.rstrip("/")
        if not rule:
            continue
        if normalized == rule or normalized.startswith(rule + "/"):
            return True
        if fnmatch.fnmatch(normalized, rule):
            return True
    return False


def write_repo_state(worktree_path: pathlib.Path, run_dir: pathlib.Path) -> list[str]:
    changed = relative_changed_files(worktree_path)
    save_text(run_dir / "changed-files.txt", "\n".join(changed) + ("\n" if changed else ""))

    diff_patch = run(["git", "-C", str(worktree_path), "diff", "--patch"], capture=True).stdout
    save_text(run_dir / "git-diff.patch", diff_patch)

    status = run(["git", "-C", str(worktree_path), "status", "--short"], capture=True).stdout
    save_text(run_dir / "git-status.txt", status)

    head = run(["git", "-C", str(worktree_path), "rev-parse", "HEAD"], capture=True).stdout.strip()
    save_text(run_dir / "head.txt", head + "\n")
    return changed


def mechanical_scope_audit(packet: dict[str, Any], changed_files: list[str]) -> dict[str, Any]:
    allowlist = packet["allowed_write_paths"]
    violations = [p for p in changed_files if not path_allowed(p, allowlist)]
    return {
        "task_id": packet["task_id"],
        "allowed_write_paths": allowlist,
        "changed_files": changed_files,
        "scope_ok": not violations,
        "violations": violations,
    }


def run_codex_worker(worktree_path: pathlib.Path, run_dir: pathlib.Path, prompt_text: str, model: str, codex_bin: str) -> None:
    prompt_file = run_dir / "worker-prompt.txt"
    save_text(prompt_file, prompt_text)

    report_file = run_dir / "worker-report.json"
    stdout_file = run_dir / "worker.stdout.jsonl"
    stderr_file = run_dir / "worker.stderr.txt"

    cmd = [
        codex_bin,
        "exec",
        "--json",
        "--ephemeral",
        "-m", model,
        "-C", str(worktree_path),
        "--sandbox", "workspace-write",
        "--output-schema", str(SCHEMA_DIR / "worker-report.schema.json"),
        "--output-last-message", str(report_file),
        "-c", 'approval_policy="never"',
        "-c", 'sandbox_mode="workspace-write"',
        "-c", 'model_reasoning_effort="high"',
        "-c", 'model_verbosity="low"',
    ]

    with prompt_file.open("r", encoding="utf-8") as stdin_fh, \
         stdout_file.open("w", encoding="utf-8") as stdout_fh, \
         stderr_file.open("w", encoding="utf-8") as stderr_fh:
        result = subprocess.run(
            cmd,
            stdin=stdin_fh,
            stdout=stdout_fh,
            stderr=stderr_fh,
            text=True,
        )
    save_text(run_dir / "worker.exit-code.txt", str(result.returncode) + "\n")


def run_codex_review(worktree_path: pathlib.Path, run_dir: pathlib.Path, prompt_text: str, review_model: str, codex_bin: str) -> None:
    prompt_file = run_dir / "review-prompt.txt"
    save_text(prompt_file, prompt_text)

    report_file = run_dir / "review-report.json"
    stdout_file = run_dir / "review.stdout.jsonl"
    stderr_file = run_dir / "review.stderr.txt"

    cmd = [
        codex_bin,
        "exec",
        "--json",
        "--ephemeral",
        "-C", str(worktree_path),
        "--output-schema", str(SCHEMA_DIR / "review-report.schema.json"),
        "--output-last-message", str(report_file),
        "-c", f'review_model="{review_model}"',
        "-c", 'approval_policy="never"',
        "-c", 'sandbox_mode="read-only"',
        "review",
        "--uncommitted",
    ]

    with prompt_file.open("r", encoding="utf-8") as stdin_fh, \
         stdout_file.open("w", encoding="utf-8") as stdout_fh, \
         stderr_file.open("w", encoding="utf-8") as stderr_fh:
        result = subprocess.run(
            cmd,
            stdin=stdin_fh,
            stdout=stdout_fh,
            stderr=stderr_fh,
            text=True,
        )
    save_text(run_dir / "review.exit-code.txt", str(result.returncode) + "\n")


def run_dir_from_task(target_repo: pathlib.Path, task_id: str) -> pathlib.Path:
    return target_repo / "SUPERVISOR" / "RUNS" / f"{utc_stamp()}-{task_id}"


def codex_home() -> pathlib.Path:
    raw = os.environ.get("CODEX_HOME")
    if raw:
        return pathlib.Path(raw).expanduser().resolve()
    return (pathlib.Path.home() / ".codex").resolve()


def codex_config_path() -> pathlib.Path:
    return codex_home() / "config.toml"


def render_bullet_lines(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def parse_existing_list(doc_path: pathlib.Path) -> list[str]:
    if not doc_path.exists():
        return []
    lines = []
    for line in doc_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            lines.append(stripped[2:].strip())
    return lines


def prompt_text(label: str, default: str | None = None, required: bool = False) -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""
        print("Please enter a value.")


def prompt_bool(label: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        value = input(f"{label} {suffix}: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer yes or no.")


def prompt_multiline(label: str, defaults: list[str] | None = None, required: bool = False) -> list[str]:
    defaults = defaults or []
    print(f"{label}")
    if defaults:
        print("Current/default values:")
        for item in defaults:
            print(f"  - {item}")
        print("Enter one per line. Submit a blank line immediately to keep the defaults.")
    else:
        print("Enter one per line. Finish with a blank line.")

    values: list[str] = []
    while True:
        line = input("> ").strip()
        if not line:
            if not values and defaults:
                return defaults
            if required and not values:
                print("At least one entry is required.")
                continue
            return values
        values.append(line)


def toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_codex_block(model: str, harness_root: pathlib.Path, target_repo: pathlib.Path, trust_target_repo: bool, trust_harness_repo: bool) -> str:
    lines = [
        CODEX_BLOCK_BEGIN,
        f'review_model = "{toml_string(model)}"',
        "",
        "[profiles.supervisor]",
        f'model = "{toml_string(model)}"',
        'model_reasoning_effort = "high"',
        'model_verbosity = "medium"',
        'plan_mode_reasoning_effort = "high"',
        'approval_policy = "on-request"',
        'sandbox_mode = "workspace-write"',
        'personality = "pragmatic"',
        "",
        "[profiles.worker]",
        f'model = "{toml_string(model)}"',
        'model_reasoning_effort = "high"',
        'model_verbosity = "low"',
        'approval_policy = "never"',
        'sandbox_mode = "workspace-write"',
        'personality = "pragmatic"',
        "",
        "[profiles.reviewer]",
        f'model = "{toml_string(model)}"',
        'model_reasoning_effort = "high"',
        'model_verbosity = "low"',
        'approval_policy = "never"',
        'sandbox_mode = "read-only"',
        'personality = "pragmatic"',
    ]
    if trust_target_repo:
        lines.extend([
            "",
            f'[projects."{toml_string(str(target_repo))}"]',
            'trust_level = "trusted"',
        ])
    if trust_harness_repo:
        lines.extend([
            "",
            f'[projects."{toml_string(str(harness_root))}"]',
            'trust_level = "trusted"',
        ])
    lines.extend(["", CODEX_BLOCK_END, ""])
    return "\n".join(lines)


def read_existing_codex_block(config_text: str) -> str | None:
    if CODEX_BLOCK_BEGIN not in config_text or CODEX_BLOCK_END not in config_text:
        return None
    start = config_text.index(CODEX_BLOCK_BEGIN)
    end = config_text.index(CODEX_BLOCK_END) + len(CODEX_BLOCK_END)
    return config_text[start:end]


def apply_codex_block(config_path: pathlib.Path, block: str) -> tuple[pathlib.Path | None, bool]:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    before = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    backup_path: pathlib.Path | None = None

    if CODEX_BLOCK_BEGIN in before and CODEX_BLOCK_END in before:
        start = before.index(CODEX_BLOCK_BEGIN)
        end = before.index(CODEX_BLOCK_END) + len(CODEX_BLOCK_END)
        after = before[:start].rstrip() + "\n\n" + block.strip() + "\n"
        tail = before[end:].lstrip("\n")
        if tail:
            after += "\n" + tail
        changed = after != before
    else:
        trimmed = before.rstrip()
        after = (trimmed + "\n\n" if trimmed else "") + block.strip() + "\n"
        changed = after != before

    if changed and config_path.exists():
        backup_path = config_path.with_name(config_path.name + f".bak.{utc_stamp()}")
        shutil.copy2(config_path, backup_path)
    if changed:
        config_path.write_text(after, encoding="utf-8")
    return backup_path, changed


def render_agents_md(project_name: str, project_purpose: str) -> str:
    return f"""# AGENTS.md

This is a supervised target repository for **{project_name}**.

## Project purpose

{project_purpose}

## Authority

The supervisor packet and the project documents under `SUPERVISOR/` are authoritative for supervised Codex runs.

## Non-negotiable rules

- Do not silently add features or behavioral changes beyond the packet.
- Do not modify files outside the writable allowlist.
- Do not treat vague requirements as permission to improvise architecture.
- If a requirement is ambiguous, state the ambiguity explicitly in the worker report.
- Preserve existing design patterns unless the packet explicitly asks for redesign.

## Required project documents

Read these when present and relevant:

- `SUPERVISOR/REQUIREMENTS.md`
- `SUPERVISOR/INVARIANTS.md`
- `SUPERVISOR/ALLOWED_PATHS.md`
- `SUPERVISOR/DONE_CRITERIA.md`

## Expected behavior

- Keep changes narrow.
- Prefer precise edits over broad rewrites.
- Keep the final report factual and machine-readable when a schema is provided.
"""


def render_requirements_md(project_name: str, project_purpose: str, project_requirements: list[str]) -> str:
    return f"""# REQUIREMENTS

## Project

- Name: {project_name}
- Purpose: {project_purpose}

## Global requirements

{render_bullet_lines(project_requirements)}
"""


def render_invariants_md(invariants: list[str]) -> str:
    return f"""# INVARIANTS

These project-wide invariants are mandatory for supervised runs.

{render_bullet_lines(invariants)}
"""


def render_allowed_paths_md(paths: list[str]) -> str:
    return f"""# ALLOWED_PATHS

These are the durable writable areas and path patterns normally considered in-bounds.
Task packets should still declare a narrower writable allowlist when appropriate.

{render_bullet_lines(paths)}
"""


def render_done_criteria_md(done_criteria: list[str], validation_commands: list[str]) -> str:
    text = f"""# DONE_CRITERIA

These are the durable acceptance expectations for supervised work.

## Acceptance criteria

{render_bullet_lines(done_criteria)}
"""
    if validation_commands:
        text += f"""

## Default validation commands

{render_bullet_lines(validation_commands)}
"""
    return text


def write_overlay_from_answers(target_repo: pathlib.Path, answers: dict[str, Any], force: bool) -> list[pathlib.Path]:
    target_repo = repo_root(target_repo)
    written: list[pathlib.Path] = []

    static_files = [
        pathlib.Path("SUPERVISOR/TASKS/.gitkeep"),
        pathlib.Path("SUPERVISOR/RUNS/.gitkeep"),
        pathlib.Path("SUPERVISOR/REVIEWS/.gitkeep"),
        pathlib.Path(".gitignore.ai-supervisor"),
    ]
    for rel in static_files:
        src = OVERLAY_ROOT / rel
        dst = target_repo / rel
        if dst.exists() and not force:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        written.append(dst)

    dynamic_docs: dict[pathlib.Path, str] = {
        pathlib.Path("AGENTS.md"): render_agents_md(answers["project_name"], answers["project_purpose"]),
        pathlib.Path("SUPERVISOR/REQUIREMENTS.md"): render_requirements_md(
            answers["project_name"],
            answers["project_purpose"],
            answers["project_requirements"],
        ),
        pathlib.Path("SUPERVISOR/INVARIANTS.md"): render_invariants_md(answers["invariants"]),
        pathlib.Path("SUPERVISOR/ALLOWED_PATHS.md"): render_allowed_paths_md(answers["allowed_paths"]),
        pathlib.Path("SUPERVISOR/DONE_CRITERIA.md"): render_done_criteria_md(
            answers["done_criteria"],
            answers["validation_commands"],
        ),
        BOOTSTRAP_MANIFEST_PATH: json.dumps(
            {
                "version": 1,
                "initialized_at_utc": utc_stamp(),
                "harness_root": str(answers["harness_root"]),
                "target_repo": str(target_repo),
                "project_name": answers["project_name"],
                "project_purpose": answers["project_purpose"],
                "default_model": answers["default_model"],
                "default_worktree_root": str(answers["default_worktree_root"]),
                "codex_config_path": str(answers["codex_config_path"]),
                "codex_profiles_installed": answers["install_codex_profiles"],
                "trusted_projects": [
                    str(p) for p in answers["trusted_projects"]
                ],
                "default_validation_commands": answers["validation_commands"],
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
    }

    for rel, content in dynamic_docs.items():
        dst = target_repo / rel
        if dst.exists() and not force:
            continue
        save_text(dst, content)
        written.append(dst)

    return written


def existing_overlay_paths(target_repo: pathlib.Path) -> list[pathlib.Path]:
    rels = [
        pathlib.Path("AGENTS.md"),
        pathlib.Path("SUPERVISOR/REQUIREMENTS.md"),
        pathlib.Path("SUPERVISOR/INVARIANTS.md"),
        pathlib.Path("SUPERVISOR/ALLOWED_PATHS.md"),
        pathlib.Path("SUPERVISOR/DONE_CRITERIA.md"),
        BOOTSTRAP_MANIFEST_PATH,
    ]
    existing = []
    for rel in rels:
        path = target_repo / rel
        if path.exists() and path.stat().st_size > 0:
            existing.append(path)
    return existing


def load_bootstrap_manifest(target_repo: pathlib.Path) -> dict[str, Any] | None:
    manifest_path = target_repo / BOOTSTRAP_MANIFEST_PATH
    if not manifest_path.exists():
        return None
    try:
        return load_json(manifest_path)
    except Exception:
        return None


def resolve_default_model(target_repo: pathlib.Path, explicit_model: str | None, key: str = "default_model") -> str:
    if explicit_model:
        return explicit_model
    manifest = load_bootstrap_manifest(target_repo)
    if manifest and isinstance(manifest.get(key), str) and manifest[key].strip():
        return manifest[key].strip()
    return "gpt-5.4"


def resolve_worktree_parent(target_repo: pathlib.Path, explicit_parent: str | None) -> pathlib.Path:
    if explicit_parent:
        return pathlib.Path(explicit_parent).expanduser().resolve()
    manifest = load_bootstrap_manifest(target_repo)
    if manifest and isinstance(manifest.get("default_worktree_root"), str):
        raw = manifest["default_worktree_root"].strip()
        if raw:
            return pathlib.Path(raw).expanduser().resolve()
    return default_worktree_parent(target_repo)


def preview_init(answers: dict[str, Any], codex_block: str | None) -> str:
    trusted = ", ".join(str(p) for p in answers["trusted_projects"]) if answers["trusted_projects"] else "(none)"
    lines = [
        "",
        "Planned bootstrap:",
        f"- harness root: {answers['harness_root']}",
        f"- target repo: {answers['target_repo']}",
        f"- worktree root: {answers['default_worktree_root']}",
        f"- default model: {answers['default_model']}",
        f"- trusted projects in Codex config: {trusted}",
        "",
        "Files to write or refresh:",
        f"- {answers['target_repo'] / 'AGENTS.md'}",
        f"- {answers['target_repo'] / 'SUPERVISOR/REQUIREMENTS.md'}",
        f"- {answers['target_repo'] / 'SUPERVISOR/INVARIANTS.md'}",
        f"- {answers['target_repo'] / 'SUPERVISOR/ALLOWED_PATHS.md'}",
        f"- {answers['target_repo'] / 'SUPERVISOR/DONE_CRITERIA.md'}",
        f"- {answers['target_repo'] / BOOTSTRAP_MANIFEST_PATH}",
        f"- {answers['target_repo'] / '.gitignore.ai-supervisor'}",
        f"- {answers['target_repo'] / 'SUPERVISOR/TASKS/.gitkeep'}",
        f"- {answers['target_repo'] / 'SUPERVISOR/RUNS/.gitkeep'}",
        f"- {answers['target_repo'] / 'SUPERVISOR/REVIEWS/.gitkeep'}",
    ]
    if codex_block:
        lines.extend([
            "",
            f"Codex config block target: {answers['codex_config_path']}",
            "Managed block preview:",
            codex_block.strip(),
        ])
    else:
        lines.extend([
            "",
            "Codex config update: skipped",
        ])
    return "\n".join(lines) + "\n"


def cmd_bootstrap_overlay(args: argparse.Namespace) -> None:
    bootstrap_overlay(pathlib.Path(args.target_repo))


def cmd_init(args: argparse.Namespace) -> None:
    ensure_command("git")
    ensure_command(args.codex_bin)

    harness_root = HARNESS_ROOT.resolve()
    target_repo = repo_root(pathlib.Path(args.target_repo).expanduser().resolve()) if args.target_repo else repo_root(pathlib.Path(prompt_text("Target source repo path", required=True)).expanduser().resolve())
    default_model = args.model or "gpt-5.4"
    default_worktree_root = pathlib.Path(args.worktree_root).expanduser().resolve() if args.worktree_root else default_worktree_parent(target_repo).resolve()
    config_path = pathlib.Path(args.codex_config).expanduser().resolve() if args.codex_config else codex_config_path()

    existing_manifest = load_bootstrap_manifest(target_repo) or {}
    existing_docs = existing_overlay_paths(target_repo)
    inferred_project_name = existing_manifest.get("project_name") or target_repo.name
    inferred_purpose = existing_manifest.get("project_purpose") or ""
    inferred_model = existing_manifest.get("default_model") or default_model
    inferred_worktree_root = pathlib.Path(existing_manifest.get("default_worktree_root", str(default_worktree_root))).expanduser().resolve()

    if existing_docs and not args.force:
        print("Existing overlay documents were found:")
        for path in existing_docs:
            print(f"- {path}")
        if not prompt_bool("Overwrite those files with new wizard output?", default=False):
            die("init cancelled because existing overlay files were present")

    print("ai_supervisor guided init")
    print("Leave a prompt blank to accept the default shown in brackets.")
    print()

    harness_answer = pathlib.Path(prompt_text("Harness repo path", default=str(harness_root), required=True)).expanduser().resolve()
    if harness_answer != harness_root:
        print(f"Note: this script is executing from {harness_root}, but will record {harness_answer} in the manifest and optional Codex config block.")
    project_name = prompt_text("Project name", default=str(inferred_project_name), required=True)
    project_purpose = prompt_text("One-sentence project purpose", default=str(inferred_purpose) if inferred_purpose else None, required=True)
    project_requirements = prompt_multiline(
        "Project-wide requirements", defaults=parse_existing_list(target_repo / "SUPERVISOR/REQUIREMENTS.md"), required=True
    )
    invariants = prompt_multiline(
        "Core invariants", defaults=parse_existing_list(target_repo / "SUPERVISOR/INVARIANTS.md"), required=True
    )
    allowed_paths = prompt_multiline(
        "Default writable paths or path patterns",
        defaults=parse_existing_list(target_repo / "SUPERVISOR/ALLOWED_PATHS.md"),
        required=True,
    )
    done_criteria = prompt_multiline(
        "Durable done criteria",
        defaults=parse_existing_list(target_repo / "SUPERVISOR/DONE_CRITERIA.md"),
        required=True,
    )
    validation_commands = prompt_multiline(
        "Default validation commands (optional)",
        defaults=existing_manifest.get("default_validation_commands", []) if isinstance(existing_manifest.get("default_validation_commands"), list) else [],
        required=False,
    )
    default_worktree_root = pathlib.Path(
        prompt_text("Default worktree parent", default=str(inferred_worktree_root), required=True)
    ).expanduser().resolve()
    default_model = prompt_text("Default Codex model", default=str(inferred_model), required=True)
    install_codex_profiles = prompt_bool("Install or update the managed Codex profile block", default=True)
    trust_target_repo = False
    trust_harness_repo = False
    if install_codex_profiles:
        trust_target_repo = prompt_bool("Mark the target repo as trusted in Codex config", default=False)
        trust_harness_repo = prompt_bool("Mark the harness repo as trusted in Codex config", default=False)

    answers = {
        "harness_root": harness_answer,
        "target_repo": target_repo,
        "project_name": project_name,
        "project_purpose": project_purpose,
        "project_requirements": project_requirements,
        "invariants": invariants,
        "allowed_paths": allowed_paths,
        "done_criteria": done_criteria,
        "validation_commands": validation_commands,
        "default_worktree_root": default_worktree_root,
        "default_model": default_model,
        "install_codex_profiles": install_codex_profiles,
        "codex_config_path": config_path,
        "trusted_projects": [
            p for p, enabled in ((target_repo, trust_target_repo), (harness_answer, trust_harness_repo)) if enabled
        ],
    }

    codex_block = None
    if install_codex_profiles:
        codex_block = render_codex_block(default_model, harness_answer, target_repo, trust_target_repo, trust_harness_repo)

    print(preview_init(answers, codex_block))
    if not prompt_bool("Apply this bootstrap", default=True):
        die("init cancelled")

    written_files = write_overlay_from_answers(target_repo, answers, force=True)

    backup_path = None
    config_changed = False
    if codex_block is not None:
        backup_path, config_changed = apply_codex_block(config_path, codex_block)

    print("Bootstrap complete.")
    print("Files written or refreshed:")
    for path in written_files:
        print(f"- {path}")
    if codex_block is not None:
        if config_changed:
            print(f"- updated Codex config: {config_path}")
            if backup_path:
                print(f"- backup created: {backup_path}")
        else:
            print(f"- Codex config already matched the managed block: {config_path}")
    else:
        print("- Codex config unchanged")

    print()
    print("Next steps:")
    print(f"1. Review {target_repo / 'SUPERVISOR/REQUIREMENTS.md'} and related project truth files.")
    print(f"2. Create the first task packet under {target_repo / 'SUPERVISOR/TASKS'}.")
    print(f"3. Spawn a worker with: ./scripts/spawn-worker.sh --target-repo {target_repo} --task {target_repo / 'SUPERVISOR/TASKS/TASK-001.json'}")


def cmd_spawn(args: argparse.Namespace) -> None:
    ensure_command("git")
    ensure_command(args.codex_bin)

    target_repo = repo_root(pathlib.Path(args.target_repo))
    packet_path = pathlib.Path(args.task).resolve()
    packet = load_json(packet_path)
    validate_task_packet(packet, packet_path)

    run_dir = run_dir_from_task(target_repo, packet["task_id"])
    run_dir.mkdir(parents=True, exist_ok=False)

    save_json(run_dir / "task-packet.json", packet)

    worktree_parent = resolve_worktree_parent(target_repo, args.worktree_parent)
    branch, worktree_path = create_worktree(target_repo, packet, worktree_parent)
    model = resolve_default_model(target_repo, args.model)

    metadata = {
        "task_id": packet["task_id"],
        "target_repo": str(target_repo),
        "packet_path": str(packet_path),
        "run_dir": str(run_dir),
        "worker_branch": branch,
        "worktree_path": str(worktree_path),
        "base_ref": packet["base_ref"],
        "model": model,
    }
    save_json(run_dir / "run-metadata.json", metadata)

    prompt = build_worker_prompt(packet, target_repo, run_dir)
    run_codex_worker(worktree_path, run_dir, prompt, model, args.codex_bin)

    changed = write_repo_state(worktree_path, run_dir)
    scope = mechanical_scope_audit(packet, changed)
    save_json(run_dir / "scope-audit.json", scope)

    print(json.dumps({
        "status": "spawned",
        "run_dir": str(run_dir),
        "worktree_path": str(worktree_path),
        "worker_branch": branch,
    }, indent=2))


def cmd_review(args: argparse.Namespace) -> None:
    ensure_command("git")
    ensure_command(args.codex_bin)

    run_dir = pathlib.Path(args.run_dir).resolve()
    metadata = load_json(run_dir / "run-metadata.json")
    packet = load_json(run_dir / "task-packet.json")
    worktree_path = pathlib.Path(metadata["worktree_path"]).resolve()
    target_repo = pathlib.Path(metadata["target_repo"]).resolve()

    changed = write_repo_state(worktree_path, run_dir)
    scope = mechanical_scope_audit(packet, changed)
    save_json(run_dir / "scope-audit.json", scope)

    review_model = resolve_default_model(target_repo, args.review_model)
    prompt = build_review_prompt(packet, changed, scope["violations"])
    run_codex_review(worktree_path, run_dir, prompt, review_model, args.codex_bin)

    print(json.dumps({
        "status": "reviewed",
        "run_dir": str(run_dir),
        "worktree_path": str(worktree_path),
    }, indent=2))


def cmd_collect(args: argparse.Namespace) -> None:
    run_dir = pathlib.Path(args.run_dir).resolve()
    metadata = load_json(run_dir / "run-metadata.json")
    packet = load_json(run_dir / "task-packet.json")
    scope = load_json(run_dir / "scope-audit.json") if (run_dir / "scope-audit.json").exists() else None

    worker_report = None
    review_report = None
    if (run_dir / "worker-report.json").exists():
        try:
            worker_report = load_json(run_dir / "worker-report.json")
        except Exception:
            worker_report = {"_error": "worker-report.json is not valid JSON"}
    if (run_dir / "review-report.json").exists():
        try:
            review_report = load_json(run_dir / "review-report.json")
        except Exception:
            review_report = {"_error": "review-report.json is not valid JSON"}

    summary = {
        "task_id": packet["task_id"],
        "title": packet["title"],
        "target_repo": metadata["target_repo"],
        "worker_branch": metadata["worker_branch"],
        "worktree_path": metadata["worktree_path"],
        "scope_ok": None if scope is None else scope.get("scope_ok"),
        "scope_violations": [] if scope is None else scope.get("violations", []),
        "worker_status": None if worker_report is None else worker_report.get("status"),
        "review_verdict": None if review_report is None else review_report.get("verdict"),
        "worker_summary": None if worker_report is None else worker_report.get("summary"),
        "review_summary": None if review_report is None else review_report.get("summary"),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ai_supervisor local runner")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="guided bootstrap for a target repo and optional Codex config block")
    p_init.add_argument("--target-repo", help="path to the target git repository; if omitted, the wizard will ask")
    p_init.add_argument("--codex-config", help="override the Codex config path; defaults to $CODEX_HOME/config.toml or ~/.codex/config.toml")
    p_init.add_argument("--worktree-root", help="default worktree parent to record in the bootstrap manifest")
    p_init.add_argument("--model", help="default worker/reviewer model to record")
    p_init.add_argument("--codex-bin", default="codex")
    p_init.add_argument("--force", action="store_true", help="overwrite existing overlay docs without preserving them")
    p_init.set_defaults(func=cmd_init)

    p_bootstrap = sub.add_parser("bootstrap-overlay", help="copy the project overlay into a target repo")
    p_bootstrap.add_argument("target_repo")
    p_bootstrap.set_defaults(func=cmd_bootstrap_overlay)

    p_spawn = sub.add_parser("spawn", help="spawn a worker lane from a task packet")
    p_spawn.add_argument("--target-repo", required=True)
    p_spawn.add_argument("--task", required=True, help="path to task packet JSON")
    p_spawn.add_argument("--worktree-parent", help="override parent directory for worker worktrees")
    p_spawn.add_argument("--model", help="override the model used for this worker run")
    p_spawn.add_argument("--codex-bin", default="codex")
    p_spawn.set_defaults(func=cmd_spawn)

    p_review = sub.add_parser("review", help="run a review lane for an existing run directory")
    p_review.add_argument("--run-dir", required=True)
    p_review.add_argument("--review-model", help="override the review model for this run")
    p_review.add_argument("--codex-bin", default="codex")
    p_review.set_defaults(func=cmd_review)

    p_collect = sub.add_parser("collect", help="print a compact summary for a run directory")
    p_collect.add_argument("--run-dir", required=True)
    p_collect.set_defaults(func=cmd_collect)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
