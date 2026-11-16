# -*- mode: python ; coding: utf-8 -*-
"""Spécification PyInstaller — macOS .app (§4.1)."""
block_cipher = None

a = Analysis(
    ["../../src/gestdepot/__main__.py"],
    pathex=["../../src"],
    binaries=[],
    datas=[],
    hiddenimports=["gestdepot.app", "gestdepot.ui.main_window"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GestDepot",
          console=False)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="GestDepot")
app = BUNDLE(coll, name="GestDepot.app",
             bundle_identifier="ci.gestdepot.app",
             info_plist={"CFBundleShortVersionString": "0.1.0",
                         "NSHighResolutionCapable": True})
