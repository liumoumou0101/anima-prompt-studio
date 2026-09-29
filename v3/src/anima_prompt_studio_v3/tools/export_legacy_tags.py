"""Read-only extraction of legacy personal tags through a local Docker psql."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


EXPORT_SQL = """BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT json_build_object(
    'categories', (SELECT coalesce(json_agg(row_to_json(c) ORDER BY c.id), '[]'::json)
                   FROM public.sys_categories AS c),
    'tags', (SELECT coalesce(json_agg(row_to_json(t) ORDER BY t.id), '[]'::json)
             FROM public.sys_tags AS t)
)::text;
COMMIT;"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export legacy categories and tags as UTF-8 JSON")
    parser.add_argument("--container", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.output.is_absolute():
        parser.error("--output must be an absolute path")
    if not args.container or not args.database or args.container.startswith("-") or args.database.startswith("-"):
        parser.error("container and database must be nonempty names")
    command = ["docker", "exec", "-i", args.container, "psql", "-X", "-v", "ON_ERROR_STOP=1",
               "-qAt", "-U", "postgres", "-d", args.database, "-c", EXPORT_SQL]
    result = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    lines = [line for line in result.stdout.splitlines() if line.lstrip().startswith("{")]
    if len(lines) != 1:
        raise ValueError("Expected one JSON result from read-only legacy export")
    payload = json.loads(lines[0])
    if not isinstance(payload, dict) or not isinstance(payload.get("categories"), list) or not isinstance(payload.get("tags"), list):
        raise ValueError("Legacy database returned malformed categories or tags")
    document = {"format": "anima-legacy-tags", "version": 1,
                "source_key": f"postgres:{args.container}/{args.database}",
                "categories": payload["categories"], "tags": payload["tags"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
