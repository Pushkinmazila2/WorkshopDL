"""
Ядро автообновления программы WorkshopDL.

Работает с GitHub Releases API:
    GET https://api.github.com/repos/Pushkinmazila2/WorkshopDL/releases

Выбирает подходящий asset по платформе:
    Windows → WorkshopDL-windows.zip
    Linux   → WorkshopDL-linux.tar.gz
    macOS   → WorkshopDL-macos.zip
"""

import os
import re
import sys
import json
import shutil
import tempfile
import requests
import subprocess
from typing import Callable, Optional

from workshopdl.config import (
    IS_WIN, IS_MAC, IS_LINUX,
    APP_DIR, UPDATE_TEMP_DIR,
)

__all__ = [
    "check_for_updates",
    "download_update",
    "apply_update",
    "ASSET_NAME",
]

# ── Asset name по платформе ──────────────────────────────────────────────────
if IS_WIN:
    ASSET_NAME = "WorkshopDL-windows.zip"
elif IS_MAC:
    ASSET_NAME = "WorkshopDL-macos.zip"
else:
    ASSET_NAME = "WorkshopDL-linux.tar.gz"

GITHUB_RELEASES_API = "https://api.github.com/repos/Pushkinmazila2/WorkshopDL/releases"


def _parse_version(tag_name: str) -> str:
    """'v1.2.3' → '1.2.3'"""
    return re.sub(r"^v", "", tag_name.strip())


def _compare_versions(v1: str, v2: str) -> int:
    """
    Сравнивает семантические версии.
    Возвращает -1 если v1 < v2, 0 если равно, 1 если v1 > v2.
    """
    def parse(v: str):
        parts = v.replace("-", ".").split(".")
        nums = []
        for p in parts:
            try:
                nums.append(int(p))
            except ValueError:
                nums.append(0)
        return nums

    a = parse(v1)
    b = parse(v2)
    for i in range(max(len(a), len(b))):
        na = a[i] if i < len(a) else 0
        nb = b[i] if i < len(b) else 0
        if na < nb:
            return -1
        if na > nb:
            return 1
    return 0


def check_for_updates(
    current_version: str,
    channel: str = "stable",
) -> Optional[dict]:
    """
    Проверяет наличие обновления на GitHub Releases.

    Параметры:
        current_version — текущая версия программы (из __version__)
        channel — "stable" (только релизы) или "dev" (включая pre-release)

    Возвращает словарь с информацией о новой версии или None:
        {
            "version": "1.2.3",
            "tag_name": "v1.2.3",
            "download_url": "https://...",
            "asset_name": "WorkshopDL-windows.zip",
            "body": "Release notes...",
            "published_at": "2024-01-01T00:00:00Z",
            "prerelease": False,
        }
    """
    try:
        resp = requests.get(GITHUB_RELEASES_API, timeout=15,
                            headers={"Accept": "application/vnd.github.v3+json",
                                     "User-Agent": "WorkshopDL-Updater/1.0"})
        resp.raise_for_status()
        releases = resp.json()

        if not isinstance(releases, list) or len(releases) == 0:
            return None

        for release in releases:
            tag_name = release.get("tag_name", "")
            prerelease = release.get("prerelease", True)

            # Фильтр по каналу
            if channel == "stable" and prerelease:
                continue
            if channel == "dev" and prerelease:
                # Dev-канал — подходят pre-release тоже, берём первый подходящий
                pass

            version = _parse_version(tag_name)
            if not version:
                continue

            # Сравнение версий
            if _compare_versions(version, current_version) <= 0:
                # Версия не выше текущей — ищем дальше (может быть более новая)
                continue

            # Ищем подходящий asset для платформы
            assets = release.get("assets", [])
            download_url = None
            asset_name_found = None
            for asset in assets:
                name = asset.get("name", "")
                if name == ASSET_NAME:
                    download_url = asset.get("browser_download_url")
                    asset_name_found = name
                    break

            if not download_url:
                # Пропускаем релиз без подходящего asset
                continue

            return {
                "version": version,
                "tag_name": tag_name,
                "download_url": download_url,
                "asset_name": asset_name_found,
                "body": release.get("body", ""),
                "published_at": release.get("published_at", ""),
                "prerelease": prerelease,
            }

        return None

    except requests.RequestException:
        return None
    except (ValueError, KeyError, TypeError):
        return None


