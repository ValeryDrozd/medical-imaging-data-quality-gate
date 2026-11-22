from pathlib import Path

from mcp.server.fastmcp import FastMCP

from quality_gate.core import validate_batch
from quality_gate.models import (
    DEFAULT_BATCH,
    DEFAULT_TAXONOMY,
    DEFAULT_THRESHOLD,
    BatchResult,
    RequestedMode,
)

server = FastMCP("medical-imaging-data-quality-gate")


def workspace_file(filename: str) -> Path:
    root = Path.cwd().resolve()
    path = (root / filename).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Input files must be within the server working directory.")
    return path


@server.tool(name="validate_batch")
def validate_batch_tool(
    batch_file: str = str(DEFAULT_BATCH),
    taxonomy_file: str = str(DEFAULT_TAXONOMY),
    confidence_threshold: float = DEFAULT_THRESHOLD,
    mode: RequestedMode = "auto",
) -> BatchResult:
    """Validate a local synthetic manifest and return record decisions and a batch summary."""
    return validate_batch(
        workspace_file(batch_file),
        workspace_file(taxonomy_file),
        confidence_threshold=confidence_threshold,
        mode=mode,
    )


if __name__ == "__main__":
    server.run(transport="stdio")
