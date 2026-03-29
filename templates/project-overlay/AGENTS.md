# AGENTS.md

This is a supervised target repository.

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
