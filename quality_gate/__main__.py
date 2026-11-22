import argparse
import sys
from pathlib import Path

from quality_gate.core import validate_batch
from quality_gate.models import DEFAULT_BATCH, DEFAULT_TAXONOMY, DEFAULT_THRESHOLD


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one synthetic medical imaging batch.")
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--confidence-threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--mode", choices=("auto", "metadata_only", "files"), default="auto")
    args = parser.parse_args()
    try:
        result = validate_batch(
            args.batch,
            args.taxonomy,
            confidence_threshold=args.confidence_threshold,
            mode=args.mode,
        )
    except (OSError, ValueError) as error:
        print(f"Batch input error: {error}", file=sys.stderr)
        return 2
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
