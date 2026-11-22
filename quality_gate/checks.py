import math
import re
from collections.abc import Iterator
from fractions import Fraction
from pathlib import PurePosixPath
from typing import TypeGuard

from pydantic import JsonValue

from quality_gate.models import Batch, Reason, Taxonomy

Fields = dict[str, JsonValue]
SHA256 = re.compile(r"[0-9a-fA-F]{64}")


# Reject a manifest whose record count or taxonomy version contradicts the inputs.
def check_batch(batch: Batch, taxonomy: Taxonomy) -> None:
    if batch.record_count != len(batch.records):
        raise ValueError("record_count does not match the records array length.")
    if batch.taxonomy_version != taxonomy.taxonomy_version:
        raise ValueError("Batch and taxonomy versions do not match.")


# Accept positive integers and reject booleans and numeric strings.
def positive_int(value: JsonValue) -> TypeGuard[int]:
    return type(value) is int and value > 0


# Accept finite JSON numbers and reject booleans and numeric strings.
def finite_number(value: JsonValue) -> TypeGuard[int | float]:
    return type(value) is int or (type(value) is float and math.isfinite(value))


# Check the declared relative path without looking for an image on disk.
def valid_image_reference(reference: JsonValue) -> bool:
    if not isinstance(reference, str) or not reference.strip() or "\x00" in reference:
        return False
    path = PurePosixPath(reference)
    if path.is_absolute():
        return False
    depth = 0
    for part in path.parts:
        depth += -1 if part == ".." else 1
        if depth < 0 or len(part.encode("utf-8")) > 255:
            return False
    return depth > 0


# Accept exactly 64 hex digits and normalize the digest for comparison.
def sha256_value(value: JsonValue) -> str | None:
    return value.lower() if isinstance(value, str) and SHA256.fullmatch(value) else None


# Validate the image metadata declared in each record.
def check_metadata(record: Fields) -> Iterator[Reason]:
    # Declared dimensions supply the bounds for annotation boxes.
    for field in ("image_width", "image_height"):
        if not positive_int(record.get(field)):
            yield Reason(
                code="IMAGE_DIMENSION_INVALID", message=f"{field} must be a positive integer."
            )

    # Distinguish a missing reference from an unusable path.
    reference = record.get("image_file")
    usable_reference = valid_image_reference(reference)
    if reference is None or (isinstance(reference, str) and not reference.strip()):
        yield Reason(code="IMAGE_REFERENCE_MISSING", message="image_file is missing or blank.")
    elif not usable_reference:
        yield Reason(
            code="IMAGE_REFERENCE_INVALID",
            message="image_file must be a usable relative path within the batch directory.",
        )

    # An empty file and an invalid size declaration have separate reason codes.
    size = record.get("file_size_bytes")
    if type(size) is int and size == 0:
        yield Reason(code="FILE_EMPTY", message="The declared file size is zero bytes.")
    elif (usable_reference or size is not None) and not positive_int(size):
        yield Reason(
            code="FILE_SIZE_INVALID", message="file_size_bytes must be a positive integer."
        )

    # Compare expected and received hashes only when both are valid.
    expected = sha256_value(record.get("sha256_expected"))
    received_raw = record.get("sha256_received")
    received = sha256_value(received_raw)
    if expected is None:
        yield Reason(
            code="SHA256_EXPECTED_INVALID", message="Expected SHA-256 must be 64 hex digits."
        )
    if received is None and (usable_reference or received_raw is not None):
        yield Reason(
            code="SHA256_RECEIVED_INVALID", message="Received SHA-256 must be 64 hex digits."
        )
    if expected is not None and received is not None and expected != received:
        yield Reason(
            code="SHA256_MISMATCH", message="Declared expected and received SHA-256 differ."
        )


# Accept exact taxonomy labels and reject deprecated aliases without mapping them.
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


# Preserve exact decimal boundaries while keeping integer coordinates as integers.
def box_coordinate(value: JsonValue) -> int | Fraction | None:
    if not finite_number(value):
        return None
    return value if isinstance(value, int) else Fraction(str(value))


# Check box format, then validate the geometry and bounds of each usable axis.
def check_bbox(annotation: Fields, index: int, *, record: Fields) -> Iterator[Reason]:
    box = annotation.get("bbox")
    coordinates = (
        [box_coordinate(value) for value in box] if isinstance(box, list) and len(box) == 4 else []
    )
    if not coordinates or None in coordinates:
        yield Reason(
            code="BBOX_FORMAT_INVALID",
            message="bbox must contain four finite numbers [x, y, width, height].",
            annotation_index=index,
        )
    if not coordinates:
        return
    x, y, width, height = coordinates
    for axis, origin, extent in (("width", x, width), ("height", y, height)):
        if origin is None or extent is None:
            continue
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


# Reject invalid scores and send valid scores below the call threshold to review.
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


# Check the annotation structure before running label, box, and confidence rules in order.
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
    for index, annotation in valid:
        yield from check_label(annotation, index, labels=labels, deprecated=deprecated)
    for index, annotation in valid:
        yield from check_bbox(annotation, index, record=record)
    for index, annotation in valid:
        yield from check_confidence(annotation, index, threshold=threshold)


# Check the record shape and ID, then collect all applicable metadata and annotation reasons.
def check_record(
    raw: JsonValue,
    *,
    labels: set[str],
    deprecated: dict[str, str],
    threshold: float,
) -> tuple[str | None, list[Reason]]:
    if not isinstance(raw, dict):
        return None, [Reason(code="RECORD_INVALID", message="Record must be an object.")]

    identifier = raw.get("record_id")
    record_id = identifier if isinstance(identifier, str) and identifier.strip() else None
    reasons: list[Reason] = []
    if record_id is None:
        reasons.append(
            Reason(code="RECORD_ID_INVALID", message="record_id must be a nonblank string.")
        )
    reasons.extend(check_metadata(raw))
    reasons.extend(check_annotations(raw, labels, deprecated, threshold))
    return record_id, reasons
