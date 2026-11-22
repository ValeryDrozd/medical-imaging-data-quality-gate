import hashlib
import math
import re
from collections import Counter
from collections.abc import Callable, Iterator
from fractions import Fraction
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import TypeGuard

from PIL import Image
from pydantic import JsonValue

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

Fields = dict[str, JsonValue]
AnnotationCheck = Callable[[Fields, int], Iterator[Reason]]
STATUS_ORDER: tuple[Status, ...] = ("PASS", "NEEDS_REVIEW", "FAIL")
SHA256 = re.compile(r"[0-9a-fA-F]{64}")


def positive_int(value: JsonValue) -> TypeGuard[int]:
    return type(value) is int and value > 0


def finite_number(value: JsonValue) -> TypeGuard[int | float]:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def image_path(reference: JsonValue, root: Path) -> Path | None:
    if not isinstance(reference, str) or not reference.strip() or Path(reference).is_absolute():
        return None
    try:
        path = (root / reference).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return path if path.is_relative_to(root) else None


def sha256_value(value: JsonValue) -> str | None:
    return value.lower() if isinstance(value, str) and SHA256.fullmatch(value) else None


def check_file(
    path: Path, record: Fields, expected: str | None, received: str | None
) -> Iterator[Reason]:
    try:
        if not path.is_file():
            yield Reason(code="IMAGE_FILE_MISSING", message="The referenced PNG is unavailable.")
            return
        data = path.read_bytes()
    except OSError:
        yield Reason(code="IMAGE_FILE_UNREADABLE", message="The referenced PNG could not be read.")
        return

    size = record.get("file_size_bytes")
    if type(size) is int and size >= 0 and len(data) != size:
        yield Reason(code="FILE_SIZE_MISMATCH", message="Actual and declared file sizes differ.")
    digest = hashlib.sha256(data).hexdigest()
    if any(value is not None and value != digest for value in (expected, received)):
        yield Reason(
            code="FILE_SHA256_MISMATCH", message="Actual SHA-256 differs from declarations."
        )
    if not data:
        if size != 0:
            yield Reason(code="FILE_EMPTY", message="The referenced PNG is empty.")
        return

    try:
        with Image.open(BytesIO(data), formats=("PNG",)) as image:
            image.verify()
        with Image.open(BytesIO(data), formats=("PNG",)) as image:
            image.load()
            dimensions = image.size
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        yield Reason(
            code="IMAGE_FILE_CORRUPT", message="The referenced file is not a decodable PNG."
        )
        return
    for field, actual in zip(("image_width", "image_height"), dimensions, strict=True):
        declared = record.get(field)
        if positive_int(declared) and declared != actual:
            yield Reason(
                code="IMAGE_DIMENSIONS_MISMATCH", message=f"Actual and declared {field} differ."
            )


def check_metadata(record: Fields, path: Path | None, mode: Mode) -> Iterator[Reason]:
    for field in ("image_width", "image_height"):
        if not positive_int(record.get(field)):
            yield Reason(
                code="IMAGE_DIMENSION_INVALID", message=f"{field} must be a positive integer."
            )

    reference = record.get("image_file")
    if reference is None or (isinstance(reference, str) and not reference.strip()):
        yield Reason(code="IMAGE_REFERENCE_MISSING", message="image_file is missing or blank.")
    elif path is None:
        yield Reason(
            code="IMAGE_REFERENCE_INVALID",
            message="image_file must stay within the batch directory.",
        )

    size = record.get("file_size_bytes")
    if type(size) is int and size == 0:
        yield Reason(code="FILE_EMPTY", message="The declared file size is zero bytes.")
    elif (path is not None or size is not None) and not positive_int(size):
        yield Reason(
            code="FILE_SIZE_INVALID", message="file_size_bytes must be a positive integer."
        )

    expected = sha256_value(record.get("sha256_expected"))
    received_raw = record.get("sha256_received")
    received = sha256_value(received_raw)
    if expected is None:
        yield Reason(
            code="SHA256_EXPECTED_INVALID", message="Expected SHA-256 must be 64 hex digits."
        )
    if received is None and (path is not None or received_raw is not None):
        yield Reason(
            code="SHA256_RECEIVED_INVALID", message="Received SHA-256 must be 64 hex digits."
        )
    if expected is not None and received is not None and expected != received:
        yield Reason(
            code="SHA256_MISMATCH", message="Declared expected and received SHA-256 differ."
        )

    if mode == "files" and path is not None:
        yield from check_file(path, record, expected, received)


def check_label(
    annotation: Fields, index: int, *, labels: set[str], deprecated: dict[str, str]
) -> Iterator[Reason]:
    label = annotation.get("label")
    if isinstance(label, str) and label in deprecated:
        yield Reason(
            code="LABEL_DEPRECATED",
            message=f"Label {label!r} is deprecated. {deprecated[label]}.",
            annotation_index=index,
        )
    elif not isinstance(label, str) or label not in labels:
        yield Reason(
            code="LABEL_UNKNOWN",
            message=f"Label {label!r} is outside the taxonomy.",
            annotation_index=index,
        )


