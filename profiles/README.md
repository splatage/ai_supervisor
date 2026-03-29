# Profiles

`config.toml.example` is a **merge template**, not a file you should blindly drop over your existing `~/.codex/config.toml`.

Recommended approach:

1. Review the file.
2. Copy the sections you want into `~/.codex/config.toml`.
3. Adjust model, approval, and verbosity settings to your taste.
4. Keep `review_model = "gpt-5.4"` if you want review passes pinned to the same model family.

The runner scripts do not rely solely on profiles; they also pass explicit command-line overrides for critical task execution settings.
