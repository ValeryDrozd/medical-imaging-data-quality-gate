from collections import Counter
from pathlib import Path

from quality_gate.checks import check_batch, check_record
from quality_gate.models import (
    DEFAULT_BATCH,
    DEFAULT_TAXONOMY,
    DEFAULT_THRESHOLD,
    Batch,
    BatchResult,
    BatchSummary,
    Reason,
    RecordResult,
    RunOptions,
    Status,
    Taxonomy,
)

STATUS_ORDER: tuple[Status, ...] = ("PASS", "NEEDS_REVIEW", "FAIL")


def summarize(records: list[RecordResult]) -> BatchSummary:
    statuses = dict.fromkeys(STATUS_ORDER, 0)
    failures: Counter[str] = Counter()
    review_ids: list[str] = []
    for record in records:
        statuses[record.status] += 1
        failures.update({reason.code for reason in record.reasons if reason.level == "FAIL"})
        if record.status == "NEEDS_REVIEW" and record.record_id is not None:
            review_ids.append(record.record_id)
    return BatchSummary(
        record_count=len(records),
        status_counts=statuses,
        failure_reason_counts=dict(sorted(failures.items(), key=lambda item: (-item[1], item[0]))),
        review_ids=review_ids,
    )


def validate_batch(
    batch_file: Path = DEFAULT_BATCH,
    taxonomy_file: Path = DEFAULT_TAXONOMY,
    *,
    confidence_threshold: float = DEFAULT_THRESHOLD,
) -> BatchResult:
    """Validate one independent delivery and return a deterministic report."""
    options = RunOptions(confidence_threshold=confidence_threshold)
    batch = Batch.model_validate_json(batch_file.read_bytes())
    taxonomy = Taxonomy.model_validate_json(taxonomy_file.read_bytes())
    check_batch(batch, taxonomy)

    labels = {entry.label for entry in taxonomy.labels}
    records: list[RecordResult] = []
    for index, raw in enumerate(batch.records):
        record_id, reasons = check_record(
            raw,
            labels=labels,
            deprecated=taxonomy.deprecated_aliases,
            threshold=options.confidence_threshold,
        )
        if not reasons:
            reasons.append(
                Reason(code="CHECKS_PASSED", message="All applicable checks passed.", level="PASS")
            )
        status = max((reason.level for reason in reasons), key=STATUS_ORDER.index)
        records.append(
            RecordResult(record_index=index, record_id=record_id, status=status, reasons=reasons)
        )
    return BatchResult(
        batch_id=batch.batch_id,
        taxonomy_version=batch.taxonomy_version,
        mode="metadata_only",
        confidence_threshold=options.confidence_threshold,
        summary=summarize(records),
        records=records,
    )
