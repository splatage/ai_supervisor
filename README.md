# ai_supervisor

A local, drift-safe orchestration harness for **Codex CLI** with **GPT-5.4**.

This repository is the **harness**, not the product repo. Its job is to help one supervising operator coordinate multiple local Codex worker lanes against a Git repository with tighter scope control, machine-readable task packets, isolated worktrees, and structured review.

## Current stage

This scaffold is an initial working slice:

- local Linux-first workflow
- one supervisor
- multiple worker lanes
- one Git worktree per worker
- machine-readable task packets
- machine-readable worker reports
- machine-readable review reports
- hard writable-path allowlists
- explicit review step before acceptance
- guided bootstrap wizard for project overlay + Codex profile setup

It is **not** yet a full autonomous merge system.

## Design goals

- reduce architecture and scope drift
- keep the supervisor authoritative
- make worker outputs easy to evaluate
- preserve a clear audit trail
- work with a normal GitHub source repo and local shell

## Repository layout

```text
docs/                     design and operating notes
profiles/                 Codex config examples
schema/                   JSON schemas for packets and reports
scripts/                  local runner and helper scripts
templates/                project overlay + packet templates
examples/                 example task packet
runs/                     placeholder for harness-local experiments
```

## Quick start

### 1. Install Codex CLI

Install Codex CLI, then authenticate with your ChatGPT account or API key.

```bash
npm install -g @openai/codex
codex
```

### 2. Run guided init

The recommended entry point is the interactive init wizard.

```bash
./scripts/init-environment.sh --target-repo /path/to/your/source-repo
```

The wizard will:

- verify `git`, `python3`, and `codex`
- inspect the target repo
- ask for the required project truth fields
- write or refresh the overlay docs under `SUPERVISOR/`
- write `SUPERVISOR/bootstrap-manifest.json`
- optionally install or refresh a managed block in `~/.codex/config.toml`

If you prefer to skip the wizard and only copy the bare overlay skeleton, you can still use:

```bash
./scripts/bootstrap-project.sh /path/to/your/source-repo
```

### 3. Review the generated project truth files

The wizard writes these into the target repo:

```text
TARGET_REPO/
  AGENTS.md
  SUPERVISOR/
    REQUIREMENTS.md
    INVARIANTS.md
    ALLOWED_PATHS.md
    DONE_CRITERIA.md
    TASKS/
    RUNS/
    REVIEWS/
    bootstrap-manifest.json
```

Review them before spawning workers.

### 4. Author a task packet

Start from:

- `examples/task-packet.example.json`
- `templates/task-packet.md`

Then save the real machine-readable packet into the target repo, for example:

```text
TARGET_REPO/SUPERVISOR/TASKS/TASK-001.json
```

### 5. Spawn a worker

```bash
./scripts/spawn-worker.sh \
  --target-repo /path/to/your/source-repo \
  --task /path/to/your/source-repo/SUPERVISOR/TASKS/TASK-001.json
```

This will:

- create an isolated Git worktree
- build a worker prompt from the task packet
- run `codex exec` in non-interactive mode
- save a machine-readable worker report
- capture transcripts and repo state

If the target repo has already been initialized, the runner will pick up the default worktree root and default model from `SUPERVISOR/bootstrap-manifest.json` unless you override them on the command line.

### 6. Review the returned work

```bash
./scripts/review-worker.sh \
  --run-dir /path/to/your/source-repo/SUPERVISOR/RUNS/<RUN_ID>
```

This will:

- compute changed files
- check changed files against the writable allowlist
- run a dedicated Codex review pass
- save a machine-readable review report

### 7. Inspect and decide

Inspect the generated artifacts in the run directory:

- `worker-report.json`
- `review-report.json`
- `git-status.txt`
- `git-diff.patch`
- `changed-files.txt`
- `scope-audit.json`
- `worker.stdout.jsonl`
- `review.stdout.jsonl`

The human supervisor remains the final acceptance authority.

## Core operating rules

1. Every worker gets a narrow task packet.
2. Every worker gets an explicit writable-path allowlist.
3. Every worker runs in its own worktree.
4. Worker self-report is never enough for acceptance.
5. A separate review pass is mandatory before approval.
6. Overlapping write-heavy workers should be avoided unless deliberately coordinated.

## Scripts

### `init-environment.sh`
Guided bootstrap for a target repo. It collects the required project truth fields, writes the overlay documents, stores a bootstrap manifest, and can update the user's Codex config with a clearly marked managed block.

### `bootstrap-project.sh`
Copies the project overlay into a target repo without asking questions.

### `spawn-worker.sh`
Thin shell wrapper over the Python supervisor runner for worker execution.

### `review-worker.sh`
Thin shell wrapper over the Python supervisor runner for review.

### `collect-results.sh`
Summarises the run artifacts in a compact human-readable form.

### `supervisor.py`
The main local runner. Current subcommands:

- `init`
- `bootstrap-overlay`
- `spawn`
- `review`
- `collect`

## Important boundaries

- The harness assumes `git`, `python3`, and `codex` are installed locally.
- Worker lanes default to `workspace-write` + `approval_policy = "never"` so unattended runs do not stall waiting for approval.
- This intentionally trades off some task breadth in favor of deterministic local execution.
- The harness does not commit or merge for you.
- The init wizard can update `~/.codex/config.toml`, but only inside a clearly marked managed block and with a backup created first when the file already exists.

## Recommended next iterations

- add automatic packet linting
- add explicit validation-command execution and capture
- add a supervisor dashboard summary
- add optional commit staging for accepted runs
- add stronger packet-to-review traceability
