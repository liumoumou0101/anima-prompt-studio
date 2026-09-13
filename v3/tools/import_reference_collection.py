"""Local-only import: --source anima-ref --database <state>/examples.db --receipt <path>."""
import argparse
import json
from pathlib import Path

from anima_prompt_studio_v3.storage.reference_examples import ExampleStore
from anima_prompt_studio_v3.storage.reference_import import import_collection


def main():
    parser = argparse.ArgumentParser(description="导入本地参考案例；不会调用模型、下载图片或覆盖个人笔记。")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.receipt.resolve().is_relative_to(args.source.resolve()):
        parser.error("回执必须保存在来源集合之外，保持原资料不变。")
    if args.database.resolve().is_relative_to(args.source.resolve()):
        parser.error("数据库必须保存在来源集合之外。")
    receipt = import_collection(ExampleStore(args.database), args.source, dry_run=args.dry_run)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"dry_run": args.dry_run, "counts": receipt["counts"], "receipt": str(args.receipt.resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
