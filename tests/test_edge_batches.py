import asyncio
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from quality_gate.core import validate_batch
from quality_gate.models import BatchResult

ROOT = Path(__file__).resolve().parents[1]
EDGE_BATCHES = Path("task_description/edge_cases")
VALID_BATCHES = ("empty", "annotation-boundaries", "record-shapes", "file-metadata")
INVALID_BATCHES = {
    "invalid-count": "record_count does not match",
    "wrong-taxonomy": "versions do not match",
    "truncated": "Invalid JSON",
}


@pytest.mark.parametrize(
    ("name", "statuses", "review_ids", "reasons"),
    [
        ("empty", [], [], {}),
        (
            "annotation-boundaries",
            ["PASS", "NEEDS_REVIEW", "PASS", "PASS", "FAIL", "FAIL", "FAIL"],
            ["ANN-MIN"],
            {
                1: ["CONFIDENCE_LOW"],
                4: [
                    "LABEL_DEPRECATED",
                    "LABEL_UNKNOWN",
                    "BBOX_FORMAT_INVALID",
                    "BBOX_GEOMETRY_INVALID",
                    "BBOX_OUT_OF_BOUNDS",
                    "CONFIDENCE_LOW",
                    "CONFIDENCE_INVALID",
                ],
                5: ["BBOX_FORMAT_INVALID", "BBOX_OUT_OF_BOUNDS", "CONFIDENCE_INVALID"],
                6: ["BBOX_GEOMETRY_INVALID", "BBOX_GEOMETRY_INVALID"],
            },
        ),
        (
            "record-shapes",
            ["FAIL"] * 7 + ["PASS"],
            [],
            {
                0: ["RECORD_INVALID"],
                1: ["RECORD_INVALID"],
                2: ["RECORD_INVALID"],
                3: [
                    "RECORD_ID_INVALID",
                    "IMAGE_DIMENSION_INVALID",
                    "IMAGE_DIMENSION_INVALID",
                    "IMAGE_REFERENCE_MISSING",
                    "SHA256_EXPECTED_INVALID",
                    "ANNOTATIONS_INVALID",
                ],
                4: ["RECORD_ID_INVALID"],
                5: ["ANNOTATIONS_INVALID"],
                6: [
                    "ANNOTATION_INVALID",
                    "ANNOTATION_INVALID",
                    "ANNOTATION_INVALID",
                    "LABEL_UNKNOWN",
                    "BBOX_FORMAT_INVALID",
                    "CONFIDENCE_INVALID",
                ],
            },
        ),
        (
            "file-metadata",
            ["FAIL"] * 7 + ["PASS", "FAIL", "PASS"],
            [],
            {
                0: ["IMAGE_REFERENCE_MISSING"],
                1: ["IMAGE_REFERENCE_INVALID"],
                2: ["IMAGE_REFERENCE_INVALID"],
                3: ["IMAGE_REFERENCE_INVALID"],
                4: ["IMAGE_REFERENCE_INVALID"],
                5: [
                    "IMAGE_DIMENSION_INVALID",
                    "IMAGE_DIMENSION_INVALID",
                    "FILE_SIZE_INVALID",
                    "SHA256_EXPECTED_INVALID",
                    "SHA256_RECEIVED_INVALID",
                ],
                6: ["FILE_EMPTY", "SHA256_MISMATCH"],
                8: ["IMAGE_REFERENCE_INVALID"],
            },
        ),
    ],
)
def test_edge_batch_cli(
    name: str, statuses: list[str], review_ids: list[str], reasons: dict[int, list[str]]
) -> None:
    run = subprocess.run(
        [sys.executable, "-m", "quality_gate", "--batch", str(EDGE_BATCHES / f"{name}.json")],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    report = BatchResult.model_validate_json(run.stdout)
    assert report.mode == "metadata_only"
    assert report.summary.record_count == len(statuses)
    assert report.summary.status_counts == {
        status: statuses.count(status) for status in ("PASS", "FAIL", "NEEDS_REVIEW")
    }
    assert report.summary.review_ids == review_ids
    assert [record.record_index for record in report.records] == list(range(len(statuses)))
    assert [record.status for record in report.records] == statuses
    assert [[reason.code for reason in record.reasons] for record in report.records] == [
        reasons.get(index, ["CHECKS_PASSED"]) for index in range(len(statuses))
    ]
    assert report.summary.failure_reason_counts == Counter(
        code for codes in reasons.values() for code in set(codes) if code != "CONFIDENCE_LOW"
    )


@pytest.mark.parametrize(("name", "message"), INVALID_BATCHES.items())
def test_bad_batch_is_a_cli_input_error(name: str, message: str) -> None:
    run = subprocess.run(
        [sys.executable, "-m", "quality_gate", "--batch", str(EDGE_BATCHES / f"{name}.json")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 2
    assert run.stdout == ""
    assert message in run.stderr
    assert "Traceback" not in run.stderr


def test_mcp_recovers_after_bad_batches() -> None:
    async def check_calls() -> None:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "quality_gate.mcp_server"], cwd=ROOT
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
            await client.initialize()
            for name in INVALID_BATCHES:
                result = await client.call_tool(
                    "validate_batch", {"batch_file": str(EDGE_BATCHES / f"{name}.json")}
                )
                assert result.isError
            for name in VALID_BATCHES:
                batch_file = EDGE_BATCHES / f"{name}.json"
                result = await client.call_tool("validate_batch", {"batch_file": str(batch_file)})
                assert not result.isError
                assert BatchResult.model_validate(result.structuredContent) == validate_batch(
                    ROOT / batch_file, ROOT / "task_description/taxonomy.json"
                )

    asyncio.run(check_calls())
