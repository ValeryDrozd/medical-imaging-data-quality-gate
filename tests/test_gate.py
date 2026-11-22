import asyncio
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image
from pydantic import JsonValue

from quality_gate.core import validate_batch
from quality_gate.models import BatchResult, Status

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "task_description/batch.json"
TAXONOMY = ROOT / "task_description/taxonomy.json"
Record = dict[str, JsonValue]


@pytest.fixture
def sample_record() -> Record:
    record: Record = json.loads(BATCH.read_text(encoding="utf-8"))["records"][0]
    return record


@pytest.fixture
def write_batch(tmp_path: Path) -> Callable[..., Path]:
    def write(records: list[JsonValue], **overrides: JsonValue) -> Path:
        path = tmp_path / "batch.json"
        batch = {
            "batch_id": "BATCH-TEST",
            "taxonomy_version": "1.2",
            "record_count": len(records),
            "records": records,
            **overrides,
        }
        path.write_text(json.dumps(batch), encoding="utf-8")
        return path

    return write


def test_supplied_batch() -> None:
    result = validate_batch(BATCH, TAXONOMY)
    captured = ROOT / "examples/batch-result.json"
    assert BatchResult.model_validate_json(captured.read_bytes()) == result
    assert result.mode == "metadata_only"
    assert result.summary.record_count == len(result.records) == 50
    assert result.summary.status_counts == {"PASS": 36, "FAIL": 13, "NEEDS_REVIEW": 1}
    assert result.summary.review_ids == ["IMG-0009"]
    assert result.summary.failure_reason_counts == {
        "BBOX_FORMAT_INVALID": 1,
        "BBOX_GEOMETRY_INVALID": 1,
        "BBOX_OUT_OF_BOUNDS": 1,
        "CONFIDENCE_INVALID": 2,
        "FILE_EMPTY": 1,
        "IMAGE_DIMENSION_INVALID": 1,
        "IMAGE_REFERENCE_MISSING": 2,
        "LABEL_DEPRECATED": 1,
        "LABEL_UNKNOWN": 2,
        "SHA256_MISMATCH": 2,
    }
    by_id = {record.record_id: record for record in result.records}
    assert by_id["IMG-0009"].reasons[0].code == "CONFIDENCE_LOW"
    assert by_id["IMG-0037"].reasons[0].code == "BBOX_FORMAT_INVALID"
    assert by_id["IMG-0043"].reasons[0].code == "LABEL_DEPRECATED"


def test_pipeline_keeps_independent_reasons(
    sample_record: Record, write_batch: Callable[..., Path]
) -> None:
    sample_record["image_width"] = 0
    sample_record["annotations"] = [
        None,
        {"label": "lesion", "bbox": [1, 1, 1], "confidence": 0.3},
        {"label": "mass", "bbox": [1000, 1, 1000, 1024], "confidence": 1.5},
    ]
    result = validate_batch(write_batch([sample_record, None]), TAXONOMY)
    first, second = result.records
    assert first.status == second.status == "FAIL"
    assert [(reason.code, reason.annotation_index) for reason in first.reasons] == [
        ("IMAGE_DIMENSION_INVALID", None),
        ("ANNOTATION_INVALID", 0),
        ("LABEL_DEPRECATED", 1),
        ("BBOX_FORMAT_INVALID", 1),
        ("BBOX_OUT_OF_BOUNDS", 2),
        ("CONFIDENCE_LOW", 1),
        ("CONFIDENCE_INVALID", 2),
    ]
    assert first.reasons[4].message.endswith("image height.")
    assert second.record_id is None
    assert second.record_index == 1
    assert second.reasons[0].code == "RECORD_INVALID"
    assert result.summary.review_ids == []


