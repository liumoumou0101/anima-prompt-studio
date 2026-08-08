from __future__ import annotations

import argparse
import concurrent.futures
import csv
import io
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from anima_prompt_studio.services.resource_manager import MODEL_REPOSITORIES, ResourceManager


ANIMA_CUTOFF = "2025-09-30T23:59:59"
API_ROOT = "https://danbooru.donmai.us"
CATEGORY_PAGES = {0: 30, 1: 10, 3: 5, 4: 12, 5: 3}
MODEL_FILES = ["README.md", "config.json", "generation_config.json", "metadata.json", "pytorch_model.bin", "source.spm", "target.spm", "tokenizer_config.json", "vocab.json"]
ALIAS_CSV_URL = "https://raw.githubusercontent.com/DominikDoom/a1111-sd-webui-tagcomplete/main/tags/danbooru.csv"


def download_models(resources: ResourceManager) -> dict:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("请先安装 requirements-translation.txt。") from exc
    resources.model_dir.mkdir(parents=True, exist_ok=True)
    installed = {}
    for direction, repository in MODEL_REPOSITORIES.items():
        target = resources.model_path(direction)
        print(f"下载 {repository} → {target}", flush=True)
        snapshot_download(repo_id=repository, local_dir=target, allow_patterns=MODEL_FILES)
        installed[direction] = {"repository": repository, "path": str(target), "downloaded_at": datetime.now(timezone.utc).isoformat()}
    return installed


def _fetch_page(category: int, page: int) -> list[dict]:
    import requests
    response = requests.get(
        f"{API_ROOT}/tags.json",
        params={"limit": 1000, "page": page, "search[category]": category, "search[hide_empty]": "yes", "search[order]": "count"},
        headers={"User-Agent": "AnimaPromptStudio/1.0 (local offline prompt compiler)"}, timeout=60,
    )
    response.raise_for_status()
    return response.json()


def download_tags(resources: ResourceManager) -> dict:
    target = resources.tag_db_path
    target.parent.mkdir(parents=True, exist_ok=True)
    jobs = [(category, page) for category, pages in CATEGORY_PAGES.items() for page in range(1, pages + 1)]
    all_tags: dict[str, dict] = {}
    print(f"从 Danbooru 官方 API 获取 {len(jobs)} 页标签…", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch_page, *job): job for job in jobs}
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            category, page = futures[future]
            for tag in future.result():
                created = tag.get("created_at") or ""
                if created[:19] <= ANIMA_CUTOFF and not tag.get("is_deprecated", False):
                    all_tags[tag["name"]] = tag
            print(f"  {index}/{len(jobs)} category={category} page={page}", flush=True)

    temporary = target.with_suffix(".building")
    if temporary.exists(): temporary.unlink()
    import requests
    alias_response = requests.get(ALIAS_CSV_URL, headers={"User-Agent": "AnimaPromptStudio/1.0"}, timeout=60)
    alias_response.raise_for_status()
    aliases: dict[str, str] = {}
    for row in csv.reader(io.StringIO(alias_response.text)):
        if len(row) < 4 or row[0] not in all_tags:
            continue
        for alias in row[3].split(","):
            alias = alias.strip()
            if alias and alias not in all_tags:
                aliases.setdefault(alias, row[0])

    connection = sqlite3.connect(temporary)
    try:
        connection.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE tags(name TEXT PRIMARY KEY, output_name TEXT NOT NULL, category INTEGER NOT NULL,
                post_count INTEGER NOT NULL, is_deprecated INTEGER NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE aliases(antecedent TEXT PRIMARY KEY, consequent TEXT NOT NULL);
            CREATE TABLE implications(antecedent TEXT NOT NULL, consequent TEXT NOT NULL, PRIMARY KEY(antecedent, consequent));
            CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE VIRTUAL TABLE tag_search USING fts5(term, canonical UNINDEXED, tokenize='unicode61');
        """)
        rows = [(x["name"], x["name"].replace("_", " ").lower(), x["category"], x["post_count"], int(x.get("is_deprecated", False)), x.get("created_at", "")) for x in all_tags.values()]
        connection.executemany("INSERT INTO tags VALUES(?,?,?,?,?,?)", rows)
        connection.executemany("INSERT INTO tag_search(term,canonical) VALUES(?,?)", [(row[1], row[0]) for row in rows])
        connection.executemany("INSERT INTO aliases(antecedent,consequent) VALUES(?,?)", aliases.items())
        connection.executemany("INSERT INTO tag_search(term,canonical) VALUES(?,?)", [(alias.replace("_", " "), canonical) for alias, canonical in aliases.items()])
        metadata = {
            "schema_version": "1", "source": f"{API_ROOT}/tags.json", "alias_source": ALIAS_CSV_URL,
            "anima_training_cutoff": ANIMA_CUTOFF, "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "tag_count": str(len(rows)), "alias_count": str(len(aliases)),
        }
        connection.executemany("INSERT INTO metadata(key,value) VALUES(?,?)", metadata.items())
        connection.commit()
    finally:
        connection.close()
    if target.exists(): target.replace(target.with_suffix(".bak"))
    temporary.replace(target)
    print(f"标签库完成：{len(all_tags):,} 标签、{len(aliases):,} 别名 → {target}", flush=True)
    return {"path": str(target), "count": len(all_tags), "aliases": len(aliases), "source": f"{API_ROOT}/tags.json", "alias_source": ALIAS_CSV_URL, "cutoff": ANIMA_CUTOFF}


def write_manifest(resources: ResourceManager, additions: dict) -> None:
    resources.root.mkdir(parents=True, exist_ok=True)
    manifest = resources.manifest(); manifest.update(additions)
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    (resources.root / "resource_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="下载 ANIMA Prompt Studio 的离线资源")
    parser.add_argument("--models", action="store_true", help="下载双向 Marian 翻译模型")
    parser.add_argument("--tags", action="store_true", help="从 Danbooru 官方 API 构建标签库")
    parser.add_argument("--root", type=Path, help="覆盖资源目录")
    args = parser.parse_args(argv)
    if not args.models and not args.tags: args.models = args.tags = True
    resources = ResourceManager(args.root)
    additions = {}
    try:
        if args.models: additions["models"] = download_models(resources)
        if args.tags: additions["tags"] = download_tags(resources)
        write_manifest(resources, additions)
        return 0
    except Exception as exc:
        print(f"资源安装失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
