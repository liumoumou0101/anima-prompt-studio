"""Install a locally supplied, verified official example pack."""
import argparse
from pathlib import Path

from ..storage.official_examples import OfficialPack


def main():
    parser = argparse.ArgumentParser(description="校验并安装官方参考图包；不会下载或安装 LoRA。")
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path, required=True, help="工作台数据库同级的 official-examples 目录")
    args = parser.parse_args()
    try:
        result = OfficialPack(args.destination).install(args.source)
    except (ValueError, OSError):
        parser.exit(1, "参考包校验/安装失败，原激活指针未被替换。\n")
    print(f"已启用 {result['id']}，{result['count']} 个官方参考。")


if __name__ == "__main__":
    main()
