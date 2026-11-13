# -*- mode: python ; coding: utf-8 -*-

import sys

_exe_icon = "img/icons/dns_icon_glass.ico" if sys.platform == "win32" else None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("dns_profiles", "dns_profiles"),
        ("img/icons/dns_icon_glass.png", "img/icons"),
        ("img/icons/dns_icon_glass_8x.png", "img/icons"),
        ("img/icons/dns_icon_glass.ico", "img/icons"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FastDNS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_exe_icon,
)
