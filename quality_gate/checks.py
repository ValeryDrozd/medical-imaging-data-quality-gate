import hashlib
import math
import re
from collections.abc import Callable, Iterator
from fractions import Fraction
from functools import partial
from io import BytesIO
from pathlib import Path
from stat import S_ISREG
from typing import TypeGuard

from PIL import Image
from pydantic import JsonValue

from quality_gate.models import Batch, Mode, Reason, Taxonomy

Fields = dict[str, JsonValue]
AnnotationCheck = Callable[[Fields, int], Iterator[Reason]]
SHA256 = re.compile(r"[0-9a-fA-F]{64}")
PNG_IEND = bytes.fromhex("00000000 49454e44 ae426082")


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


# Resolve references inside the batch directory and detect regular files in auto mode.
def image_path(reference: JsonValue, root: Path, *, probe: bool) -> tuple[Path | None, bool]:
    if not isinstance(reference, str) or not reference.strip() or Path(reference).is_absolute():
        return None, False
    try:
        path = (root / reference).resolve()
        if path == root or not path.is_relative_to(root):
            return None, False
        if probe:
            try:
                return (path, True) if S_ISREG(path.stat().st_mode) else (None, False)
            except FileNotFoundError:
                return path, False
    except (OSError, RuntimeError, ValueError):
        return None, False
    return path, False


# Accept exactly 64 hex digits and normalize the digest for comparison.
def sha256_value(value: JsonValue) -> str | None:
    return value.lower() if isinstance(value, str) and SHA256.fullmatch(value) else None


# Compare PNG bytes with declarations, then check size limits, decoding, and dimensions.
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

    # Compare bytes on disk with a usable declared size.
    size = record.get("file_size_bytes")
    if type(size) is int and size >= 0 and len(data) != size:
        yield Reason(code="FILE_SIZE_MISMATCH", message="Actual and declared file sizes differ.")
    # A single actual digest must agree with every usable hash declaration.
    digest = hashlib.sha256(data).hexdigest()
    if any(value is not None and value != digest for value in (expected, received)):
        yield Reason(
            code="FILE_SHA256_MISMATCH", message="Actual SHA-256 differs from declarations."
        )
    # Empty files cannot be decoded. Keep the reason even if the declared size was invalid.
    if not data:
        if type(size) is not int or size != 0:
            yield Reason(code="FILE_EMPTY", message="The referenced PNG is empty.")
        return

    # Verify the PNG and reject an oversized canvas before decoding pixels.
    try:
        with BytesIO(data) as stream, Image.open(stream, formats=("PNG",)) as image:
            if (
                Image.MAX_IMAGE_PIXELS is not None
                and math.prod(image.size) > Image.MAX_IMAGE_PIXELS
            ):
                raise Image.DecompressionBombError("PNG exceeds the decoder's pixel limit.")
            image.verify()
            # Pillow stops after reading the IEND header. Check the final CRC and EOF.
            if stream.tell() != len(data) - 4 or not data.endswith(PNG_IEND):
                raise SyntaxError("Invalid PNG image trailer.")
        with Image.open(BytesIO(data), formats=("PNG",)) as image:
            image.load()
            dimensions = image.size
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        yield Reason(
            code="IMAGE_FILE_TOO_LARGE", message="The PNG exceeds the decoder's pixel limit."
        )
        return
    except (OSError, SyntaxError, ValueError):
        yield Reason(
            code="IMAGE_FILE_CORRUPT", message="The referenced file is not a decodable PNG."
        )
        return
    # Compare each decoded dimension only when the corresponding declaration is valid.
    for field, actual in zip(("image_width", "image_height"), dimensions, strict=True):
        declared = record.get(field)
        if positive_int(declared) and declared != actual:
            yield Reason(
                code="IMAGE_DIMENSIONS_MISMATCH", message=f"Actual and declared {field} differ."
            )


# Validate declared image metadata before checking available file content.
def check_metadata(record: Fields, path: Path | None, mode: Mode) -> Iterator[Reason]:
    # Declared dimensions supply the bounds for annotation boxes.
    for field in ("image_width", "image_height"):
        if not positive_int(record.get(field)):
            yield Reason(
                code="IMAGE_DIMENSION_INVALID", message=f"{field} must be a positive integer."
            )

    # Distinguish a missing reference from an unusable path.
    reference = record.get("image_file")
    if reference is None or (isinstance(reference, str) and not reference.strip()):
        yield Reason(code="IMAGE_REFERENCE_MISSING", message="image_file is missing or blank.")
    elif path is None:
        yield Reason(
            code="IMAGE_REFERENCE_INVALID",
            message="image_file must be a usable relative path within the batch directory.",
        )

    # An empty file and an invalid size declaration have separate reason codes.
    size = record.get("file_size_bytes")
    if type(size) is int and size == 0:
        yield Reason(code="FILE_EMPTY", message="The declared file size is zero bytes.")
    elif (path is not None or size is not None) and not positive_int(size):
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


# Check box format, then validate the geometry and bounds of each usable axis.
def check_bbox(annotation: Fields, index: int, *, record: Fields) -> Iterator[Reason]:
    box = annotation.get("bbox")
    coordinates = (
        [Fraction(str(value)) if finite_number(value) else None for value in box]
        if isinstance(box, list) and len(box) == 4
        else []
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
    pipeline: tuple[AnnotationCheck, ...] = (
        partial(check_label, labels=labels, deprecated=deprecated),
        partial(check_bbox, record=record),
        partial(check_confidence, threshold=threshold),
    )
    for check in pipeline:
        for index, annotation in valid:
            yield from check(annotation, index)


# Check the record shape and ID, then collect all applicable metadata and annotation reasons.
def check_record(
    raw: JsonValue,
    path: Path | None,
    mode: Mode,
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
    reasons.extend(check_metadata(raw, path, mode))
    reasons.extend(check_annotations(raw, labels, deprecated, threshold))
    return record_id, reasons
