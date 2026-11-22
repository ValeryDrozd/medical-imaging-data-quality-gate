from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

Status = Literal["PASS", "FAIL", "NEEDS_REVIEW"]
Mode = Literal["metadata_only", "files"]
RequestedMode = Literal["auto", "metadata_only", "files"]
ConfidenceThreshold = Annotated[
    float,
    Field(
        strict=True,
        ge=0,
        le=1,
        allow_inf_nan=False,
        description="Send valid confidence scores below this threshold to review for this call.",
    ),
]

DEFAULT_BATCH = Path("task_description/batch.json")
DEFAULT_TAXONOMY = Path("task_description/taxonomy.json")
DEFAULT_THRESHOLD = 0.50


class Batch(BaseModel):
    model_config = ConfigDict(strict=True)

    batch_id: str = Field(min_length=1)
    taxonomy_version: str = Field(min_length=1)
    record_count: int = Field(ge=0)
    records: list[JsonValue]


class Label(BaseModel):
    label: str = Field(min_length=1)


class Taxonomy(BaseModel):
    model_config = ConfigDict(strict=True)

    taxonomy_version: str = Field(min_length=1)
    labels: list[Label] = Field(min_length=1)
    deprecated_aliases: dict[str, str]


class RunOptions(BaseModel):
    confidence_threshold: ConfidenceThreshold = DEFAULT_THRESHOLD
    mode: RequestedMode = "auto"


class Reason(BaseModel):
    code: str
    message: str
    level: Status = "FAIL"
    annotation_index: int | None = None


class RecordResult(BaseModel):
    record_index: int
    record_id: str | None
    status: Status
    reasons: list[Reason]


class BatchSummary(BaseModel):
    record_count: int
    status_counts: dict[Status, int]
    failure_reason_counts: dict[str, int]
    review_ids: list[str]


class BatchResult(BaseModel):
    batch_id: str
    taxonomy_version: str
    mode: Mode
    confidence_threshold: float
    summary: BatchSummary
    records: list[RecordResult]
