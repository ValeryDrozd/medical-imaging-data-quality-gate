# AI log

I built and reviewed the MVP in Codex desktop with the `gpt-6.2-sol` model. I used Docker Compose to run the synthetic batches, Ruff and pytest for checks, and GitHub CLI and the GitHub connector for repository work. A Codex CLI smoke run verified that the Stop hook ran Ruff and pytest automatically.

## Prompt excerpts

1. “MCP is mandatory. Expose a `validate_batch` tool that calls the same Python core as the CLI.” This drove the shared core and the parity tests.
2. “Find if there are any edge cases, generate more batches in several files” led to seven synthetic fixtures and tests that verify recovery after invalid manifests.
3. “All checks should be in a separate file, and each should be described in comment above it” led to the rules moving into `quality_gate/checks.py`.

## Mistake and verification

In the earlier optional file mode, I initially relied on Pillow's `verify()` and `load()` to validate an entire PNG. A sweep of 68 truncated versions of a blank test image found four that passed when their declared sizes and hashes matched the remaining bytes. An explicit final-chunk and checksum check caught all 68. The project later narrowed the gate to the supplied JSON and retired that mode.

Ruff and 27 pytest tests passed. The Docker MCP tool returned 36 PASS, 13 FAIL and 1 NEEDS_REVIEW for `IMG-0009` when called from this Codex session. The 0.38 override was verified separately and moved `IMG-0009` to PASS for that call.
