import argparse
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ContentBlock, Tool, ToolAnnotations
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from quality_gate.core import validate_batch
from quality_gate.models import (
    DEFAULT_BATCH,
    DEFAULT_TAXONOMY,
    DEFAULT_THRESHOLD,
    BatchResult,
    ConfidenceThreshold,
)

logger = logging.getLogger(__name__)
TOOL_NAME = "validate_batch"
ErrorCode = Literal[
    "INVALID_ARGUMENTS",
    "INVALID_THRESHOLD",
    "INPUT_PATH_INVALID",
    "INPUT_UNAVAILABLE",
    "INVALID_BATCH_INPUT",
    "INTERNAL_ERROR",
]


class BatchArguments(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    batch_file: str = str(DEFAULT_BATCH)
    taxonomy_file: str = str(DEFAULT_TAXONOMY)
    confidence_threshold: ConfidenceThreshold = DEFAULT_THRESHOLD


class ToolErrorDetails(BaseModel):
    code: ErrorCode
    message: str


class ToolFailure(BaseModel):
    error: ToolErrorDetails


def failure(code: ErrorCode, message: str) -> dict[str, object]:
    return ToolFailure(error=ToolErrorDetails(code=code, message=message)).model_dump(mode="json")


# Resolve operator input within the server's working directory before the core can read it.
def workspace_file(filename: str) -> Path:
    root = Path.cwd().resolve()
    path = (root / filename).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Input files must be within the server working directory.")
    if not path.is_file():
        raise OSError("Input must be an existing regular file.")
    return path


# Handle argument validation here so FastMCP cannot turn bad tool arguments into tool errors.
class GateMCP(FastMCP):
    async def list_tools(self) -> list[Tool]:
        return [
            Tool(
                name=TOOL_NAME,
                description="Validate a synthetic manifest and return a report or an error result.",
                inputSchema=BatchArguments.model_json_schema(),
                outputSchema={
                    "type": "object",
                    **TypeAdapter(BatchResult | ToolFailure).json_schema(),
                },
                annotations=ToolAnnotations(readOnlyHint=True),
            )
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, object]
    ) -> Sequence[ContentBlock] | dict[str, object]:
        if name != TOOL_NAME:
            return await super().call_tool(name, arguments)
        try:
            inputs = BatchArguments.model_validate(arguments)
        except ValidationError as error:
            if error.errors(include_input=False)[0]["loc"] == ("confidence_threshold",):
                return failure("INVALID_THRESHOLD", "Confidence threshold must be between 0 and 1.")
            return failure("INVALID_ARGUMENTS", "Use the arguments listed in the tool schema.")
        try:
            try:
                batch_file = workspace_file(inputs.batch_file)
                taxonomy_file = workspace_file(inputs.taxonomy_file)
            except (ValueError, RuntimeError):
                return failure("INPUT_PATH_INVALID", "Use valid paths inside the server workspace.")
            result = validate_batch(
                batch_file, taxonomy_file, confidence_threshold=inputs.confidence_threshold
            )
            return result.model_dump(mode="json")
        except OSError:
            return failure("INPUT_UNAVAILABLE", "The batch or taxonomy file could not be read.")
        except ValueError:
            return failure(
                "INVALID_BATCH_INPUT",
                "Check the JSON, declared record count, and taxonomy version.",
            )
        except Exception:
            logger.exception("Batch validation failed unexpectedly")
            return failure("INTERNAL_ERROR", "Batch validation failed unexpectedly.")


server = GateMCP(
    "medical-imaging-data-quality-gate",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"],
    ),
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
