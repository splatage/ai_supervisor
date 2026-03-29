# Codex grounding notes

This scaffold is intentionally aligned to the current Codex CLI surface, not to an imagined tool.

## Important grounded assumptions

The current Codex CLI exposes:

- `codex exec` for non-interactive runs
- `codex review` as a non-interactive review surface
- `-m/--model` for model selection on exec
- `-p/--profile` for named config profiles
- `-C/--cd` for working directory selection
- `--sandbox` for sandbox mode
- `--output-schema` for structured final output
- `-o/--output-last-message` for saving the final response
- `--json` for JSONL event output

The current config surface includes:

- `model`
- `model_reasoning_effort`
- `model_verbosity`
- `approval_policy`
- `sandbox_mode`
- `profiles`
- `projects`
- `review_model`
- `project_doc_fallback_filenames`
- `project_doc_max_bytes`

## Design consequence

The harness uses:

- `codex exec` for worker runs
- `codex exec review` for structured review runs
- `--output-schema` + `-o` for machine-readable reports
- explicit task packets instead of ad hoc freeform prompts
- worktree isolation instead of shared-branch concurrency

## Conservative choices

This version intentionally avoids relying on unstable or unclear features.

For example:

- no automatic merge
- no forced feature-flag activation
- no assumption that local project config is auto-loaded from a repo-specific path
- no hidden dependence on approval prompts during unattended runs
