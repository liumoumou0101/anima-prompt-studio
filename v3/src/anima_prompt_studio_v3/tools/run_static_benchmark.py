from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..core import StaticBenchmarkRunner, StaticBenchmarkSuite
from ..data import ReferenceDataStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ANIMA V3 static prompt hard gates.")
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--reference-db", type=Path, required=True)
    args = parser.parse_args(argv)
    suite = StaticBenchmarkSuite.load(args.suite.resolve())
    with ReferenceDataStore(args.reference_db.resolve()) as store:
        report = StaticBenchmarkRunner(store).run(suite)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
