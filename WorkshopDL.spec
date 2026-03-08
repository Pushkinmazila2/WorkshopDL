# -*- mode: python ; coding: utf-8 -*-
# WorkshopDL.spec — файл сборки PyInstaller
# Использование: pyinstaller WorkshopDL.spec

import sys
import os

IS_WIN   = sys.platform == "win32"
IS_MAC   = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# Файлы локализации которые нужно включить в сборку
datas = [
    ("lang_en.json", "."),
    ("lang_ru.json", "."),
]

# Если есть папка lang/ — включаем все JSON из неё
if os.path.isdir("lang"):
    datas.append(("lang/*.json", "lang"))

a = Analysis(
    ["workshopdl.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "PyQt5",
        "PyQt5.QtWidgets",
        "PyQt5.QtCore",
        "PyQt5.QtGui",
        "requests",
        "requests.adapters",
        "requests.auth",
        "requests.cookies",
        "requests.exceptions",
        "requests.models",
        "requests.sessions",
        "requests.structures",
        "urllib",
        "urllib.request",
        "urllib.parse",
        "urllib.error",
        "urllib.response",
        "urllib.robotparser",
        "email",
        "email.mime",
        "email.mime.text",
        "email.mime.multipart",
        "email.mime.base",
        "email.generator",
        "email.parser",
        "email.header",
        "email.utils",
        "email.charset",
        "email.encoders",
        "http",
        "http.client",
        "http.cookiejar",
        "configparser",
        "zipfile",
        "tarfile",
        "charset_normalizer",
        "idna",
        "certifi",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "numpy", "pandas", "scipy",
        "tkinter", "unittest", "pydoc",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

if IS_MAC:
    # macOS — собираем .app bundle
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="WorkshopDL",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe, a.binaries, a.datas,
        strip=False, upx=True,
        upx_exclude=[],
        name="WorkshopDL",
    )
    app = BUNDLE(
        coll,
        name="WorkshopDL.app",
        icon=None,
        bundle_identifier="com.workshopdl.app",
        info_plist={
            "CFBundleShortVersionString": "3.0",
            "NSHighResolutionCapable": True,
        },
    )
else:
    # Windows / Linux — одиночный файл
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="WorkshopDL",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,           # False = без консольного окна
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=None,               # замените на "icon.ico" если есть иконка
    )