def download_update(
    url: str,
    dest_dir: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Optional[str]:
    """
    Скачивает файл обновления из url в dest_dir.

    Возвращает полный путь к скачанному файлу или None при ошибке.
    progress_callback(current_bytes, total_bytes).
    """
    try:
        os.makedirs(dest_dir, exist_ok=True)
        local_filename = url.split("/")[-1] or "update.zip"
        dest_path = os.path.join(dest_dir, local_filename)

        # Удаляем старый файл, если есть
        if os.path.exists(dest_path):
            os.remove(dest_path)

        resp = requests.get(url, stream=True, timeout=30,
                            headers={"User-Agent": "WorkshopDL-Updater/1.0"})
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total:
                        progress_callback(downloaded, total)

        return dest_path

    except Exception:
        return None


def _extract_archive(archive_path: str, extract_dir: str) -> bool:
    """Распаковывает архив (zip или tar.gz) в указанную папку."""
    try:
        os.makedirs(extract_dir, exist_ok=True)

        if archive_path.endswith(".zip"):
            import zipfile
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(extract_dir)
        elif archive_path.endswith(".tar.gz") or archive_path.endswith(".tgz"):
            import tarfile
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(extract_dir)
        else:
            return False

        return True
    except Exception:
        return False


def _get_update_script_path() -> str:
    """Возвращает путь к скрипту-обновлятору."""
    if IS_WIN:
        return os.path.join(UPDATE_TEMP_DIR, "update.bat")
    else:
        return os.path.join(UPDATE_TEMP_DIR, "update.sh")


def _write_update_script(script_path: str, target_exe: str, new_exe: str) -> None:
    """
    Создаёт скрипт, который:
    1. Ждёт 2 секунды (чтобы основной процесс завершился)
    2. Копирует новый exe поверх старого
    3. Запускает новый exe
    4. Удаляет сам себя
    """
    os.makedirs(os.path.dirname(script_path), exist_ok=True)

    if IS_WIN:
        content = f"""@echo off
timeout /t 2 /nobreak >nul
copy /Y "{new_exe}" "{target_exe}" >nul 2>&1
start "" "{target_exe}"
del "%~f0"
"""
        with open(script_path, "w", encoding="cp1251") as f:
            f.write(content)
    else:
        # shell-скрипт для Linux/macOS
        content = f"""#!/bin/sh
sleep 2
cp "{new_exe}" "{target_exe}" 2>/dev/null
chmod +x "{target_exe}"
"{target_exe}" &
rm -- "$0"
"""
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(script_path, 0o755)


def apply_update(archive_path: str) -> bool:
    """
    Применяет обновление:
    1. Распаковывает архив во временную папку
    2. Находит новый exe
    3. Создаёт и запускает скрипт-обновлятор
    4. Завершает текущий процесс

    Возвращает True если скрипт запущен, иначе False.
    """
    try:
        extract_dir = os.path.join(UPDATE_TEMP_DIR, "extracted")
        # Очищаем старую распаковку
        if os.path.isdir(extract_dir):
            shutil.rmtree(extract_dir)

        if not _extract_archive(archive_path, extract_dir):
            return False

        # Ищем exe внутри распакованной папки
        new_exe = None
        exe_name = "WorkshopDL.exe" if IS_WIN else "WorkshopDL"
        for root, _dirs, files in os.walk(extract_dir):
            for f in files:
                if f == exe_name:
                    new_exe = os.path.join(root, f)
                    break
            if new_exe:
                break

        if not new_exe or not os.path.isfile(new_exe):
            return False

        target_exe = os.path.join(APP_DIR, exe_name)

        script_path = _get_update_script_path()
        _write_update_script(script_path, target_exe, new_exe)

        # Запускаем скрипт
        if IS_WIN:
            subprocess.Popen(
                [script_path],
                shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            subprocess.Popen(
                ["sh", script_path],
                start_new_session=True,
            )

        # Завершаем текущий процесс
        sys.exit(0)

    except Exception:
        return False