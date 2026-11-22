# Specification

## Inputs and run behavior

| Acceptance criterion | Expected behavior |
| --- | --- |
| Delivery envelope | Accept a batch JSON object with a nonempty batch ID, taxonomy version, declared record count and records array. The version must match the taxonomy and the count must match the array length. |
| Invalid run input | Invalid JSON, an unreadable manifest, an invalid envelope or taxonomy, a version/count mismatch or an invalid threshold aborts the run. The CLI reports the input error to stderr and exits 2. MCP reports a tool error. |
| Independent deliveries | Given the same input files, options and available PNGs, both entry points return the same report. A completed CLI run exits 0 for any mix of record decisions. |
| Record isolation | Emit one result per input element in input order. A non-object fails with `RECORD_INVALID`. A missing or invalid record ID fails with `RECORD_ID_INVALID` and the zero-based `record_index` still identifies the element. |
| Image mode | In `auto`, resolve references relative to the batch directory. If any referenced regular file exists, use `files`. Otherwise use `metadata_only`. Either mode can be selected explicitly. The result reports the mode used. |

## Ordered checks

Evaluate metadata, then annotations by label, box and confidence. Checks emit a stable code and a readable explanation. Annotation reasons include a zero-based `annotation_index`. A failed prerequisite skips its dependent check. Independent checks continue.

| Check | Acceptance criteria and reason codes |
| --- | --- |
| Declared dimensions | Both dimensions must be positive integers. Emit `IMAGE_DIMENSION_INVALID` for each invalid dimension. |
| Image reference | A null or blank reference yields `IMAGE_REFERENCE_MISSING`. An absolute path, outside path or unresolvable path yields `IMAGE_REFERENCE_INVALID`. |
| Declared file size | Zero yields `FILE_EMPTY`. Other invalid values yield `FILE_SIZE_INVALID`. Skip an absent size when the reference is unusable. |
| Declared SHA-256 | Require valid 64-digit hex. Emit `SHA256_EXPECTED_INVALID` or `SHA256_RECEIVED_INVALID` for bad declarations. Skip an absent received digest when the reference is unusable. Compare two valid declarations case-insensitively and emit `SHA256_MISMATCH` when they differ. |
| PNG integrity in `files` mode | Missing or unreadable files yield `IMAGE_FILE_MISSING` or `IMAGE_FILE_UNREADABLE`. For files read, check actual byte count and digest against usable declarations (`FILE_SIZE_MISMATCH`, `FILE_SHA256_MISMATCH`). Empty bytes yield `FILE_EMPTY`. A nonempty file must verify and decode as PNG (`IMAGE_FILE_CORRUPT)). Compare decoded dimensions with any valid declared dimensions (`IMAGE_DIMENSIONS_MISMATCH`). |
| Annotation structure | An empty array is valid. A missing or non-array container yields `ANNOTATIONS_INVALID`. A non-object entry yields `ANNOTATION_INVALID`. Continue across other entries. |
| Taxonomy | Accept case-sensitive labels in the supplied taxonomy. A deprecated alias such as `lesion` yields `LABEL_DEPRECATED` with the taxonomy’s explanation. An unknown, missing or invalid label yields `LABEL_UNKNOWN`. |
| Box format and bounds | Require exactly four finite numbers `[x, y, width, height]` in pixels from the top-left (`BBOX_FORMAT_INVALID`). Each origin must be nonnegative and each extent positive (`BBOX_GEOMETRY_INVALID`). On each axis with valid geometry and a valid declared dimension, origin plus extent may equal the dimension. Exceeding it yields `BBOX_OUT_OF_BOUNDS`. |
| Confidence | A finite number from 0 to 1 inclusive is valid. Values below the configurable threshold (default 0.50) yield `CONFIDENCE_LOW`. Equality is accepted. Missing, nonnumeric or out-of-range values yield `CONFIDENCE_INVALID`. |

## Decision and report

- Assign each status once after collecting applicable reasons. Hard failures take precedence over low confidence, which takes precedence over a pass. A pass gets `CHECKS_PASSED`.
- Include the batch ID, taxonomy version, applied threshold and mode. Include the total record count, all three status counts, failure frequency by code and the IDs of final `NEEDS_REVIEW` records. Count each failure code at most once per record and sort by descending frequency, then alphabetically.
- For the supplied 50 records and default threshold, expect `metadata_only`, 36 PASS, 13 FAIL and 1 NEEDS_REVIEW. `IMG-0009` is the sole review ID. `IMG-0037` fails with `BBOX_FORMAT_INVALID` and `IMG-0043` fails with `LABEL_DEPRECATED`. The integration tests verify the result and CLI/MCP parity.
- The supplied fixtures are synthetic metadata. The PNG integration test writes a temporary blank image as a test double.
