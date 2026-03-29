# Profiles

`config.toml.example` is a **merge template**, not a file you should blindly drop over your existing `~/.codex/config.toml`.

You now have two supported setup paths:

1. **Guided path**: run `./scripts/init-environment.sh` and let the wizard install or refresh the managed block in your Codex config.
2. **Manual path**: review `config.toml.example`, then copy the relevant sections into `~/.codex/config.toml` yourself.

Recommended approach for the guided path:

- let the wizard manage only the clearly marked `ai_supervisor managed block`
- keep all unrelated personal Codex settings outside that block
- rerun the wizard when you want to refresh the harness profiles or project trust entries

Recommended approach for the manual path:

1. Review the file.
2. Copy the sections you want into `~/.codex/config.toml`.
3. Adjust model, approval, and verbosity settings to your taste.
4. Keep `review_model = "gpt-5.4"` if you want review passes pinned to the same model family.

The runner scripts do not rely solely on profiles; they also pass explicit command-line overrides for critical task execution settings.
