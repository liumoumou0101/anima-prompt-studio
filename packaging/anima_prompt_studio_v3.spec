# PyInstaller onedir definition for the ANIMA V3 browser-based Windows desktop package.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


ROOT = Path(SPECPATH).parent
V2_SRC = ROOT / "src"
V3_ROOT = ROOT / "v3"
V3_SRC = V3_ROOT / "src"
V2_PACKAGE = V2_SRC / "anima_prompt_studio"
V3_PACKAGE = V3_SRC / "anima_prompt_studio_v3"
PACK_SOURCE = Path(os.environ["ANIMA_V3_PACK_SOURCE"]).resolve()

sys.path.insert(0, str(V3_SRC))
sys.path.insert(0, str(V2_SRC))

if not (V3_ROOT / "web" / "dist" / "index.html").is_file():
    raise SystemExit("V3 web/dist is missing; build the web app before running PyInstaller.")
if not (PACK_SOURCE / "data-pack.json").is_file() or not (PACK_SOURCE / "reference.db").is_file():
    raise SystemExit(f"V3 data pack is incomplete: {PACK_SOURCE}")

datas = [
    (str(V3_PACKAGE / "configs"), "anima_prompt_studio_v3/configs"),
    (str(V3_ROOT / "web" / "dist"), "anima_prompt_studio_v3/web/dist"),
    (str(V2_PACKAGE / "configs"), "anima_prompt_studio/configs"),
    (str(PACK_SOURCE), f"data-packs/{PACK_SOURCE.name}"),
]

hiddenimports = sorted(
    set(
        collect_submodules("anima_prompt_studio.services.remote")
        + collect_submodules("anima_prompt_studio_v3.adapters.v2")
    )
)

a = Analysis(
    [str(ROOT / "packaging" / "run_v3.py")],
    pathex=[str(V3_SRC), str(V2_SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "transformers", "sentencepiece", "sacremoses", "pandas", "pyarrow"],
    noarchive=False,
)
# The Codex workspace exposes Poppler's private ICU build through PATH. QtCore
# intentionally uses the Windows ICU DLL, so bundling Poppler's same-named
# icuuc.dll shadows the system library and fails with WinError 127.
a.binaries = [
    entry
    for entry in a.binaries
    if Path(entry[0]).name.lower() not in {"icuuc.dll", "icudt78.dll"}
]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AnimaPromptStudioV3",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    a.zipfiles,
    name="AnimaPromptStudioV3",
)
