# AI log

I built and reviewed the MVP in Codex desktop with the `gpt-6.2-sol` model. I used Docker Compose to run the synthetic batches, Ruff and pytest for checks, and GitHub CLI and the GitHub connector for repository work. A Codex CLI smoke run verified that the Stop hook ran Ruff and pytest automatically.

## Prompt excerpts

1. “MCP is mandatory. Expose a `validate_batch` tool that calls the same Python core as the CLI.” This drove the shared core and the parity tests.
2. “Find if there are any edge cases, generate more batches in several files” led to seven synthetic fixtures and tests that verify recovery after invalid manifests.
3. “All checks should be in a separate file, and each should be described in comment above it” led to the rules moving into `quality_gate/checks.py`.

## Mistake and verification

I read the brief’s mention of missing and corrupted images as a requirement to inspect PNG bytes. I added automatic image-file detection, an optional file mode, and a Pillow dependency. During a manual code review, the user pointed out that the project contained no PNGs. I rechecked the brief and the supplied inputs. The deliverable was a gate for the synthetic batch and taxonomy JSON. The extra mode added code and tests outside that scope, and my proposed PNG performance improvement would have had no effect on the demo batch.

I removed the file mode, detection, decoding, and Pillow. The gate still validates declared image references, sizes, and hashes and reports `metadata_only`. Docker Compose reproduced the original report byte for byte with 36 PASS, 13 FAIL, and `IMG-0009` as the only record needing review. Ruff and all 30 tests passed.
