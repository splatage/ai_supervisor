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
    overlay_root = TEMPLATES_DIR / "project-overlay"

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
        src = overlay_root / rel
        dst = target_repo / rel
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    print(f"Bootstrapped overlay into {target_repo}")


def utc_stamp() -> str:
    return dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


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
- {target_repo / "AGENTS.md"}
- {target_repo / "SUPERVISOR/REQUIREMENTS.md"}
- {target_repo / "SUPERVISOR/INVARIANTS.md"}
- {target_repo / "SUPERVISOR/ALLOWED_PATHS.md"}
- {target_repo / "SUPERVISOR/DONE_CRITERIA.md"}

READ-ONLY CONTEXT PATHS
{os.linesep.join("- " + p for p in ro_paths) if ro_paths else "- (none declared)"}

WRITABLE PATH ALLOWLIST
{os.linesep.join("- " + p for p in packet["allowed_write_paths"])}

HARD CONSTRAINTS
{os.linesep.join("- " + c for c in constraints)}

DONE CRITERIA
{os.linesep.join("- " + c for c in done)}

DELIVERABLES
{os.linesep.join("- " + d for d in deliverables) if deliverables else "- (no extra deliverables declared)"}

VALIDATION COMMANDS
{os.linesep.join("- " + v for v in validations) if validations else "- (none declared)"}

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
{appendix if appendix else "(none)"}

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


def cmd_bootstrap_overlay(args: argparse.Namespace) -> None:
    bootstrap_overlay(pathlib.Path(args.target_repo))


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

    worktree_parent = pathlib.Path(args.worktree_parent).resolve() if args.worktree_parent else default_worktree_parent(target_repo)
    branch, worktree_path = create_worktree(target_repo, packet, worktree_parent)

    metadata = {
        "task_id": packet["task_id"],
        "target_repo": str(target_repo),
        "packet_path": str(packet_path),
        "run_dir": str(run_dir),
        "worker_branch": branch,
        "worktree_path": str(worktree_path),
        "base_ref": packet["base_ref"],
        "model": args.model,
    }
    save_json(run_dir / "run-metadata.json", metadata)

    prompt = build_worker_prompt(packet, target_repo, run_dir)
    run_codex_worker(worktree_path, run_dir, prompt, args.model, args.codex_bin)

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

    changed = write_repo_state(worktree_path, run_dir)
    scope = mechanical_scope_audit(packet, changed)
    save_json(run_dir / "scope-audit.json", scope)

    prompt = build_review_prompt(packet, changed, scope["violations"])
    run_codex_review(worktree_path, run_dir, prompt, args.review_model, args.codex_bin)

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

    p_bootstrap = sub.add_parser("bootstrap-overlay", help="copy the project overlay into a target repo")
    p_bootstrap.add_argument("target_repo")
    p_bootstrap.set_defaults(func=cmd_bootstrap_overlay)

    p_spawn = sub.add_parser("spawn", help="spawn a worker lane from a task packet")
    p_spawn.add_argument("--target-repo", required=True)
    p_spawn.add_argument("--task", required=True, help="path to task packet JSON")
    p_spawn.add_argument("--worktree-parent", help="override parent directory for worker worktrees")
    p_spawn.add_argument("--model", default="gpt-5.4")
    p_spawn.add_argument("--codex-bin", default="codex")
    p_spawn.set_defaults(func=cmd_spawn)

    p_review = sub.add_parser("review", help="run a review lane for an existing run directory")
    p_review.add_argument("--run-dir", required=True)
    p_review.add_argument("--review-model", default="gpt-5.4")
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
