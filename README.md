# Medical Imaging Data Quality Gate

Research scientists and data operations staff use this gate to screen batches of synthetic chest X-ray records from a vendor model. Deterministic checks give each record a decision and explain what triggered it. The batch summary gives scientists the IDs to review.

## Run the supplied batch

With Docker Compose v2 and a running Docker daemon, run this from the repository root.

```sh
sh scripts/run-batch.sh > results.json
```

The script builds and runs the Compose service and writes the JSON report to stdout. Set `DOCKER_CONTEXT=desktop-linux` if Docker Desktop uses that context on your machine. Each run defaults to a confidence threshold of 0.50. For example, `sh scripts/run-batch.sh --confidence-threshold 0.38 > results.json` applies 0.38 to that run.

## Actual result

| Batch | Mode | PASS | FAIL | NEEDS_REVIEW |
| --- | --- | ---: | ---: | ---: |
| BATCH-2026-11-02-A | `metadata_only` | 36 | 13 | 1 |

Review **IMG-0009**, whose confidence was 0.38. The most common failures were invalid confidence, missing image references, unknown labels, and mismatched declared SHA-256 hashes, each affecting two records. [Full report](examples/batch-result.json)

## Assumptions

- Each batch is independent and declares the version of the supplied taxonomy. Labels are exact and case-sensitive. The deprecated label `lesion` fails without mapping. Empty annotation arrays are valid.
- Valid scores below the applied confidence threshold go to human review. A hard failure takes precedence. Review handoff is the `review_ids` list in the report.
- The delivery contains image metadata and zero PNG files. In automatic mode, any available referenced PNG activates file checks across the batch. Use `--mode files` when every referenced PNG is expected. Boxes use declared dimensions, a top-left origin and pixel units.

## Developer and review entry points

For MCP setup and deployment, see the [MCP guide](MCP.md). For local checks, see [AGENTS.md](AGENTS.md). See also the [acceptance criteria and edge-case batches](SPEC.md) and [AI log](AI_LOG.md).

## Questions for the client

1. How should we calibrate the review threshold by label, model version, and available reviewer capacity?
2. Which file integrity checks and vendor manifest fields are mandatory for accepting a delivery?
3. Who owns the review queue, and how should the vendor receive and resubmit rejected records?
