"""
Система локализации.
Кушает файлы напрямую из папки Modules/lang/ в формате {code}.json.
"""

import os
import json
import requests
from PyQt5.QtCore import QThread, pyqtSignal

# Импортируем пути из твоего конфига
from workshopdl.config import LANG_LOCAL_DIR, GITHUB_LANG_API, GITHUB_LANG_RAW

# ── Локализация ───────────────────────────────────────────────────────────────
_LANG: dict = {}
BASE_LANG_CODE = "en"  # Базовый язык для фолбэка

def lang_load(path_or_code: str = ""):
    """
    Загружает языковой пакет.
    Реализует механизм Fallback: сначала загружает базовый 'en', 
    а поверх него накладывает выбранный язык, чтобы избежать пустых ключей.
    """
    global _LANG
    new_lang = {}

    # Шаг 1: Пытаемся загрузить базовый английский язык для подстраховки
    base_path = os.path.join(LANG_LOCAL_DIR, f"{BASE_LANG_CODE}.json")
    if os.path.exists(base_path):
        try:
            with open(base_path, encoding="utf-8") as f:
                new_lang.update(json.load(f))
        except Exception:
            pass

    # Шаг 2: Определяем целевой путь
    if not path_or_code:
        # Если ничего не передано, используем базовый английский
        target_path = base_path
    elif os.path.sep in path_or_code or os.path.altsep and os.path.altsep in path_or_code:
        # Если передан полноценный путь
        target_path = path_or_code
    else:
        # Если передан только код (например, "ru")
        target_path = os.path.join(LANG_LOCAL_DIR, f"{path_or_code}.json")

    # Шаг 3: Накатываем целевой язык поверх базового (если целевой язык не базовый)
    if target_path != base_path and os.path.exists(target_path):
        try:
            with open(target_path, encoding="utf-8") as f:
                user_lang = json.load(f)
                if isinstance(user_lang, dict):
                    new_lang.update(user_lang)
        except Exception:
            pass

    _LANG = new_lang


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
    """
    Сканирует ТОЛЬКО папку Modules/lang/ и возвращает список доступных языков.
    Возвращает: список кортежей (code, display_name, path)
    """
    result = []
    if not os.path.isdir(LANG_LOCAL_DIR):
        return result

    try:
        for f in os.listdir(LANG_LOCAL_DIR):
            if f.endswith(".json"):
                code = lang_code_from_filename(f)
                path = lang_local_path(code)
                result.append((code, lang_display_name(code), path))
    except Exception:
        pass

    return sorted(result, key=lambda x: x[0])


class LangFetchWorker(QThread):
    """Загружает список доступных языков с GitHub и опционально скачивает один."""
    list_ready   = pyqtSignal(list)       # [(code, display_name, is_downloaded), ...]
    dl_progress  = pyqtSignal(str)        # статус скачивания
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
            
            # Получаем коды языков, которые уже есть локально в Modules/lang
            local_codes = {c for c, _, _ in lang_list_local()}
            result = []
            
            for f in files:
                if f.get("type") == "file" and f["name"].endswith(".json"):
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