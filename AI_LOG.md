# AI log

I built the MVP in the Codex desktop app with the `gpt-6.2-sol` model. Codex inspected the supplied fixtures, edited the project and ran Docker Compose, Ruff, pytest and GitHub CLI. A Codex CLI smoke run verified that the Stop hook executed Ruff and pytest automatically.

Three excerpts from real prompts used during the work

1. “MCP is mandatory. Expose a `validate_batch` tool that calls the same Python core as the CLI.” This drove the shared core and the stdio parity test.
2. “With the stated policy, the supplied batch should produce 36 PASS, 13 FAIL, and 1 NEEDS_REVIEW (`IMG-0009`). Verify this with an integration test.” This became the regression test for the real fixture.
3. “Reply with the single word verified. Do not call tools or edit files.” I sent this to the CLI so the check log could only come from the automatic Stop hook during that smoke run.

I initially redirected `docker compose run --build` into the result file. The installed Compose release wrote build progress to stdout, and `jq` rejected the file. I moved the build into the same one-command script with its output redirected to stderr, then reran the batch and verified that the resulting file parsed as JSON and matched the Python CLI report.
