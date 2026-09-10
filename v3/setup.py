"""Bundle the immutable example packs without duplicating their source files."""
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def run(self):
        super().run()
        root = Path(__file__).resolve().parent / "example-packs"
        if not (root / "cma-styles-20260910-v1" / "examples-pack.json").is_file():
            raise ValueError("Bundled example pack is missing from the build source")
        for source in sorted(root.glob("*/examples-pack.json")):
            manifest = json.loads(source.read_bytes())
            destination = Path(self.build_lib) / "anima_prompt_studio_v3" / "example_packs" / source.parent.name
            inventory = [("examples-pack.json", source.read_bytes())]
            for item in manifest["files"]:
                name = item["path"]
                if (PurePosixPath(name).is_absolute() or "\\" in name or ":" in name
                        or any(part in {"", ".", ".."} for part in name.split("/"))):
                    raise ValueError("Invalid example pack path")
                path = (source.parent / item["path"]).resolve()
                if not path.is_relative_to(source.parent.resolve()):
                    raise ValueError("Example pack path escapes source")
                content = path.read_bytes()
                if len(content) != item["size"] or sha256(content).hexdigest() != item["sha256"]:
                    raise ValueError(f"Example pack checksum mismatch: {item['path']}")
                inventory.append((item["path"], content))
            for name, content in inventory:
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)


setup(cmdclass={"build_py": BuildPy})