@pytest.mark.parametrize(
    ("confidence", "threshold", "status"),
    [
        (0, 0.50, "NEEDS_REVIEW"),
        (0.49, 0.50, "NEEDS_REVIEW"),
        (0.50, 0.50, "PASS"),
        (1, 1, "PASS"),
        (0.49, 0.49, "PASS"),
        (-0.01, 0.50, "FAIL"),
        (1.01, 0.50, "FAIL"),
        (True, 0.50, "FAIL"),
        ("0.49", 0.50, "FAIL"),
    ],
)
def test_confidence_and_box_edge(
    confidence: JsonValue,
    threshold: float,
    status: Status,
    sample_record: Record,
    write_batch: Callable[..., Path],
) -> None:
    sample_record["annotations"] = [
        {"label": "nodule", "bbox": [0.1, 1, 1023.9, 1023], "confidence": confidence},
    ]
    result = validate_batch(write_batch([sample_record]), TAXONOMY, confidence_threshold=threshold)
    assert result.records[0].status == status
    assert all(not reason.code.startswith("BBOX_") for reason in result.records[0].reasons)


def test_empty_annotations_pass(sample_record: Record, write_batch: Callable[..., Path]) -> None:
    sample_record["annotations"] = []
    result = validate_batch(write_batch([sample_record]), TAXONOMY)
    assert result.records[0].status == "PASS"
    assert result.records[0].reasons[0].code == "CHECKS_PASSED"


def test_invalid_batch_inputs(write_batch: Callable[..., Path]) -> None:
    with pytest.raises(ValueError, match="record_count does not match"):
        validate_batch(write_batch([], record_count=1), TAXONOMY)
    with pytest.raises(ValueError, match="versions do not match"):
        validate_batch(write_batch([], taxonomy_version="0.0"), TAXONOMY)
    with pytest.raises(ValueError, match="confidence_threshold"):
        validate_batch(write_batch([]), TAXONOMY, confidence_threshold=1.1)


def test_file_mode(sample_record: Record, write_batch: Callable[..., Path], tmp_path: Path) -> None:
    image_file = tmp_path / "test.png"
    with Image.new("L", (2, 2)) as image:
        image.save(image_file)
    data = image_file.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    sample_record.update(
        image_file=image_file.name,
        image_width=2,
        image_height=2,
        file_size_bytes=len(data),
        sha256_expected=digest,
        sha256_received=digest.upper(),
        annotations=[],
    )
    other = sample_record | {"record_id": "MISSING", "image_file": "missing.png"}
    result = validate_batch(write_batch([sample_record, other]), TAXONOMY)
    assert result.mode == "files"
    assert result.records[0].status == "PASS"
    assert result.records[1].reasons[0].code == "IMAGE_FILE_MISSING"

    wrong_dimensions = sample_record | {"image_width": 3}
    result = validate_batch(write_batch([wrong_dimensions]), TAXONOMY)
    assert result.records[0].reasons[0].code == "IMAGE_DIMENSIONS_MISMATCH"

    image_file.write_bytes(data[:20])
    result = validate_batch(write_batch([sample_record]), TAXONOMY)
    assert [reason.code for reason in result.records[0].reasons] == [
        "FILE_SIZE_MISMATCH",
        "FILE_SHA256_MISMATCH",
        "IMAGE_FILE_CORRUPT",
    ]

    image_file.unlink()
    result = validate_batch(write_batch([sample_record]), TAXONOMY, mode="files")
    assert result.mode == "files"
    assert result.records[0].reasons[0].code == "IMAGE_FILE_MISSING"


def test_escaping_image_path(sample_record: Record, write_batch: Callable[..., Path]) -> None:
    sample_record["image_file"] = "../outside.png"
    result = validate_batch(write_batch([sample_record]), TAXONOMY)
    assert result.records[0].reasons[0].code == "IMAGE_REFERENCE_INVALID"


def test_cli_and_mcp_return_the_core_report() -> None:
    expected = validate_batch(BATCH, TAXONOMY)
    cli = subprocess.run(
        [sys.executable, "-m", "quality_gate"], cwd=ROOT, check=True, capture_output=True
    )
    assert BatchResult.model_validate_json(cli.stdout) == expected

    async def call_tool() -> BatchResult:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "quality_gate.mcp_server"], cwd=ROOT
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
            await client.initialize()
            tools = await client.list_tools()
            assert [tool.name for tool in tools.tools] == ["validate_batch"]
            result = await client.call_tool("validate_batch")
            assert not result.isError
            assert result.structuredContent is not None
            return BatchResult.model_validate(result.structuredContent)

    assert asyncio.run(call_tool()) == expected
