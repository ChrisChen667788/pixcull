# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PixCull.app.

Build:
    cd pixcull
    .venv/bin/pyinstaller app/pixcull.spec --noconfirm

Output:
    dist/PixCull.app           the bundle (rename / move to /Applications)
    dist/PixCull/              onefolder dist if you prefer that layout

This spec uses ``--onedir`` mode (Contents/Resources holds the
package). One-file mode would balloon startup to 30+ seconds because
PyInstaller has to extract a 2 GB archive on every launch.

Bundle assumptions:
* Apple silicon arm64. Cross-compile to x86_64 by passing
  ``--target-arch x86_64`` at the CLI; or use a universal2 build via
  ``--target-arch universal2`` (requires universal Python).
* Models are NOT bundled — they download to ~/Library/Application
  Support/PixCull/model_cache on first run. Bundling them would push
  the .app to ~8 GB. See app/launcher.py:run_first_setup.
"""

from pathlib import Path
import os
import sys

block_cipher = None

# Resolve project root from the spec file's location. PyInstaller's
# SPEC_PATH is the directory containing this file.
# SPECPATH is set by PyInstaller to the dir containing this spec file.
# Our spec lives at pixcull/app/pixcull.spec, so SPECPATH == pixcull/app
# and SPECPATH/.. == project root (pixcull/).
SPEC = Path(SPECPATH).resolve()  # type: ignore[name-defined]
PROJECT = SPEC.parent              # pixcull/
PACKAGE = PROJECT / "pixcull"
SCRIPTS = PROJECT / "scripts"
MODELS = PROJECT / "models"

# Data files to ship inside the bundle. Each tuple is (source, dest_dir).
datas = [
    # Web demo source (launcher subprocess imports these)
    (str(SCRIPTS), "scripts"),
    # Pixcull package — not in site-packages, added explicitly so
    # PyInstaller can pick up scene_templates.yaml etc.
    (str(PACKAGE), "pixcull"),
    # Pre-trained V2.1 axis rescorers — small (~1 MB total), worth
    # bundling so day-1 users get learned scoring out of the box.
]
if MODELS.exists():
    datas.append((str(MODELS), "models"))

# Hidden imports for modules PyInstaller's static analysis misses.
# These are typically lazy-imports, plugin-style imports, or things
# referenced via getattr / importlib.
hiddenimports = [
    # Our own lazy-imported modules
    "pixcull.scoring.rescorer",
    "pixcull.scoring.axis_rescorer",
    "pixcull.scoring.vlm_judge",
    "pixcull.scoring.meta_judge",
    "pixcull.scoring.rubric",
    "pixcull.scoring.rubric_decompose",
    "pixcull.detectors.face",          # lazy-imported on demand
    # Heavy 3rd-party packages with dynamic imports
    "transformers.models.clip.modeling_clip",
    "transformers.models.dinov2.modeling_dinov2",
    "rembg.bg",
    "pyiqa.archs",
    "pyiqa.metrics",
    # mlx-vlm fans out by model id
    "mlx_vlm.models.qwen3_vl",
    # OpenAI client used by meta-judge
    "openai",
    # macOS menu bar UI
    "rumps",
    "objc",
    "Foundation",
    "AppKit",
    # cgi used by serve_demo (deprecated but bundled in 3.12 stdlib)
    "cgi",
    "email.parser",
]

# Collect all submodules + data for these heavyweight packages — their
# import graphs are dynamic and PyInstaller's analysis misses pieces.
from PyInstaller.utils.hooks import collect_all

collect_packages = [
    "torch",
    "torchvision",
    "transformers",
    "huggingface_hub",
    "tokenizers",
    "safetensors",
    "rembg",
    "onnxruntime",
    "pyiqa",
    "mlx",
    "mlx_lm",
    "mlx_vlm",
    "imagededup",
    "pixcull",
    "pandas",
    "sklearn",
    "rumps",
    "openai",
]
for pkg in collect_packages:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        hiddenimports += h
    except Exception as e:
        print(f"warn: collect_all({pkg!r}) skipped: {e}")

a = Analysis(
    ["launcher.py"],
    pathex=[str(PROJECT), str(SPEC)],
    binaries=[],
    datas=datas,
    hiddenimports=list(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Exclude obvious bloat we don't need
    excludes=[
        "matplotlib.tests",
        "scipy.tests",
        "tensorflow",         # we don't use TF
        "tests",
        "PyQt5", "PyQt6", "PySide2", "PySide6",  # no Qt UI
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PixCull",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # UPX often breaks signed dylibs on macOS
    console=False,                  # no Terminal window when launched
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,               # take system default (arm64 on M-series)
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PixCull",
)

# macOS bundle wrapper. Without this PyInstaller produces a folder; the
# BUNDLE step wraps it as a real .app.
app = BUNDLE(
    coll,
    name="PixCull.app",
    icon=str(SPEC / "PixCull.icns") if (SPEC / "PixCull.icns").exists() else None,
    bundle_identifier="dev.pixcull.app",
    info_plist={
        "CFBundleName": "PixCull",
        "CFBundleDisplayName": "PixCull",
        "CFBundleVersion": "4.0.0",
        "CFBundleShortVersionString": "4.0",
        "CFBundleIdentifier": "dev.pixcull.app",
        # Apple silicon only by default — flip if targeting Intel
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        # Camera-related photo files — request implicit Photos access
        # if the user picks an iCloud Photos album folder. We never
        # actually use the Photos API; this just keeps Finder /
        # Sandbox from blocking reads on Photos library symlinks.
        "NSPhotoLibraryUsageDescription":
            "PixCull reads photos from folders you point it at. "
            "Nothing is uploaded — analysis runs locally.",
        "NSDocumentsFolderUsageDescription":
            "PixCull reads photos from folders you select.",
        "NSDownloadsFolderUsageDescription":
            "PixCull reads photos from folders you select.",
        "LSApplicationCategoryType": "public.app-category.photography",
    },
)
