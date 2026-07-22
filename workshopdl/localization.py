"""
Система локализации.
"""

import os, json, requests
from PyQt5.QtCore import QThread, pyqtSignal

from workshopdl.config import LANG_DEF_PATH, LANG_LOCAL_DIR, APP_DIR, GITHUB_LANG_API, GITHUB_LANG_RAW

# ── Локализация ───────────────────────────────────────────────────────────────
_LANG: dict = {}

def lang_load(path: str = ""):
    global _LANG
    target = path or LANG_DEF_PATH
    try:
        with open(target, encoding="utf-8") as f:
            _LANG = json.load(f)
    except Exception:
        _LANG = {}

def t(key: str, **kw) -> str:
    """Возвращает переведённую строку по ключу."""
    s = _LANG.get(key, key)
    return s.format(**kw) if kw else s


# Человекочитаемые имена языков по коду файла
LANG_DISPLAY = {
    "en": "🇬🇧 English",
    "ru": "🇷🇺 Русский",
    "de": "🇩🇪 Deutsch",
    "zh": "🇨🇳 中文",
    "fr": "🇫🇷 Français",
    "es": "🇪🇸 Español",
    "pl": "🇵🇱 Polski",
    "uk": "🇺🇦 Українська",
    "tr": "🇹🇷 Türkçe",
    "pt": "🇵🇹 Português",
    "ja": "🇯🇵 日本語",
    "ko": "🇰🇷 한국어",
}

def lang_code_from_filename(filename: str) -> str:
    """'ru.json' → 'ru'"""
    return os.path.splitext(filename)[0].lower()

def lang_display_name(code: str) -> str:
    return LANG_DISPLAY.get(code, f"🌐 {code.upper()}")

def lang_local_path(code: str) -> str:
    return os.path.join(LANG_LOCAL_DIR, f"{code}.json")

def lang_list_local() -> list:
    """Возвращает список (code, display_name, path) локально доступных языков."""
    result = []
    for f in os.listdir(APP_DIR):
        if f.startswith("lang_") and f.endswith(".json"):
            code = f[5:-5]
            result.append((code, lang_display_name(code), os.path.join(APP_DIR, f)))
    if os.path.isdir(LANG_LOCAL_DIR):
        for f in os.listdir(LANG_LOCAL_DIR):
            if f.endswith(".json"):
                code = lang_code_from_filename(f)
                path = lang_local_path(code)
                if not any(c == code for c, _, _ in result):
                    result.append((code, lang_display_name(code), path))
    return sorted(result, key=lambda x: x[0])


class LangFetchWorker(QThread):
    """Загружает список доступных языков с GitHub и опционально скачивает один."""
    list_ready   = pyqtSignal(list)   # [(code, display_name, is_downloaded), ...]
    dl_progress  = pyqtSignal(str)    # статус скачки
    dl_done      = pyqtSignal(bool, str)  # success, local_path_or_error

    def __init__(self, download_code: str = ""):
        super().__init__()
        self.download_code = download_code

    def run(self):
        if self.download_code:
            self._download(self.download_code)
        else:
            self._fetch_list()

    def _fetch_list(self):
        try:
            r = requests.get(GITHUB_LANG_API, timeout=8,
                             headers={"Accept": "application/vnd.github.v3+json"})
            r.raise_for_status()
            files = r.json()
            local_codes = {c for c, _, _ in lang_list_local()}
            result = []
            for f in files:
                if f["name"].endswith(".json"):
                    code = lang_code_from_filename(f["name"])
                    result.append((code, lang_display_name(code), code in local_codes))
            self.list_ready.emit(sorted(result, key=lambda x: x[0]))
        except Exception as e:
            self.list_ready.emit([])

    def _download(self, code: str):
        url = f"{GITHUB_LANG_RAW}/{code}.json"
        self.dl_progress.emit(f"⬇  Загружаю {lang_display_name(code)}...")
        try:
            os.makedirs(LANG_LOCAL_DIR, exist_ok=True)
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
            dest = lang_local_path(code)
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.dl_done.emit(True, dest)
        except Exception as e:
            self.dl_done.emit(False, str(e))