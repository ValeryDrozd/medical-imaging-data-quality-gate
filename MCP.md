# Run the MCP server

The server exposes `validate_batch` over stdio and Streamable HTTP. Both use the same validation rules and report format as the batch command.

## Docker on this machine

From the repository root, build and start the local MCP service.

```sh
docker compose up -d --build mcp
```

The service publishes `http://127.0.0.1:8000/mcp` on the host loopback and mounts the supplied synthetic manifests and edge-case fixtures read-only. On Docker Desktop, set `DOCKER_CONTEXT=desktop-linux` if that is your active Docker context.

Add the URL in Codex Settings > MCP servers with the Streamable HTTP transport, or run this command.

```sh
codex mcp add quality_gate_docker --url http://127.0.0.1:8000/mcp
```

Restart Codex and check `/mcp` for `quality_gate_docker`. Run `docker compose stop mcp` to stop the service. [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli#configure-with-the-cli)

## Local stdio setup

From the repository root, create a virtual environment and install the project.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
```

The server command is `.venv/bin/python -m quality_gate.mcp_server`. Configure your MCP client to launch it with the repository root as its working directory. For Codex, add the following to your `~/.codex/config.toml`, replacing both paths with your checkout’s absolute path.

```toml
[mcp_servers.quality_gate]
command = "/absolute/path/to/medical-imaging-data-quality-gate/.venv/bin/python"
args = ["-m", "quality_gate.mcp_server"]
cwd = "/absolute/path/to/medical-imaging-data-quality-gate"
```

Restart Codex and use `/mcp` to check that `quality_gate` is connected. [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli#configure-with-configtoml)

## Deploy on a Docker host

On a host you can access with SSH, check out the repository at `/srv/medical-imaging-data-quality-gate` and build the image from the checkout.

```sh
cd /srv/medical-imaging-data-quality-gate
docker compose build gate
```

On your client machine, configure a second stdio server. Replace the example SSH account and checkout path. The SSH account must have key-based access and permission to run Docker Compose on the host.

```toml
[mcp_servers.quality_gate_remote]
command = "ssh"
args = [
  "-T", "-o", "BatchMode=yes", "reviewer@gate.example.com",
  "cd /srv/medical-imaging-data-quality-gate && exec docker compose run --rm -T --entrypoint python gate -m quality_gate.mcp_server",
]
startup_timeout_sec = 30
```

The client starts a container for the MCP session. SSH carries the stdio messages, and Compose mounts the synthetic batch directory read-only. Build the image ahead of time so stdout carries only MCP messages during the session.

## Call `validate_batch`

Use `{}` for the supplied batch with the default threshold of **0.50**. To override it for one call, send a JSON number from 0 to 1 inclusive.

```json
{"confidence_threshold": 0.38}
```

In Codex, ask “Call the `quality_gate_docker` server’s `validate_batch` tool with `confidence_threshold` set to 0.38 and report the status counts.” Use `quality_gate` for local stdio or `quality_gate_remote` for SSH.

The response includes the applied `confidence_threshold`, `summary` and per-record `records`. At 0.50, `IMG-0009` needs review. At 0.38, its confidence equals the threshold and it passes, giving **37 PASS, 13 FAIL and 0 NEEDS_REVIEW**. A later call with `{}` uses 0.50 again.

Optional arguments are `batch_file` (default `task_description/batch.json`), `taxonomy_file` (default `task_description/taxonomy.json`) and `mode` (`auto`, `metadata_only` or `files`). File paths refer to the server’s working directory. For local Docker HTTP, use `task_description/edge_cases/annotation-boundaries.json` to try an edge-case batch.
