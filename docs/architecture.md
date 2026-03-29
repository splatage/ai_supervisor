# Architecture

## Purpose

`ai_supervisor` is a reusable harness for running Codex workers against a target Git repository under the authority of a supervising operator.

The harness is intentionally separate from the target repo so that orchestration logic does not become entangled with product-specific architecture.

## Layers

### 1. Human supervisor
The human sets project direction, writes or approves task packets, and makes the final accept/reject decision.

### 2. Harness
The harness performs repeatable local orchestration:

- copies the project overlay into a target repo
- loads task packets
- creates run directories
- creates isolated Git worktrees
- builds worker and review prompts
- runs Codex non-interactively
- saves structured outputs and raw transcripts
- performs basic scope auditing

### 3. Codex worker
A worker is a non-interactive `codex exec` run against one isolated worktree.

The worker is constrained by:

- the task packet
- the target repo overlay
- the writable-path allowlist
- the chosen sandbox and approval settings
- the final response schema

### 4. Codex reviewer
A reviewer is a second non-interactive `codex exec review` run over the worker worktree.

The reviewer evaluates:

- whether the returned changes solve the requested task
- whether the work violates stated invariants
- whether the changed files are suspicious
- whether rework is required

### 5. Target repo overlay
The target repo receives a thin supervisory overlay:

- `AGENTS.md`
- `SUPERVISOR/REQUIREMENTS.md`
- `SUPERVISOR/INVARIANTS.md`
- `SUPERVISOR/ALLOWED_PATHS.md`
- `SUPERVISOR/DONE_CRITERIA.md`
- `SUPERVISOR/TASKS/`
- `SUPERVISOR/RUNS/`
- `SUPERVISOR/REVIEWS/`

This is the durable project-specific truth that workers must consume.

## Drift controls

### Scope drift
Workers only receive the writable paths listed in the task packet. The harness audits changed files and flags out-of-scope modifications.

### Requirement drift
Task packets embed explicit goals, constraints, and done criteria. Workers are instructed not to infer missing requirements.

### Evaluation drift
The worker report and review report use strict JSON schemas so the supervisor can evaluate machine-readable outputs instead of loose prose alone.

### Context drift
Every run records:

- target repo path
- base ref
- worker branch
- worktree path
- task packet copy
- prompt files
- changed files
- diff patch
- transcripts

## Why worktrees

Worktrees are the cleanest local isolation boundary for this workflow:

- no shared dirty working tree
- simpler diff inspection
- easier branch-per-worker discipline
- lower risk of one worker contaminating another

## Why non-interactive workers

Interactive workers are harder to reproduce and harder to compare. Non-interactive workers make the run more auditable and easier to automate.

## Why `approval_policy = "never"` for workers

This harness is intended for unattended worker lanes. Prompt-based approvals would stall the lane and make automation brittle.

The design therefore prefers:

- sandboxed workers
- narrower task packets
- review after the fact

instead of:

- broad workers waiting on live approvals

## What this version is not

- not a cloud orchestrator
- not a merge bot
- not a full multi-agent planner
- not a replacement for human architectural judgment

It is a local, disciplined orchestration scaffold.
