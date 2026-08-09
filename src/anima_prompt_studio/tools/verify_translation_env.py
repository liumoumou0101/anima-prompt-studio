from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import json

from anima_prompt_studio.services.resource_manager import MODEL_REPOSITORIES, ResourceManager


RUNTIME_PACKAGES = {
    "torch": "torch",
    "transformers": "transformers",
    "sentencepiece": "sentencepiece",
    "sacremoses": "sacremoses",
}


def inspect_environment(resources: ResourceManager | None = None) -> dict:
    resources = resources or ResourceManager()
    packages = {}
    for module_name, distribution_name in RUNTIME_PACKAGES.items():
        available = importlib.util.find_spec(module_name) is not None
        try:
            version = importlib.metadata.version(distribution_name) if available else None
        except importlib.metadata.PackageNotFoundError:
            version = None
        packages[module_name] = {"available": available, "version": version}

    torch_status = {"backend": "unavailable", "cuda_build": None, "cuda_available": False}
    if packages["torch"]["available"]:
        torch = importlib.import_module("torch")
        cuda_build = getattr(getattr(torch, "version", None), "cuda", None)
        cuda_available = bool(getattr(getattr(torch, "cuda", None), "is_available", lambda: False)())
        torch_status = {
            "backend": "CUDA" if cuda_build else "CPU",
            "cuda_build": cuda_build,
            "cuda_available": cuda_available,
        }

    models = {}
    for direction, repository in MODEL_REPOSITORIES.items():
        path = resources.model_path(direction)
        weight = path / "pytorch_model.bin"
        models[direction] = {
            "repository": repository,
            "path": str(path),
            "available": (path / "config.json").is_file() and weight.is_file() and weight.stat().st_size > 100_000_000,
            "size_mb": round(weight.stat().st_size / 1024 / 1024, 1) if weight.is_file() else 0.0,
        }

    return {
        "runtime_ready": all(item["available"] for item in packages.values()),
        "packages": packages,
        "torch": torch_status,
        "models_ready": all(item["available"] for item in models.values()),
        "models": models,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 ANIMA 本地 Marian 翻译运行环境")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--require-models", action="store_true", help="模型缺失时返回失败")
    args = parser.parse_args(argv)
    status = inspect_environment()

    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        print("ANIMA 本地翻译环境检查")
        for name, item in status["packages"].items():
            print(f"  {name}: {item['version'] or '未安装'}")
        print(f"  Torch backend: {status['torch']['backend']}")
        print(f"  CUDA build: {status['torch']['cuda_build'] or '无'}")
        for direction, item in status["models"].items():
            state = f"已安装，{item['size_mb']} MB" if item["available"] else "未安装"
            print(f"  {direction} model: {state}")

    if not status["runtime_ready"]:
        return 1
    if args.require_models and not status["models_ready"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
