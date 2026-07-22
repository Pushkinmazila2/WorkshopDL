"""
Конфигурация: платформа, пути, конфиг-файл.
"""

import sys, os, subprocess, shutil, configparser

# ── Платформа ─────────────────────────────────────────────────────────────────
IS_WIN   = sys.platform == "win32"
IS_MAC   = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# Имя исполняемого файла steamcmd
STEAMCMD_BIN = "steamcmd.exe" if IS_WIN else "steamcmd.sh" if IS_LINUX else "steamcmd"

# URL для скачки bootstrapper
STEAMCMD_DL_URL = (
    "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"          if IS_WIN   else
    "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz" if IS_LINUX else
    "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_osx.tar.gz"   # macOS
)
STEAMCMD_ARCHIVE_IS_ZIP = IS_WIN  # True → .zip, False → .tar.gz

STEAMCMD_ZIP_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"

def open_folder(path: str):
    """Открывает папку в файловом менеджере на любой ОС."""
    if not os.path.isdir(path):
        return False
    try:
        if IS_WIN:
            os.startfile(path)
        elif IS_MAC:
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False

def safe_rename(src: str, dst: str) -> str:
    """
    Переименовывает папку мода.
    Если src и dst на разных устройствах — копирует и удаляет (редкий случай).
    Возвращает итоговый путь.
    """
    try:
        os.rename(src, dst)
        return dst
    except OSError:
        try:
            shutil.move(src, dst)
            return dst
        except Exception:
            return src

# ── Пути ──────────────────────────────────────────────────────────────────────
APP_DIR        = os.path.dirname(os.path.abspath(sys.argv[0]))
STEAMCMD_DEF   = os.path.join(APP_DIR, "steamcmd", STEAMCMD_BIN)
INI_PATH       = os.path.join(APP_DIR, "WorkshopDL.ini")
MODULES_PATH   = os.path.join(APP_DIR, "Modules")
QUEUE_PATH     = os.path.join(MODULES_PATH, "queue.json")
HISTORY_PATH   = os.path.join(MODULES_PATH, "history.json")
MOD_PATHS_PATH = os.path.join(MODULES_PATH, "mod_paths.json")
LANG_DEF_PATH  = os.path.join(APP_DIR, "lang_en.json")   # английский — базовый язык

# ── GitHub-интеграция языков ──────────────────────────────────────────────────
GITHUB_REPO      = "Pushkinmazila2/WorkshopDL"
GITHUB_LANG_API  = f"https://api.github.com/repos/{GITHUB_REPO}/contents/lang"
GITHUB_LANG_RAW  = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/lang"
LANG_LOCAL_DIR   = os.path.join(MODULES_PATH, "lang")

# ── Установщик модов: GitHub ──────────────────────────────────────────────────
INSTALL_REPO_DEFAULT = "Pushkinmazila2/WorkshopDL"
INSTALL_PATH_DEFAULT = "install"
INSTALL_LOCAL_DIR    = os.path.join(MODULES_PATH, "install")

# ── Конфиг ────────────────────────────────────────────────────────────────────
def load_config():
    cfg = configparser.ConfigParser()
    cfg.read(INI_PATH, encoding="utf-8")
    return cfg

def save_config(cfg):
    with open(INI_PATH, "w", encoding="utf-8") as f:
        cfg.write(f)

def cfg_get(cfg, section, key, fallback=""):
    try:
        return cfg.get(section, key)
    except Exception:
        return fallback

# ── Отключение/включение мода (переименование папки) ─────────────────────────
DISABLED_SUFFIX = ".disabled"

def mod_is_disabled(folder_path: str) -> bool:
    return folder_path.endswith(DISABLED_SUFFIX)

def mod_toggle(folder_path: str) -> str:
    if mod_is_disabled(folder_path):
        new_path = folder_path[: -len(DISABLED_SUFFIX)]
    else:
        new_path = folder_path + DISABLED_SUFFIX
    return safe_rename(folder_path, new_path)

def folder_size_mb(path: str) -> float:
    """Считает размер папки рекурсивно в МБ."""
    total = 0
    try:
        for dirpath, _, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except Exception:
                    pass
    except Exception:
        pass
    return total / (1024 * 1024)


# ── _install_repo_url ─────────────────────────────────────────────────────────
def install_repo_url(cfg: configparser.ConfigParser = None) -> tuple[str, str]:
    """
    Возвращает (raw_base_url, api_base_url) для инструкций установки.
    Читает из cfg если передан, иначе возвращает дефолт.
    """
    if cfg is not None:
        saved = cfg_get(cfg, "WorkshopDL", "InstallRepo", "")
        if saved:
            repo_str = saved.strip()
        else:
            repo_str = f"{INSTALL_REPO_DEFAULT}/{INSTALL_PATH_DEFAULT}"
    else:
        repo_str = f"{INSTALL_REPO_DEFAULT}/{INSTALL_PATH_DEFAULT}"

    if repo_str.startswith("https://"):
        raw = repo_str.rstrip("/")
        api = raw
        return raw, api

    parts = repo_str.strip("/").split("/")
    if len(parts) < 2:
        parts = [INSTALL_REPO_DEFAULT, INSTALL_PATH_DEFAULT]

    owner  = parts[0]
    repo   = parts[1]

    if len(parts) >= 4 and parts[2] == "tree":
        branch = parts[3]
        folder = "/".join(parts[4:]) if len(parts) > 4 else ""
    else:
        branch = "main"
        folder = "/".join(parts[2:]) if len(parts) > 2 else INSTALL_PATH_DEFAULT

    folder = folder.strip("/") or INSTALL_PATH_DEFAULT
    raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{folder}"
    api = f"https://api.github.com/repos/{owner}/{repo}/contents/{folder}"
    return raw, api

# Динамические URL — обновляются при загрузке настроек
GITHUB_INSTALL_RAW, GITHUB_INSTALL_API = install_repo_url()