"""
Определение магазина и версии игры по файлам в папке игры.
"""

import os, re, json, glob

from workshopdl.config import IS_WIN, IS_MAC, IS_LINUX
from workshopdl.installer.utils import _pf_read_file_value


# Известные файлы-маркеры версии для каждого магазина.
_STORE_VERSION_READERS = {
    "gog": [
        {
            "file":    "goggame-*.info",
            "format":  "json",
            "extract": {"path": "version"},
            "label":   "GOG манифест (version)",
        },
        {
            "file":    "goggame-*.info",
            "format":  "json",
            "extract": {"path": "gameId"},
            "label":   "GOG манифест (gameId)",
        },
        {
            "file":    "gameinfo",
            "format":  "text",
            "extract": {"line": 2},
            "label":   "GOG gameinfo (строка 2)",
        },
    ],
    "epic": [
        {
            "file":    ".egstore/*.item",
            "format":  "json",
            "extract": {"path": "AppVersionString"},
            "label":   "Epic .egstore manifest (AppVersionString)",
        },
        {
            "file":    ".egstore/*.item",
            "format":  "json",
            "extract": {"path": "BuildVersion"},
            "label":   "Epic .egstore manifest (BuildVersion)",
        },
    ],
    "steam": [
        {
            "file":    "../*.acf",
            "format":  "text",
            "extract": {"regex": r'"buildid"\s+"(\d+)"'},
            "label":   "Steam .acf buildid",
            "transform": "strip",
        },
    ],
    "_universal": [
        {
            "file":    "version.txt",
            "format":  "text",
            "extract": {"regex": r"(\d+[\.\d]+)"},
            "label":   "version.txt",
        },
        {
            "file":    "Version.txt",
            "format":  "text",
            "extract": {"regex": r"(\d+[\.\d]+)"},
            "label":   "Version.txt",
        },
        {
            "file":    "version.json",
            "format":  "json",
            "extract": {"path": "version"},
            "label":   "version.json (.version)",
        },
        {
            "file":    "version.json",
            "format":  "json",
            "extract": {"path": "Version"},
            "label":   "version.json (.Version)",
        },
        {
            "file":    "app.info",
            "format":  "json",
            "extract": {"path": "version"},
            "label":   "app.info (.version)",
        },
    ],
}

_STORE_SIGNATURE_FILES = {
    "gog": [
        "goggame-*.info",
        "goggame-*.id",
        "GalaxyAPI.dll",
        "Galaxy64.dll",
        "goggame.ico",
        "gog.ico",
        "gameinfo",
        "GalaxyCSharpGlue*.dll",
    ],
    "epic": [
        ".egstore",
        "EOSSDK-Win64-Shipping.dll",
        "EOSSDK-Win32-Shipping.dll",
        "libEOSSDK-Linux-Shipping.so",
    ],
}


def _auto_detect_version(game_folder: str, store: str, params: dict = None, ctx: dict = None) -> str:
    """
    Пробует все известные способы прочитать версию игры из файлов в папке игры.
    """
    ctx    = ctx    or {}
    params = params or {}

    readers = []
    readers += _STORE_VERSION_READERS.get(store, [])
    readers += _STORE_VERSION_READERS["_universal"]
    readers += params.get("version_readers", [])

    for reader in readers:
        val = _pf_read_file_value(game_folder, reader, ctx)
        if val and val.strip():
            return val.strip()

    if params.get("version_file"):
        val = _pf_read_file_value(game_folder, params["version_file"], ctx)
        if val:
            return val.strip()

    return ""


def _pf_detect_game_store(game_folder: str, params: dict, ctx: dict) -> dict:
    """
    Определяет магазин и версию игры исключительно по файлам в папке игры.
    """
    if not game_folder or not os.path.isdir(game_folder):
        return {
            "store": "unknown", "version": "",
            "evidence": ["папка игры не найдена или не существует"],
            "game_folder": game_folder,
        }

    if params.get("force_store"):
        forced  = params["force_store"]
        version = _auto_detect_version(game_folder, forced, params, ctx)
        return {
            "store": forced, "version": version,
            "evidence": [f"force_store={forced} задан в инструкции"],
            "game_folder": game_folder,
        }

    evidence: list[str] = []
    votes = {"gog": 0, "epic": 0, "steam": 0}

    try:
        dir_listing = os.listdir(game_folder)
    except Exception:
        dir_listing = []
    dir_set = set(dir_listing)

    sig_files = dict(_STORE_SIGNATURE_FILES)
    for st, files in params.get("hints", {}).items():
        sig_files.setdefault(st, []).extend(files)

    for st, patterns in sig_files.items():
        for pattern in patterns:
            if not pattern.endswith(("*", ".dll", ".so", ".ico", ".info", ".id")):
                if os.path.isdir(os.path.join(game_folder, pattern)):
                    votes[st] = votes.get(st, 0) + 5
                    evidence.append(f"папка {pattern}/")
                continue
            if "*" in pattern:
                matches = glob.glob(os.path.join(game_folder, pattern))
                if matches:
                    votes[st] = votes.get(st, 0) + 5
                    evidence.append(f"файл {os.path.basename(matches[0])}")
            else:
                if pattern in dir_set:
                    votes[st] = votes.get(st, 0) + 4
                    evidence.append(f"файл {pattern}")

    detected = max(votes, key=votes.get) if any(v > 0 for v in votes.values()) else "other"
    version = _auto_detect_version(game_folder, detected, params, ctx)

    return {
        "store":       detected,
        "version":     version,
        "evidence":    evidence,
        "game_folder": game_folder,
        "votes":       votes,
    }