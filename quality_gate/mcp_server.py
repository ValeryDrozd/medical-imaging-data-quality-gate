import argparse
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from quality_gate.core import validate_batch
from quality_gate.models import (
    DEFAULT_BATCH,
    DEFAULT_TAXONOMY,
    DEFAULT_THRESHOLD,
    BatchResult,
    ConfidenceThreshold,
    RequestedMode,
)

server = FastMCP(
    "medical-imaging-data-quality-gate",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"],
    ),
)


# Resolve operator input within the server's working directory before the core can read it.
def workspace_file(filename: str) -> Path:
    root = Path.cwd().resolve()
    path = (root / filename).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Input files must be within the server working directory.")
    return path


@server.tool(name="validate_batch", annotations=ToolAnnotations(readOnlyHint=True))
def validate_batch_tool(
    batch_file: str = str(DEFAULT_BATCH),
    taxonomy_file: str = str(DEFAULT_TAXONOMY),
    confidence_threshold: ConfidenceThreshold = DEFAULT_THRESHOLD,
    mode: RequestedMode = "auto",
) -> BatchResult:
    """Validate a local synthetic manifest and return record decisions and a batch summary."""
    return validate_batch(
        workspace_file(batch_file),
        workspace_file(taxonomy_file),
        confidence_threshold=confidence_threshold,
        mode=mode,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the synthetic imaging gate MCP server.")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1", help="bind address for Streamable HTTP")
    args = parser.parse_args()
    server.settings.host = args.host
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
