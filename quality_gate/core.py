from collections import Counter
from os.path import realpath
from pathlib import Path

from quality_gate.checks import check_batch, check_record, image_path
from quality_gate.models import (
    DEFAULT_BATCH,
    DEFAULT_TAXONOMY,
    DEFAULT_THRESHOLD,
    Batch,
    BatchResult,
    BatchSummary,
    Mode,
    Reason,
    RecordResult,
    RequestedMode,
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
    mode: RequestedMode = "auto",
) -> BatchResult:
    """Validate one independent delivery and return a deterministic report."""
    options = RunOptions(confidence_threshold=confidence_threshold, mode=mode)
    batch_file = Path(realpath(batch_file, strict=True))
    batch = Batch.model_validate_json(batch_file.read_bytes())
    taxonomy = Taxonomy.model_validate_json(taxonomy_file.read_bytes())
    check_batch(batch, taxonomy)

    references = [
        image_path(
            record.get("image_file") if isinstance(record, dict) else None,
            batch_file.parent,
            probe=options.mode == "auto",
        )
        for record in batch.records
    ]
    actual_mode: Mode
    if options.mode == "auto":
        files_available = any(available for _, available in references)
        actual_mode = "files" if files_available else "metadata_only"
    else:
        actual_mode = options.mode
    labels = {entry.label for entry in taxonomy.labels}
    records: list[RecordResult] = []
    for index, (raw, (path, _)) in enumerate(zip(batch.records, references, strict=True)):
        record_id, reasons = check_record(
            raw,
            path,
            actual_mode,
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
        mode=actual_mode,
        confidence_threshold=options.confidence_threshold,
        summary=summarize(records),
        records=records,
    )
