"""
Ядро автообновления программы WorkshopDL.

Работает с GitHub Releases API:
    GET https://api.github.com/repos/Pushkinmazila2/WorkshopDL/releases

Выбирает подходящий asset по платформе:
    Windows → WorkshopDL-windows.zip
    Linux   → WorkshopDL-linux.tar.gz
    macOS   → WorkshopDL-macos.zip
"""

import os, re, sys, json, shutil, tempfile, requests, subprocess
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
    Сравнивает версии вида:
      v4.0.55-f202185        (stable)
      v4.0.55-f202185-dev    (dev)
    Игнорирует хэш коммита, сравнивает только major.minor.build.
    Dev-суффикс делает версию меньше stable при равных числовых частях.
    Возвращает -1 если v1 < v2, 0 если равно, 1 если v1 > v2.
    """
    def parse(v: str):
        # Убираем префикс 'v'
        v = re.sub(r"^v", "", v)
        # Разделяем по '-'
        parts = v.split("-")
        # Первая часть — числовая (major.minor.build)
        nums = [int(x) for x in parts[0].split(".")]
        # Проверяем dev-суффикс в оставшихся частях
        is_dev = any("dev" in p for p in parts[1:])
        return nums, is_dev

    nums1, dev1 = parse(v1)
    nums2, dev2 = parse(v2)

    # Сравниваем числовые части
    max_len = max(len(nums1), len(nums2))
    for i in range(max_len):
        n1 = nums1[i] if i < len(nums1) else 0
        n2 = nums2[i] if i < len(nums2) else 0
        if n1 < n2:
            return -1
        if n1 > n2:
            return 1

    # Числовые части равны — сравниваем dev/stable
    # dev < stable (dev-версия считается ниже, чем stable с тем же номером)
    if dev1 and not dev2:
        return -1
    if not dev1 and dev2:
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
        channel — "stable" (только обычные релизы) или "dev" (только pre-release dev-сборки)

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

        best_candidate = None

        for release in releases:
            tag_name = release.get("tag_name", "")
            prerelease = release.get("prerelease", True)
            version = _parse_version(tag_name)
            if not version:
                continue
            if _compare_versions(version, current_version) <= 0:
                continue

            # Фильтр по каналу:
            #   stable → только обычные релизы (не pre-release)
            #   dev    → только pre-release (dev-сборки)
            if (channel == "stable" and prerelease) or (channel == "dev" and not prerelease):
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
                continue

            # GitHub API возвращает релизы от новых к старым,
            # поэтому первый подходящий — самый новый
            best_candidate = {
                "version": version,
                "tag_name": tag_name,
                "download_url": download_url,
                "asset_name": asset_name_found,
                "body": release.get("body", ""),
                "published_at": release.get("published_at", ""),
                "prerelease": prerelease,
            }
            break

        return best_candidate

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


def _write_update_script(script_path: str, target_exe: str, new_exe: str,
                         modules_src: Optional[str] = None,
                         modules_dst: Optional[str] = None) -> None:
    """
    Создаёт скрипт, который:
    1. Ждёт 2 секунды (чтобы основной процесс завершился)
    2. Копирует новый exe поверх старого
    3. Копирует папку Modules/ (языки и т.д.) если есть
    4. Запускает новый exe
    5. Удаляет сам себя
    """
    os.makedirs(os.path.dirname(script_path), exist_ok=True)

    if IS_WIN:
        lines = [
            "@echo off",
            'timeout /t 2 /nobreak >nul',
            f'copy /Y "{new_exe}" "{target_exe}" >nul 2>&1',
        ]
        if modules_src and modules_dst:
            lines.append(f'if exist "{modules_src}" (')
            lines.append(f'    if not exist "{modules_dst}" mkdir "{modules_dst}"')
            lines.append(f'    xcopy /E /Y "{modules_src}" "{modules_dst}" >nul 2>&1')
            lines.append(')')
        lines.extend([
            f'start "" "{target_exe}"',
            'del "%~f0"',
        ])
        content = "\n".join(lines)
        with open(script_path, "w", encoding="cp1251") as f:
            f.write(content)
    else:
        # shell-скрипт для Linux/macOS
        lines = [
            "#!/bin/sh",
            "sleep 2",
            f'cp "{new_exe}" "{target_exe}" 2>/dev/null',
        ]
        if modules_src and modules_dst:
            lines.append(f'if [ -d "{modules_src}" ]; then')
            lines.append(f'    mkdir -p "{modules_dst}"')
            lines.append(f'    cp -r "{modules_src}/." "{modules_dst}" 2>/dev/null')
            lines.append('fi')
        lines.extend([
            f'chmod +x "{target_exe}"',
            f'"{target_exe}" &',
            'rm -- "$0"',
        ])
        content = "\n".join(lines)
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(script_path, 0o755)


def apply_update(archive_path: str) -> bool:
    """
    Применяет обновление:
    1. Распаковывает архив во временную папку
    2. Находит новый exe
    3. Находит папку Modules/ (языки и т.д.)
    4. Создаёт и запускает скрипт-обновлятор
    5. Завершает текущий процесс

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

        # Ищем папку Modules/ внутри распакованного архива
        modules_src = None
        modules_dst = os.path.join(APP_DIR, "Modules")
        for root, dirs, _files in os.walk(extract_dir):
            if os.path.basename(root) == "Modules":
                modules_src = root
                break
            # Также проверяем, может Modules лежит прямо в корне
            if "Modules" in dirs:
                modules_src = os.path.join(root, "Modules")
                break

        target_exe = os.path.join(APP_DIR, exe_name)

        script_path = _get_update_script_path()
        _write_update_script(script_path, target_exe, new_exe,
                             modules_src=modules_src, modules_dst=modules_dst)

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

        # Завершаем текущий процесс мгновенно, не вызывая cleanup PyInstaller
        # (sys.exit(0) удаляет _MEI* папку, что мешает новому процессу запуститься)
        os._exit(0)

    except Exception:
        return False
