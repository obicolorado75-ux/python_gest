# -*- mode: python ; coding: utf-8 -*-
"""Spécification PyInstaller — Windows (§4.1)."""
import sys
from pathlib import Path

block_cipher = None
assets = []  # ajouter ici les icônes / modèles si nécessaire

a = Analysis(
    ["../../src/gestdepot/__main__.py"],
    pathex=["../../src"],
    binaries=[],
    datas=assets,
    hiddenimports=["gestdepot.app", "gestdepot.ui.main_window"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GestDepot",
          console=False, icon=None)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="GestDepot")
