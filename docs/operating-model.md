# Operating model

## Normal loop

1. Bootstrap the target repo overlay.
2. Fill in project-wide truths in the target repo.
3. Write a task packet.
4. Spawn one or more workers on non-overlapping scopes.
5. Review each returned lane.
6. Accept, reject, or revise.
7. Only then consider commit or merge.

## Supervisor packet discipline

A good task packet should be narrow enough that a rejection is cheap.

Prefer:

- one bug
- one refactor seam
- one documentation correction
- one bounded implementation slice

Avoid:

- broad “fix the architecture”
- mixed feature + refactor + test + docs bundles
- multiple unrelated writable areas

## Suggested worker role split

### Implementer
Writes code and returns a structured worker report.

### Reviewer
Performs code review over uncommitted changes and returns a structured review report.

### Analyst
Reads the repo and returns facts or traces without changing files.

### Test author
Adds or updates tests only, with a separate writable-path allowlist.

## Acceptance logic

The supervisor should reject or rework when any of these are true:

- out-of-scope files changed
- worker assumptions changed product behavior
- invariants were ignored
- unresolved risks are too material
- the review report contains blocking findings
- the change is technically correct but architecturally off-shape

## Audit trail

Every run should leave enough evidence for later inspection without reopening the full interaction:

- task packet
- generated worker prompt
- generated review prompt
- structured worker report
- structured review report
- changed-file list
- diff patch
- scope audit
- stdout/stderr transcripts

## First testing plan

Use a harmless test repo first.

### Suggested test sequence

1. documentation-only edit
2. single-file bug fix
3. two-worker non-overlapping change
4. deliberate out-of-scope worker request to test rejection
5. deliberate vague task packet to see how the worker behaves
6. review-only lane over a known-bad diff

## Metrics worth watching

- percent of runs with out-of-scope file changes
- percent of runs rejected after review
- time from task packet to review output
- rate of silent requirement inference
- rate of worker confusion from vague packets
- difference in quality between narrow and broad packets
