# AGENTS.md

This repository is a harness for supervising Codex CLI worker lanes.

## Primary rule

Do not silently expand scope.

## Operating intent

All changes in this repository must strengthen one or more of the following:

- supervisor authority
- drift resistance
- worker isolation
- evaluation clarity
- auditability
- local usability on Linux

## Constraints

- Prefer explicit contracts over clever prompting.
- Prefer narrow task packets over broad open-ended instructions.
- Prefer worktree isolation over shared mutable state.
- Prefer machine-readable artifacts when a later evaluation step will consume them.
- Do not add autonomous merge or destructive automation without explicit design approval.
- Do not weaken writable-path controls or review requirements without explicit design approval.
- Avoid product-specific assumptions; this repo is a general orchestration harness.

## File ownership guidance

- `schema/` defines machine-readable contracts.
- `templates/` defines reusable project and task scaffolds.
- `scripts/` contains the working local runner.
- `docs/` explains system design and operating procedure.
- `profiles/` contains Codex config examples, not authoritative user config.

## Preferred change style

- Keep scripts small and legible.
- Keep JSON schemas strict.
- Keep docs aligned to the actual runner behavior.
- When changing contracts, update the relevant template, schema, and doc together.
