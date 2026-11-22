# Specification

## Inputs and run behavior

| Acceptance criterion | Expected behavior |
| --- | --- |
| Delivery envelope | Accept a batch JSON object with a nonempty batch ID, taxonomy version, declared record count and records array. The version must match the taxonomy and the count must match the array length. |
| Invalid run input | Invalid JSON, an unreadable manifest, an invalid envelope or taxonomy, a version/count mismatch or an invalid threshold aborts the run. The CLI reports the input error to stderr and exits 2. MCP reports a tool error. |
| Independent deliveries | Given the same input files, options and available PNGs, both entry points return the same report. A completed CLI run exits 0 for any mix of record decisions. |
| Per-call threshold | `--confidence-threshold` in the CLI and `confidence_threshold` in MCP accept a finite number from 0 to 1 inclusive. An omitted threshold uses 0.50, even after a previous MCP call with an override. With 0.38, the supplied batch has 37 PASS, 13 FAIL and zero NEEDS_REVIEW. |
| Record isolation | Emit one result per input element in input order. A non-object fails with `RECORD_INVALID`. A missing or invalid record ID fails with `RECORD_ID_INVALID` and the zero-based `record_index` still identifies the element. |
| Metadata-only scope | Every report uses `metadata_only`. Validation consumes the batch and taxonomy JSON. Image reference and integrity decisions use the declared metadata and are independent of the files on disk. |
| MCP call result | A `validate_batch` call returns either the same report as the CLI or an `error` object with a stable `code` and readable `message`. Both use MCP `isError: false`. A valid call still succeeds after a failed one on the same session. See [MCP errors](MCP.md#failed-calls) for the codes and protocol boundary. |

## Ordered checks

Evaluate metadata, then annotations by label, box and confidence. Checks emit a stable code and a readable explanation. Annotation reasons include a zero-based `annotation_index`. A failed prerequisite skips its dependent check. Independent checks continue.

| Check | Acceptance criteria and reason codes |
| --- | --- |
| Declared dimensions | Both dimensions must be positive integers. Emit `IMAGE_DIMENSION_INVALID` for each invalid dimension. |
| Image reference | A null or blank reference yields `IMAGE_REFERENCE_MISSING`. Check relative POSIX path syntax. An absolute path, a path that escapes or resolves lexically to the batch directory, an embedded NUL, and a component over 255 UTF-8 bytes each yield `IMAGE_REFERENCE_INVALID`. |
| Declared file size | Zero yields `FILE_EMPTY`. Other invalid values yield `FILE_SIZE_INVALID`. Skip an absent size when the reference is unusable. |
| Declared SHA-256 | Require valid 64-digit hex. Emit `SHA256_EXPECTED_INVALID` or `SHA256_RECEIVED_INVALID` for bad declarations. Skip an absent received digest when the reference is unusable. Compare two valid declarations case-insensitively and emit `SHA256_MISMATCH` when they differ. |
| Annotation structure | An empty array is valid. A missing or non-array container yields `ANNOTATIONS_INVALID`. A non-object entry yields `ANNOTATION_INVALID`. Continue across other entries. |
| Taxonomy | Accept case-sensitive labels in the supplied taxonomy. A deprecated alias such as `lesion` yields `LABEL_DEPRECATED` with the taxonomy’s explanation. An unknown, missing or invalid label yields `LABEL_UNKNOWN`. |
| Box format and bounds | Require exactly four finite numbers `[x, y, width, height]` in pixels from the top-left (`BBOX_FORMAT_INVALID`). With four positions, check each axis whose coordinates are finite independently. The origin must be nonnegative and extent positive (`BBOX_GEOMETRY_INVALID`). With valid geometry and a valid declared dimension, origin plus extent may equal the dimension. Exceeding it yields `BBOX_OUT_OF_BOUNDS`. |
| Confidence | A finite number from 0 to 1 inclusive is valid. Values below the configurable threshold (default 0.50) yield `CONFIDENCE_LOW`. Equality is accepted. Missing, nonnumeric or out-of-range values yield `CONFIDENCE_INVALID`. |

## Decision and report

- Assign each status once after collecting applicable reasons. Hard failures take precedence over low confidence, which takes precedence over a pass. A pass gets `CHECKS_PASSED`.
- Include the batch ID, taxonomy version, applied threshold and mode. Include the total record count, all three status counts, failure frequency by code and the IDs of final `NEEDS_REVIEW` records. Count each failure code at most once per record and sort by descending frequency, then alphabetically.
- For the supplied 50 records and default threshold, expect `metadata_only`, 36 PASS, 13 FAIL and 1 NEEDS_REVIEW. `IMG-0009` is the sole review ID. `IMG-0037` fails with `BBOX_FORMAT_INVALID` and `IMG-0043` fails with `LABEL_DEPRECATED`. The integration tests verify the result and CLI/MCP parity.

## Edge-case batches

The files in [task_description/edge_cases](task_description/edge_cases) are test variants of the supplied synthetic metadata. Run any fixture through Compose with `sh scripts/run-batch.sh --batch task_description/edge_cases/annotation-boundaries.json`, substituting the filename as needed. Tests assert record order, status, reason codes and review IDs, and verify that one MCP session can process valid batches after input errors.

| Fixture | Coverage | Expected result |
| --- | --- | --- |
| `empty.json` | A valid zero-record delivery | 0 PASS, 0 FAIL, 0 NEEDS_REVIEW |
| `annotation-boundaries.json` | Exact edges, fractional coordinates, empty annotations, out-of-range numbers, multiple reasons | 3 PASS, 3 FAIL, 1 NEEDS_REVIEW (`ANN-MIN`) |
| `record-shapes.json` | Invalid records, IDs and annotation types followed by a valid record | 1 PASS, 7 FAIL, 0 NEEDS_REVIEW |
| `file-metadata.json` | Missing, escaping, malformed and overlong paths, invalid dimensions and hashes, case-insensitive digests | 2 PASS, 8 FAIL, 0 NEEDS_REVIEW |
| `invalid-count.json` | Declared count differs from array length | CLI exit 2 and `INVALID_BATCH_INPUT` in the MCP result |
| `wrong-taxonomy.json` | Unsupported taxonomy version | CLI exit 2 and `INVALID_BATCH_INPUT` in the MCP result |
| `truncated.json` | Intentionally incomplete JSON | CLI exit 2 and `INVALID_BATCH_INPUT` in the MCP result |
