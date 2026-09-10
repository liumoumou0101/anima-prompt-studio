"""Install a locally supplied, verified official example pack."""
import argparse
from pathlib import Path

from ..storage.official_examples import OfficialPack
from ..storage.bundled_examples import bundled_example_source


def main():
    parser = argparse.ArgumentParser(description="校验并安装官方参考图包；不会下载或安装 LoRA。")
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--bundled", action="store_true", help="安装程序自带的官方参考样例，无需下载")
    parser.add_argument("--destination", type=Path, required=True, help="工作台数据库同级的 official-examples 目录")
    args = parser.parse_args()
    if (args.source is not None) == args.bundled:
        parser.error("请选择 source 路径或 --bundled，不能同时使用。")
    try:
        result = OfficialPack(args.destination).install(bundled_example_source() if args.bundled else args.source)
    except (ValueError, OSError):
        parser.exit(1, "参考包校验/安装失败，原激活指针未被替换。\n")
    print(f"已启用 {result['id']}，{result['count']} 个官方参考。")


if __name__ == "__main__":
    main()
