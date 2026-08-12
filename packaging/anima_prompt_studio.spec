# PyInstaller build definition for the Windows portable and installer packages.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
PACKAGE = SRC / "anima_prompt_studio"

datas = [
    (str(PACKAGE / "configs"), "anima_prompt_studio/configs"),
    (str(PACKAGE / "web_gallery" / "dist"), "anima_prompt_studio/web_gallery/dist"),
]

# These modules are loaded by optional runtime paths and should remain available
# in the all-in-one Windows build even when the base build does not exercise them.
hiddenimports = collect_submodules("anima_prompt_studio.services.remote")


a = Analysis(
    [str(PACKAGE / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "transformers", "sentencepiece", "sacremoses"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AnimaPromptStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    a.zipfiles,
    name="AnimaPromptStudio",
)
