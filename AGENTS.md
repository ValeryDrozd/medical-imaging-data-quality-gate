# Project instructions

- Use only the supplied synthetic batch and taxonomy for demo runs. Preserve their contents. Keep the original challenge documents and personal notes local.
- Put validation rules in `quality_gate/checks.py` with a comment above each rule. Keep batch orchestration, status precedence and aggregation in `quality_gate/core.py`. Keep the CLI and MCP adapters thin and reason codes stable.
- Use explicit Python type hints. Validate inputs with Pydantic and test changes with pytest. Match the code and acceptance criteria when changing behavior.
- Docker and GitHub Actions use Python 3.12. From the repository root, prepare local development with `python3 -m venv .venv` and `.venv/bin/python -m pip install '.[dev]'`.
- Run `sh scripts/check.sh` before committing. CI and the Codex Stop hook invoke this script for Ruff lint, format checks and pytest.
- To enable automatic checks on a new Codex installation, trust the project, review the project Stop hook under `/hooks`, and trust its definition. The most recent run writes `.codex-checks.log`. [Codex hook documentation](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks)
- To regenerate the checked-in report, run `sh scripts/run-batch.sh > examples/batch-result.json` with Docker running. Pass the same flags to the Python CLI and the Compose script.
- Use the [Angular commit skill](.agents/skills/angular-commit/SKILL.md) for `type(scope): subject` commit messages.