def check_bbox(annotation: Fields, index: int, *, record: Fields) -> Iterator[Reason]:
    box = annotation.get("bbox")
    if not isinstance(box, list) or len(box) != 4 or not all(map(finite_number, box)):
        yield Reason(
            code="BBOX_FORMAT_INVALID",
            message="bbox must contain four finite numbers [x, y, width, height].",
            annotation_index=index,
        )
        return
    coordinates = [Fraction(str(value)) for value in box]
    x, y, width, height = coordinates
    for axis, origin, extent in (("width", x, width), ("height", y, height)):
        limit = record.get(f"image_{axis}")
        if origin < 0 or extent <= 0:
            yield Reason(
                code="BBOX_GEOMETRY_INVALID",
                message=f"On the {axis} axis, origin must be nonnegative and extent positive.",
                annotation_index=index,
            )
        elif positive_int(limit) and origin + extent > limit:
            yield Reason(
                code="BBOX_OUT_OF_BOUNDS",
                message=f"The box extends beyond the image {axis}.",
                annotation_index=index,
            )


def check_confidence(annotation: Fields, index: int, *, threshold: float) -> Iterator[Reason]:
    value = annotation.get("confidence")
    if not finite_number(value) or not 0 <= value <= 1:
        yield Reason(
            code="CONFIDENCE_INVALID",
            message="Confidence must be a finite number in [0, 1].",
            annotation_index=index,
        )
    elif value < threshold:
        yield Reason(
            code="CONFIDENCE_LOW",
            message=f"Confidence {value} is below the review threshold {threshold}.",
            level="NEEDS_REVIEW",
            annotation_index=index,
        )


def check_annotations(
    record: Fields, labels: set[str], deprecated: dict[str, str], threshold: float
) -> Iterator[Reason]:
    annotations = record.get("annotations")
    if not isinstance(annotations, list):
        yield Reason(code="ANNOTATIONS_INVALID", message="annotations must be an array.")
        return
    valid: list[tuple[int, Fields]] = []
    for index, annotation in enumerate(annotations):
        if isinstance(annotation, dict):
            valid.append((index, annotation))
        else:
            yield Reason(
                code="ANNOTATION_INVALID",
                message="Annotation must be an object.",
                annotation_index=index,
            )
    pipeline: tuple[AnnotationCheck, ...] = (
        partial(check_label, labels=labels, deprecated=deprecated),
        partial(check_bbox, record=record),
        partial(check_confidence, threshold=threshold),
    )
    for check in pipeline:
        for index, annotation in valid:
            yield from check(annotation, index)


def validate_record(
    index: int, raw: JsonValue, path: Path | None, mode: Mode, taxonomy: Taxonomy, threshold: float
) -> RecordResult:
    reasons: list[Reason] = []
    record_id: str | None = None
    if isinstance(raw, dict):
        identifier = raw.get("record_id")
        if isinstance(identifier, str) and identifier.strip():
            record_id = identifier
        else:
            reasons.append(
                Reason(code="RECORD_ID_INVALID", message="record_id must be a nonblank string.")
            )
        reasons.extend(check_metadata(raw, path, mode))
        labels = {entry.label for entry in taxonomy.labels}
        reasons.extend(check_annotations(raw, labels, taxonomy.deprecated_aliases, threshold))
    else:
        reasons.append(Reason(code="RECORD_INVALID", message="Record must be an object."))

    if not reasons:
        reasons.append(
            Reason(code="CHECKS_PASSED", message="All applicable checks passed.", level="PASS")
        )
    status = max((reason.level for reason in reasons), key=STATUS_ORDER.index)
    return RecordResult(record_index=index, record_id=record_id, status=status, reasons=reasons)


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
    batch = Batch.model_validate_json(batch_file.read_bytes())
    taxonomy = Taxonomy.model_validate_json(taxonomy_file.read_bytes())
    if batch.record_count != len(batch.records):
        raise ValueError("record_count does not match the records array length.")
    if batch.taxonomy_version != taxonomy.taxonomy_version:
        raise ValueError("Batch and taxonomy versions do not match.")

    root = batch_file.parent.resolve()
    paths = [
        image_path(record.get("image_file"), root) if isinstance(record, dict) else None
        for record in batch.records
    ]
    actual_mode: Mode
    if options.mode == "auto":
        files_available = any(path is not None and path.is_file() for path in paths)
        actual_mode = "files" if files_available else "metadata_only"
    else:
        actual_mode = options.mode
    records = [
        validate_record(index, record, path, actual_mode, taxonomy, options.confidence_threshold)
        for index, (record, path) in enumerate(zip(batch.records, paths, strict=True))
    ]
    return BatchResult(
        batch_id=batch.batch_id,
        taxonomy_version=batch.taxonomy_version,
        mode=actual_mode,
        confidence_threshold=options.confidence_threshold,
        summary=summarize(records),
        records=records,
    )
