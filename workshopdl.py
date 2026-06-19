"""
WorkshopDL — Python Edition v4
Полный аналог WorkshopDL с улучшенным интерфейсом:
- Система локализации (JSON-файлы)
- Таблица модов с кнопками: Steam / Вкл-Выкл / Открыть папку
- Отключение модов (переименование папки .disabled)
- Скрываемые столбцы дат
- Размер мода в таблице
- Пауза / продолжение, история игр, автопоиск Game ID
- [v4] Установка модов после скачивания
  - Инструкции хранятся на GitHub (game_id.json)
  - Два формата: Параметрический (declarative) и Гибридный (JSON + Python-плагин)
  - Автопоиск папки игры, умное копирование/распаковка, работа с ini/json
  - Диалог с вопросами к пользователю (text/select/checkbox)
  - Лог статуса установки
"""

import sys, os, re, json, subprocess, threading, configparser, datetime, shutil
import zipfile, urllib.request, importlib.util, glob, fnmatch
import requests
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QListWidget, QListWidgetItem, QLabel,
    QTextEdit, QGroupBox, QCheckBox, QTabWidget, QMessageBox,
    QFileDialog, QProgressBar, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSizePolicy, QAction, QToolBar, QSpinBox,
    QDialog, QDialogButtonBox, QScrollArea, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QUrl, pyqtSlot
from PyQt5.QtGui import QFont, QColor, QBrush, QDesktopServices

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

# ── Очередь ───────────────────────────────────────────────────────────────────
def queue_save(game_id, mod_ids, done_count):
    os.makedirs(MODULES_PATH, exist_ok=True)
    with open(QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump({"game_id": game_id, "mod_ids": mod_ids, "done_count": done_count}, f)

def queue_load():
    if not os.path.exists(QUEUE_PATH):
        return None
    try:
        with open(QUEUE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def queue_clear():
    if os.path.exists(QUEUE_PATH):
        os.remove(QUEUE_PATH)

# ── История игр ───────────────────────────────────────────────────────────────
def history_load() -> dict:
    """
    Возвращает историю игр.
    Формат (новый): {game_id: {name, game_folder, last_used}}
    Формат (старый): {game_id: "game_name"}  — автоматически мигрирует
    """
    if not os.path.exists(HISTORY_PATH):
        return {}
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        # Миграция старого формата {id: str} → {id: {name, game_folder, last_used}}
        migrated = False
        for k, v in data.items():
            if isinstance(v, str):
                data[k] = {"name": v, "game_folder": "", "last_used": ""}
                migrated = True
        if migrated:
            history_save(data)
        return data
    except Exception:
        return {}

def history_save(data: dict):
    os.makedirs(MODULES_PATH, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def history_add(game_id: str, game_name: str = "", game_folder: str = ""):
    """Добавляет или обновляет запись в истории игр."""
    data  = history_load()
    entry = data.get(game_id, {})
    if isinstance(entry, str):
        entry = {"name": entry, "game_folder": "", "last_used": ""}

    if game_name and game_name != game_id:
        entry["name"] = game_name
    elif "name" not in entry:
        entry["name"] = game_id

    if game_folder and os.path.isdir(game_folder):
        entry["game_folder"] = game_folder

    entry["last_used"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    data[game_id] = entry
    history_save(data)

def history_get_name(game_id: str) -> str:
    """Возвращает название игры из истории или game_id если не найдено."""
    entry = history_load().get(game_id, {})
    if isinstance(entry, dict):
        return entry.get("name", game_id) or game_id
    return str(entry) or game_id

def history_get_game_folder(game_id: str) -> str:
    """
    Возвращает сохранённый путь к папке игры из истории.
    Проверяет что папка реально существует — иначе возвращает "".
    """
    entry = history_load().get(game_id, {})
    if isinstance(entry, dict):
        folder = entry.get("game_folder", "")
        if folder and os.path.isdir(folder):
            return folder
    return ""

def history_set_game_folder(game_id: str, game_folder: str):
    """Сохраняет путь к папке игры в историю."""
    if game_folder and os.path.isdir(game_folder):
        history_add(game_id, game_folder=game_folder)

def history_scan_from_disk(content_path):
    if not os.path.isdir(content_path):
        return
    data = history_load()
    changed = False
    for e in os.scandir(content_path):
        if e.is_dir() and e.name.isdigit() and e.name not in data:
            data[e.name] = e.name
            changed = True
    if changed:
        history_save(data)

# ── Сохранённые пути к папкам модов ──────────────────────────────────────────
def mod_paths_load():
    if not os.path.exists(MOD_PATHS_PATH):
        return []
    try:
        with open(MOD_PATHS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def mod_paths_save(paths):
    os.makedirs(MODULES_PATH, exist_ok=True)
    with open(MOD_PATHS_PATH, "w", encoding="utf-8") as f:
        json.dump(paths, f, ensure_ascii=False)

def mod_paths_add(path):
    path = path.strip()
    if not path:
        return
    paths = mod_paths_load()
    if path in paths:
        paths.remove(path)
    paths.insert(0, path)
    mod_paths_save(paths[:20])

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

# ── Steam API ─────────────────────────────────────────────────────────────────
def fetch_game_id_for_mod(workshop_id):
    try:
        r = requests.post(
            "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
            data={"itemcount": "1", "publishedfileids[0]": workshop_id}, timeout=10
        )
        d = r.json()["response"]["publishedfiledetails"][0]
        app_id = str(d.get("consumer_app_id", ""))
        name = ""
        if app_id:
            try:
                r2 = requests.get(
                    f"https://store.steampowered.com/api/appdetails?appids={app_id}&filters=basic",
                    timeout=8
                )
                name = r2.json().get(app_id, {}).get("data", {}).get("name", "")
            except Exception:
                pass
        return app_id, name
    except Exception:
        return "", ""

def fetch_collection(collection_id):
    try:
        r = requests.post(
            "https://api.steampowered.com/ISteamRemoteStorage/GetCollectionDetails/v1/",
            data={"collectioncount": "1", "publishedfileids[0]": collection_id}, timeout=10
        )
        children = r.json()["response"]["collectiondetails"][0].get("children", [])
        return [str(c["publishedfileid"]) for c in children]
    except Exception:
        return []

def fetch_mod_details_batch(mod_ids: list) -> dict:
    """Возвращает {mod_id: {title, time_updated, children: [mod_id, ...]}}"""
    result = {}
    for i in range(0, len(mod_ids), 100):
        chunk = mod_ids[i:i+100]
        data = {"itemcount": str(len(chunk))}
        for j, mid in enumerate(chunk):
            data[f"publishedfileids[{j}]"] = mid
        try:
            r = requests.post(
                "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
                data=data, timeout=15
            )
            for item in r.json()["response"]["publishedfiledetails"]:
                fid = str(item.get("publishedfileid", ""))
                # children — зависимости мода (другие моды)
                children = [
                    str(c["publishedfileid"])
                    for c in item.get("children", [])
                    if c.get("file_type", 0) == 0   # 0 = Workshop item, не DLC
                ]
                result[fid] = {
                    "title":        item.get("title", fid),
                    "time_updated": int(item.get("time_updated", 0)),
                    "children":     children,
                }
        except Exception:
            pass
    return result


def fetch_dependencies(mod_ids: list, depth: int = 3) -> dict:
    """
    Рекурсивно собирает все зависимости для списка модов.
    Возвращает {dep_id: title} — только зависимости, не сами моды.
    depth — максимальная глубина рекурсии (защита от циклов).
    """
    if depth == 0 or not mod_ids:
        return {}
    details = fetch_mod_details_batch(mod_ids)
    all_deps = {}
    next_level = []
    for mid, info in details.items():
        for child_id in info.get("children", []):
            if child_id not in all_deps:
                child_info = details.get(child_id)
                title = child_info["title"] if child_info else child_id
                all_deps[child_id] = title
                next_level.append(child_id)
    # Убираем уже известные из следующего уровня
    next_level = [x for x in next_level if x not in details]
    if next_level:
        deeper = fetch_dependencies(next_level, depth - 1)
        for k, v in deeper.items():
            all_deps.setdefault(k, v)
    return all_deps


# ── Воркер скачки SteamCMD ────────────────────────────────────────────────────
STEAMCMD_ZIP_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"

class SteamCMDInstallWorker(QThread):
    status  = pyqtSignal(str)   # текстовое сообщение
    percent = pyqtSignal(int)   # 0-100
    log_line = pyqtSignal(str)  # строки из stdout steamcmd
    done    = pyqtSignal(bool, str)  # success, path_or_error

    def run(self):
        dest_dir = os.path.join(APP_DIR, "steamcmd")
        exe_path = os.path.join(dest_dir, STEAMCMD_BIN)
        archive_name = "steamcmd.zip" if STEAMCMD_ARCHIVE_IS_ZIP else "steamcmd.tar.gz"
        archive_path = os.path.join(dest_dir, archive_name)
        try:
            os.makedirs(dest_dir, exist_ok=True)

            # ── Шаг 1: скачать bootstrapper ───────────────────────────────────
            self.status.emit(t("steamcmd_dl_downloading"))
            self.percent.emit(0)

            def reporthook(count, block, total):
                if total > 0:
                    pct = min(int(count * block * 100 / total), 30)
                    self.percent.emit(pct)

            urllib.request.urlretrieve(STEAMCMD_DL_URL, archive_path, reporthook)

            # ── Шаг 2: распаковать ────────────────────────────────────────────
            self.status.emit(t("steamcmd_dl_unpacking"))
            self.percent.emit(31)
            if STEAMCMD_ARCHIVE_IS_ZIP:
                with zipfile.ZipFile(archive_path, "r") as z:
                    z.extractall(dest_dir)
            else:
                import tarfile
                with tarfile.open(archive_path, "r:gz") as t_:
                    t_.extractall(dest_dir)
                # На Linux steamcmd.sh нужен chmod +x
                if not IS_WIN and os.path.exists(exe_path):
                    os.chmod(exe_path, 0o755)
            os.remove(archive_path)

            if not os.path.exists(exe_path):
                self.done.emit(False, t("steamcmd_dl_exe_missing")); return

            # ── Шаг 3: первый запуск — steamcmd докачивает движок (~40 МБ) ───
            self.status.emit(t("steamcmd_dl_init"))
            self.percent.emit(35)
            self.log_line.emit("─── SteamCMD self-update ───")

            flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
            proc = subprocess.Popen(
                [exe_path, "+quit"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=flags
            )

            import re as _re
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self.log_line.emit(line)
                    m = _re.search(r"\[\s*(\d+)%\]", line)
                    if m:
                        pct = int(m.group(1))
                        self.percent.emit(35 + int(pct * 0.63))

            proc.wait()
            self.percent.emit(100)
            self.status.emit(t("steamcmd_dl_done"))
            self.done.emit(True, exe_path)

        except Exception as e:
            self.done.emit(False, str(e))


# ── Воркер скачки ─────────────────────────────────────────────────────────────
class DownloadWorker(QThread):
    log_line   = pyqtSignal(str)
    progress   = pyqtSignal(int, int)
    finished   = pyqtSignal(int, int)
    paused     = pyqtSignal(int)
    deps_found = pyqtSignal(dict)   # {dep_id: title}

    def __init__(self, steamcmd, game_id, mod_ids, anonymous, username, password,
                 start_from=0, batch_size=1):
        super().__init__()
        self.steamcmd   = steamcmd
        self.game_id    = game_id
        self.mod_ids    = mod_ids
        self.anonymous  = anonymous
        self.username   = username
        self.password   = password
        self.start_from = start_from
        self.batch_size = max(1, batch_size)
        self._stop = self._pause = False

    def stop(self):  self._stop  = True
    def pause(self): self._pause = True

    def run(self):
        # ── Проверяем зависимости перед скачкой ───────────────────────────────
        if self.start_from == 0:
            self.log_line.emit("🔗 Проверка зависимостей...")
            try:
                all_deps = fetch_dependencies(self.mod_ids)
                known    = set(self.mod_ids)
                new_deps = {k: v for k, v in all_deps.items() if k not in known}
                if new_deps:
                    self.log_line.emit(f"🔗 Найдено {len(new_deps)} зависимост(ей) — см. диалог")
                    self.deps_found.emit(new_deps)
                else:
                    self.log_line.emit("🔗 Зависимостей нет")
            except Exception as e:
                self.log_line.emit(f"🔗 Не удалось проверить зависимости: {e}")

        total   = len(self.mod_ids)
        pending = [m for i, m in enumerate(self.mod_ids, 1) if i > self.start_from]
        success = self.start_from
        fail    = 0
        done    = self.start_from   # сколько обработано всего

        # ── Разбиваем на пачки ────────────────────────────────────────────────
        for batch_start in range(0, len(pending), self.batch_size):
            if self._stop:
                queue_clear(); break
            if self._pause:
                queue_save(self.game_id, self.mod_ids, done)
                self.paused.emit(total - done)
                return

            batch = pending[batch_start : batch_start + self.batch_size]

            if self.batch_size == 1:
                # Одиночный режим — подробный лог по каждому
                mod_id = batch[0]
                done += 1
                self.log_line.emit(t("log_downloading", cur=done, total=total, mod_id=mod_id))
                self.progress.emit(done - 1, total)
                results = self._run_batch(batch)
                if results.get(mod_id):
                    success += 1
                    self.log_line.emit(t("log_ok", cur=done, total=total, mod_id=mod_id))
                else:
                    fail += 1
                    self.log_line.emit(t("log_fail", cur=done, total=total, mod_id=mod_id))
                    self._diagnose_failure(mod_id)
            else:
                # Пакетный режим — одна сессия steamcmd на всю пачку
                first = done + 1
                last  = done + len(batch)
                self.log_line.emit(
                    f"\n📦 Пачка [{first}–{last}/{total}]: {len(batch)} модов..."
                )
                self.progress.emit(done, total)
                results = self._run_batch(batch)
                for mod_id in batch:
                    done += 1
                    if results.get(mod_id):
                        success += 1
                        self.log_line.emit(t("log_ok", cur=done, total=total, mod_id=mod_id))
                    else:
                        fail += 1
                        self.log_line.emit(t("log_fail", cur=done, total=total, mod_id=mod_id))
                        self._diagnose_failure(mod_id)
                self.progress.emit(done, total)

            queue_save(self.game_id, self.mod_ids, done)

        queue_clear()
        self.progress.emit(total, total)
        self.finished.emit(success, fail)

    def _run_batch(self, mod_ids: list) -> dict:
        """
        Запускает одну сессию steamcmd для списка модов.
        Возвращает {mod_id: True/False}.
        """
        args = ([self.steamcmd, "+login", "anonymous"] if self.anonymous
                else [self.steamcmd, "+login", self.username, self.password])
        for mid in mod_ids:
            args += ["+workshop_download_item", self.game_id, mid]
        args += ["+quit"]

        results = {mid: False for mid in mod_ids}
        try:
            flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
            proc  = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", creationflags=flags
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line: self.log_line.emit(line)
                # "Success. Downloaded item 123456789 to ..."
                if "Success. Downloaded item" in line:
                    for mid in mod_ids:
                        if mid in line:
                            results[mid] = True
                            break
            proc.wait()
        except FileNotFoundError:
            self.log_line.emit(t("log_steamcmd_missing"))
        except Exception as e:
            self.log_line.emit(t("log_error", err=e))
        return results

    def _diagnose_failure(self, mod_id: str):
        """Пытается объяснить причину ошибки через Steam API."""
        try:
            details = fetch_mod_details_batch([mod_id])
            info    = details.get(mod_id)
            if not info:
                self.log_line.emit(f"  ⚠ [{mod_id}] Мод не найден в Steam — возможно удалён")
                return
            title = info.get("title", mod_id)
            # Проверяем видимость через отдельный запрос
            r = requests.post(
                "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
                data={"itemcount": "1", "publishedfileids[0]": mod_id}, timeout=8
            )
            item = r.json()["response"]["publishedfiledetails"][0]
            result_code = item.get("result", 0)
            visibility  = item.get("visibility", 0)   # 0=public,1=friends,2=private
            banned      = item.get("banned", False)
            ban_reason  = item.get("ban_reason", "")

            if banned:
                self.log_line.emit(f"  🚫 [{title}] Мод заблокирован Valve: {ban_reason}")
            elif visibility == 2:
                self.log_line.emit(f"  🔒 [{title}] Мод приватный — автор ограничил доступ")
            elif visibility == 1:
                self.log_line.emit(f"  🔒 [{title}] Мод доступен только друзьям автора")
            elif result_code != 1:
                self.log_line.emit(f"  ⚠ [{title}] Steam вернул ошибку (code={result_code})")
            else:
                # Мод публичный — скорее всего нужна купленная игра
                self.log_line.emit(
                    f"  🔑 [{title}] Мод публичный, но требует владения игрой.\n"
                    f"     Попробуйте: Настройки → отключить анонимный режим и войти в аккаунт."
                )
        except Exception:
            pass   # диагностика не критична — молча игнорируем


# ── Воркер проверки обновлений ────────────────────────────────────────────────
class UpdateCheckWorker(QThread):
    # mod_id, title, local_ts, server_ts, status, folder_path, size_mb, missing_deps: list
    mod_result   = pyqtSignal(str, str, float, int, str, str, float, list)
    progress     = pyqtSignal(int, int)
    finished     = pyqtSignal(int, int)   # outdated, ok
    missing_deps = pyqtSignal(dict)       # {dep_id: title} — зависимости которых нет локально

    def __init__(self, mods_path: str):
        super().__init__()
        self.mods_path = mods_path

    def run(self):
        try:
            entries = []
            for e in os.scandir(self.mods_path):
                name = e.name
                if e.is_dir() and (name.isdigit() or
                   (name.endswith(DISABLED_SUFFIX) and name[:-len(DISABLED_SUFFIX)].isdigit())):
                    entries.append(e)
        except Exception:
            self.finished.emit(0, 0); return

        if not entries:
            self.finished.emit(0, 0); return

        def clean_id(name):
            return name[:-len(DISABLED_SUFFIX)] if name.endswith(DISABLED_SUFFIX) else name

        mod_ids  = [clean_id(e.name) for e in entries]
        local_ts = {clean_id(e.name): e.stat().st_mtime for e in entries}
        paths    = {clean_id(e.name): e.path for e in entries}
        local_set = set(mod_ids)
        total    = len(mod_ids)

        self.progress.emit(0, total)
        server_data = fetch_mod_details_batch(mod_ids)

        # Собираем все зависимости одним запросом
        all_missing_deps = {}
        for mid, info in server_data.items():
            for child_id in info.get("children", []):
                if child_id not in local_set and child_id not in all_missing_deps:
                    # Получаем название зависимости
                    child_info = server_data.get(child_id)
                    all_missing_deps[child_id] = child_info["title"] if child_info else child_id

        # Если есть незагруженные зависимости — уведомляем
        if all_missing_deps:
            self.missing_deps.emit(all_missing_deps)

        outdated = ok_count = 0
        for idx, mid in enumerate(mod_ids, 1):
            self.progress.emit(idx, total)
            folder   = paths.get(mid, "")
            loc_ts   = local_ts.get(mid, 0)
            size     = folder_size_mb(folder)
            srv      = server_data.get(mid)
            disabled = mod_is_disabled(folder)

            # Зависимости конкретно этого мода которых нет локально
            mod_missing = []
            if srv:
                for child_id in srv.get("children", []):
                    if child_id not in local_set:
                        child_title = all_missing_deps.get(child_id, child_id)
                        mod_missing.append((child_id, child_title))

            if disabled:
                status = "disabled"
            elif not srv or srv["time_updated"] == 0:
                status = "unknown"
            elif srv["time_updated"] > loc_ts:
                status = "outdated"; outdated += 1
            else:
                status = "ok"; ok_count += 1

            title  = srv["title"] if srv else mid
            srv_ts = srv["time_updated"] if srv else 0
            self.mod_result.emit(mid, title, loc_ts, srv_ts, status, folder, size, mod_missing)

        self.finished.emit(outdated, ok_count)


# ── GitHub-интеграция языков ──────────────────────────────────────────────────
GITHUB_REPO      = "Pushkinmazila2/WorkshopDL"
GITHUB_LANG_API  = f"https://api.github.com/repos/{GITHUB_REPO}/contents/lang"
GITHUB_LANG_RAW  = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/lang"
LANG_LOCAL_DIR   = os.path.join(MODULES_PATH, "lang")

# ── Установщик модов: GitHub ──────────────────────────────────────────────────
# Основной репозиторий с инструкциями. Может быть переопределён в настройках.
INSTALL_REPO_DEFAULT = "Pushkinmazila2/WorkshopDL"
INSTALL_PATH_DEFAULT = "install"   # папка внутри репо: install/[game_id].json
INSTALL_LOCAL_DIR    = os.path.join(MODULES_PATH, "install")

def _install_repo_url(cfg: configparser.ConfigParser = None) -> tuple[str, str]:
    """
    Возвращает (raw_base_url, api_base_url) для инструкций установки.
    Читает из cfg если передан, иначе возвращает дефолт.
    Поддерживает форматы:
      - "owner/repo"                     → github.com, папка install/
      - "owner/repo/tree/branch/folder"  → кастомная ветка и папка
      - "https://raw.githubusercontent.com/..."  → прямой raw URL
    """
    if cfg is not None:
        saved = cfg_get(cfg, "WorkshopDL", "InstallRepo", "")
        if saved:
            repo_str = saved.strip()
        else:
            repo_str = f"{INSTALL_REPO_DEFAULT}/{INSTALL_PATH_DEFAULT}"
    else:
        repo_str = f"{INSTALL_REPO_DEFAULT}/{INSTALL_PATH_DEFAULT}"

    # Прямой https URL
    if repo_str.startswith("https://"):
        raw = repo_str.rstrip("/")
        api = raw  # для прямых URL используем raw напрямую
        return raw, api

    # Разбираем "owner/repo[/tree/branch[/folder]]"
    parts = repo_str.strip("/").split("/")
    if len(parts) < 2:
        parts = [INSTALL_REPO_DEFAULT, INSTALL_PATH_DEFAULT]

    owner  = parts[0]
    repo   = parts[1]

    # Определяем ветку и папку
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

# Динамические URL — пересчитываются при загрузке настроек
GITHUB_INSTALL_RAW, GITHUB_INSTALL_API = _install_repo_url()



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
    # Сначала смотрим встроенные рядом со скриптом
    for f in os.listdir(APP_DIR):
        if f.startswith("lang_") and f.endswith(".json"):
            code = f[5:-5]   # lang_ru.json → ru
            result.append((code, lang_display_name(code), os.path.join(APP_DIR, f)))
    # Потом из папки Modules/lang/
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
        self.download_code = download_code   # если не пусто — скачать этот язык

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
            self.list_ready.emit([])   # пустой список — нет соединения

    def _download(self, code: str):
        url = f"{GITHUB_LANG_RAW}/{code}.json"
        self.dl_progress.emit(f"⬇  Загружаю {lang_display_name(code)}...")
        try:
            os.makedirs(LANG_LOCAL_DIR, exist_ok=True)
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            # Проверяем что это валидный JSON
            data = r.json()
            dest = lang_local_path(code)
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.dl_done.emit(True, dest)
        except Exception as e:
            self.dl_done.emit(False, str(e))




# ══════════════════════════════════════════════════════════════════════════════
# МОД-УСТАНОВЩИК  (v4)
# ══════════════════════════════════════════════════════════════════════════════

# ── Получение инструкции с GitHub ─────────────────────────────────────────────

def install_fetch_recipe(game_id: str, force: bool = False,
                         cfg: configparser.ConfigParser = None) -> dict | None:
    """
    Скачивает/возвращает из кеша инструкцию установки для игры.
    Файл на GitHub: <install_folder>/<game_id>.json
    Поддерживает кастомный репозиторий из настроек (cfg).
    Возвращает dict или None если инструкции нет.
    """
    os.makedirs(INSTALL_LOCAL_DIR, exist_ok=True)
    local = os.path.join(INSTALL_LOCAL_DIR, f"{game_id}.json")

    if os.path.exists(local) and not force:
        try:
            with open(local, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    raw_base, _ = _install_repo_url(cfg)
    url = f"{raw_base}/{game_id}.json"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        with open(local, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data
    except Exception:
        return None


# ── Параметрические утилиты-функции (строительные блоки декларативного DSL) ──

def _pf_find_game_folder(params: dict, ctx: dict) -> str | None:
    """
    Параметрическая функция автоматического поиска папки игры.
    params:
      candidates  — список возможных путей (поддерживает {STEAM}, {USERPROFILE}, glob-паттерны)
      registry    — список ключей реестра Windows (только Windows)
      env_hints   — список переменных окружения
    Возвращает найденный путь или None.
    """
    tpl_vars = {
        "STEAM":        _find_steam_path(),
        "USERPROFILE":  os.path.expanduser("~"),
        "APPDATA":      os.environ.get("APPDATA", ""),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
        "PROGRAMFILES": os.environ.get("ProgramFiles", "C:\\Program Files"),
        "PROGRAMFILES86": os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
    }
    tpl_vars.update(ctx.get("user_vars", {}))

    candidates = params.get("candidates", [])
    for pattern in candidates:
        try:
            expanded = pattern.format(**tpl_vars)
        except KeyError:
            expanded = pattern
        # glob
        matches = glob.glob(expanded, recursive=True)
        if matches:
            return matches[0]
        # прямой путь
        if os.path.isdir(expanded):
            return expanded

    # Реестр Windows
    if IS_WIN and params.get("registry"):
        import winreg
        for reg_path in params["registry"]:
            try:
                parts = reg_path.split("\\")
                root_map = {
                    "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
                    "HKEY_CURRENT_USER":  winreg.HKEY_CURRENT_USER,
                }
                root = root_map.get(parts[0], winreg.HKEY_LOCAL_MACHINE)
                key_path = "\\".join(parts[1:-1])
                value_name = parts[-1]
                with winreg.OpenKey(root, key_path) as k:
                    val, _ = winreg.QueryValueEx(k, value_name)
                    if os.path.isdir(str(val)):
                        return str(val)
            except Exception:
                pass

    # Переменные окружения
    for env in params.get("env_hints", []):
        val = os.environ.get(env, "")
        if val and os.path.isdir(val):
            return val

    return None


def _find_steam_path() -> str:
    """Находит корень Steam на текущей платформе."""
    if IS_WIN:
        candidates = [
            os.path.expandvars(r"%ProgramFiles(x86)%\Steam"),
            os.path.expandvars(r"%ProgramFiles%\Steam"),
            r"C:\Steam",
        ]
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\WOW6432Node\Valve\Steam") as k:
                val, _ = winreg.QueryValueEx(k, "InstallPath")
                candidates.insert(0, str(val))
        except Exception:
            pass
    elif IS_MAC:
        candidates = [os.path.expanduser("~/Library/Application Support/Steam")]
    else:
        candidates = [
            os.path.expanduser("~/.steam/steam"),
            os.path.expanduser("~/.local/share/Steam"),
        ]
    for p in candidates:
        if os.path.isdir(p):
            return p
    return ""


# ── Параметрическая функция: определение магазина и версии игры ───────────────
#
# Ключевая идея: мы не знаем откуда игра — пользователь сам указал папку
# (через вопрос GAME_PATH или find_game_folder). Детектируем только по
# файлам внутри этой папки. Никакого реестра, никаких путей.
#
GameStoreResult = dict  # {store, version, evidence, game_folder}


# Известные файлы-маркеры версии для каждого магазина.
# Структура: list of {file, format, extract, label}
# Используется _auto_detect_version и может быть переопределена в инструкции.
_STORE_VERSION_READERS = {
    "gog": [
        {
            # goggame-<id>.info — главный манифест GOG
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
            # GOG Galaxy 2.0: gameinfo файл
            "file":    "gameinfo",
            "format":  "text",
            "extract": {"line": 2},   # 3-я строка = версия
            "label":   "GOG gameinfo (строка 2)",
        },
    ],
    "epic": [
        {
            # Epic manifest внутри папки игры
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
            # steam_appid.txt — только app id, не версия игры
            # Версия через .acf манифест в steamapps/ (уровень выше)
            "file":    "../*.acf",
            "format":  "text",
            "extract": {"regex": r'"buildid"\s+"(\d+)"'},
            "label":   "Steam .acf buildid",
            "transform": "strip",
        },
    ],
    # Универсальные файлы версии — пробуем для любого магазина
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

# Файлы-маркеры принадлежности к магазину (только уникальные, не Steam)
_STORE_SIGNATURE_FILES = {
    "gog": [
        "goggame-*.info",   # почти всегда есть
        "goggame-*.id",
        "GalaxyAPI.dll",
        "Galaxy64.dll",
        "goggame.ico",
        "gog.ico",
        "gameinfo",         # GOG gameinfo без расширения
        "GalaxyCSharpGlue*.dll",
    ],
    "epic": [
        ".egstore",                         # папка
        "EOSSDK-Win64-Shipping.dll",
        "EOSSDK-Win32-Shipping.dll",
        "libEOSSDK-Linux-Shipping.so",
    ],
}


def _pf_detect_game_store(game_folder: str, params: dict, ctx: dict) -> GameStoreResult:
    """
    Определяет магазин и версию игры исключительно по файлам в папке игры.

    Пользователь сам указал папку (через вопрос GAME_PATH или find_game_folder).
    Реестр и пути не используются — работает одинаково на Win/Linux/macOS.

    Порядок:
      1. force_store в params — принудительный результат из инструкции
      2. Сканируем файлы-маркеры магазина (_STORE_SIGNATURE_FILES)
      3. Пробуем прочитать версию через _STORE_VERSION_READERS
         сначала для определённого магазина, потом _universal
      4. Дополнительные readers из params["version_readers"] (кастомные)

    params:
      force_store      — "steam"|"gog"|"epic"|"other" — не детектировать, взять как есть
      hints            — {store: ["file.dll", ...]} — доп. маркеры из инструкции
      version_readers  — список дополнительных readers (тот же формат что _STORE_VERSION_READERS)
      version_file     — краткая форма: один reader (совместимость со старым форматом)
    """
    if not game_folder or not os.path.isdir(game_folder):
        return {
            "store": "unknown", "version": "",
            "evidence": ["папка игры не найдена или не существует"],
            "game_folder": game_folder,
        }

    # ── 0. force_store ────────────────────────────────────────────────────────
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

    # ── 1. Маркеры магазина по файлам ────────────────────────────────────────
    sig_files = dict(_STORE_SIGNATURE_FILES)
    # Доп. маркеры из инструкции
    for st, files in params.get("hints", {}).items():
        sig_files.setdefault(st, []).extend(files)

    for st, patterns in sig_files.items():
        for pattern in patterns:
            # Папка (.egstore)
            if not pattern.endswith(("*", ".dll", ".so", ".ico", ".info", ".id")):
                if os.path.isdir(os.path.join(game_folder, pattern)):
                    votes[st] = votes.get(st, 0) + 5
                    evidence.append(f"папка {pattern}/")
                continue
            # Glob
            if "*" in pattern:
                matches = glob.glob(os.path.join(game_folder, pattern))
                if matches:
                    votes[st] = votes.get(st, 0) + 5
                    evidence.append(f"файл {os.path.basename(matches[0])}")
            else:
                if pattern in dir_set:
                    votes[st] = votes.get(st, 0) + 4
                    evidence.append(f"файл {pattern}")

    # ── 2. Голосование ───────────────────────────────────────────────────────
    detected = max(votes, key=votes.get) if any(v > 0 for v in votes.values()) else "other"

    # ── 3. Версия ─────────────────────────────────────────────────────────────
    version = _auto_detect_version(game_folder, detected, params, ctx)

    return {
        "store":       detected,
        "version":     version,
        "evidence":    evidence,
        "game_folder": game_folder,
        "votes":       votes,
    }


def _auto_detect_version(game_folder: str, store: str, params: dict = None, ctx: dict = None) -> str:
    """
    Пробует все известные способы прочитать версию игры из файлов в папке игры.
    Порядок: readers для конкретного store → _universal → params["version_readers"] → params["version_file"].
    """
    ctx    = ctx    or {}
    params = params or {}

    # Собираем список readers в порядке приоритета
    readers = []
    readers += _STORE_VERSION_READERS.get(store, [])
    readers += _STORE_VERSION_READERS["_universal"]
    readers += params.get("version_readers", [])

    for reader in readers:
        val = _pf_read_file_value(game_folder, reader, ctx)
        if val and val.strip():
            return val.strip()

    # Краткая форма version_file (обратная совместимость)
    if params.get("version_file"):
        val = _pf_read_file_value(game_folder, params["version_file"], ctx)
        if val:
            return val.strip()

    return ""



    """
    Параметрическая функция определения магазина/источника игры.

    ВАЖНО: WorkshopDL скачивает моды только через SteamCMD — все скачанные
    моды лежат в steamapps/workshop/content/<game_id>/<mod_id>/.
    Поэтому store=steam устанавливается автоматически через контекст ещё до
    вызова этой функции (_step_detect_store проверяет ctx["workshopdl_source"]).

    Эта функция нужна для определения того, КАК УСТАНОВЛЕНА САМА ИГРА —
    чтобы найти правильную папку назначения для мода:
      - Steam → steamapps/common/<Game>/
      - GOG   → обычно C:/GOG Games/<Game>/  или ~/.local/share/...
      - Epic  → C:/Program Files/Epic Games/<Game>/
      - other → пользователь указывает вручную

    Детектирование по приоритету:
      1. ctx["game_folder"] содержит steamapps/common → steam (надёжно)
      2. Маркер-файлы в папке игры (GOG/Epic специфичны, Steam маркеры могут
         быть в любом релизе — учитываем с меньшим весом)
      3. Характерные подпапки/.egstore/goggame-*.info
      4. Путь к папке (GOG Games, Epic Games в пути)
      5. Реестр Windows — ТОЛЬКО для GOG и Epic (Steam уже определён через путь)
      6. Linux/macOS: характерные пути GOG/Heroic/Lutris вместо реестра

    params (все опциональны):
      hints         — {store: ["marker.dll", ...]} — дополнительные маркеры
      version_file  — передаётся в _pf_read_file_value
      force_store   — принудительно задать результат ("steam"/"gog"/"epic"/"other")

    Возвращает GameStoreResult:
      store, version, evidence, game_folder
    """
    evidence: list[str] = []
    votes = {"steam": 0, "gog": 0, "epic": 0}

    def vote(count: int, msg: str, st: str):
        evidence.append(msg)
        votes[st] += count

    # ── 0. Принудительное задание магазина из инструкции ──────────────────────
    if params.get("force_store"):
        forced = params["force_store"]
        evidence.append(f"force_store={forced} (задан в инструкции)")
        version = _pf_read_file_value(game_folder, params["version_file"], ctx) \
                  if params.get("version_file") else _auto_detect_version(game_folder, forced)
        return {"store": forced, "version": version, "evidence": evidence, "game_folder": game_folder}

    if not game_folder or not os.path.isdir(game_folder):
        return {"store": "unknown", "version": "", "evidence": ["папка игры не найдена"], "game_folder": game_folder}

    norm_path = game_folder.replace("\\", "/").lower()

    # ── 1. Путь содержит steamapps/common → это Steam, сразу высокий вес ────────
    # WorkshopDL работает со Steam, и если game_folder уже указывает на
    # steamapps/common/<Game> — это 100% Steam без дальнейших проверок
    if "steamapps/common" in norm_path:
        vote(10, "путь содержит steamapps/common", "steam")

    # ── 2. Маркер-файлы ───────────────────────────────────────────────────────
    # Steam маркеры дают малый вес — steam_api.dll есть у многих пираток тоже.
    # GOG/Epic маркеры уникальны → высокий вес.
    MARKERS = {
        "steam": [
            ("steam_api.dll",        2), ("steam_api64.dll",     2),
            ("libsteam_api.so",      2), ("libsteam_api.dylib",  2),
            ("steam_appid.txt",      3),  # почти всегда Steam
            ("installscript.vdf",    2),
        ],
        "gog": [
            ("GalaxyAPI.dll",        5), ("Galaxy64.dll",        5),
            ("goggame.ico",          4), ("gog.ico",             4),
            ("Galaxy.dll",           4),
        ],
        "epic": [
            ("EOSSDK-Win64-Shipping.dll",   5),
            ("EOSSDK-Win32-Shipping.dll",   5),
            ("libEOSSDK-Linux-Shipping.so", 5),
        ],
    }
    # Дополнительные маркеры из инструкции
    for st_hint, files in params.get("hints", {}).items():
        for f in files:
            MARKERS.setdefault(st_hint, []).append((f, 4))

    try:
        dir_files = set(os.listdir(game_folder))
    except Exception:
        dir_files = set()

    for st, marker_list in MARKERS.items():
        for marker, weight in marker_list:
            if marker in dir_files:
                vote(weight, f"файл {marker}", st)

    # GOG: динамические goggame-<id>.info / .id
    for fname in dir_files:
        if fname.startswith("goggame-"):
            if fname.endswith(".info"):
                vote(5, f"файл {fname} (GOG manifest)", "gog")
            elif fname.endswith(".id"):
                vote(3, f"файл {fname} (GOG id)", "gog")
        if fname.startswith("GalaxyCSharpGlue"):
            vote(4, f"файл {fname}", "gog")

    # ── 3. Характерные подпапки и служебные файлы ─────────────────────────────
    if os.path.isdir(os.path.join(game_folder, ".egstore")):
        vote(6, ".egstore/ (Epic manifest dir)", "epic")
        egstore = os.path.join(game_folder, ".egstore")
        for fname in os.listdir(egstore):
            if fname.endswith(".mancpn"):
                vote(3, f".egstore/{fname}", "epic")
            elif fname.endswith(".item"):
                vote(4, f".egstore/{fname}", "epic")

    if os.path.isdir(os.path.join(game_folder, "__galaxy")):
        vote(5, "__galaxy/ (GOG overlay)", "gog")

    # ── 4. Путь к папке (GOG / Epic — характерные корни) ─────────────────────
    # Не даём вес Steam через путь — уже учли в п.1
    if "/gog games/" in norm_path or "\\gog games\\" in game_folder.lower():
        vote(4, "путь содержит 'GOG Games'", "gog")
    if "epic games" in norm_path:
        vote(4, "путь содержит 'Epic Games'", "epic")

    # Heroic Games Launcher (Linux/macOS) устанавливает GOG/Epic игры
    if "heroic/gog_games" in norm_path or "heroic\\gog_games" in norm_path:
        vote(6, "путь Heroic GOG", "gog")
    if "heroic/games" in norm_path or "heroic\\games" in norm_path:
        vote(4, "путь Heroic Epic", "epic")

    # Lutris (Linux) — может быть что угодно, маленький вес
    if "/lutris/" in norm_path:
        vote(1, "путь содержит lutris (неопределённый магазин)", "other")

    # ── 5а. Реестр Windows — только GOG и Epic (Steam уже ясен через путь) ────
    if IS_WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\WOW6432Node\GOG.com\Games") as k:
                # Проверяем что именно эта игра зарегистрирована
                n = winreg.QueryInfoKey(k)[0]
                for i in range(n):
                    try:
                        sub_name = winreg.EnumKey(k, i)
                        with winreg.OpenKey(k, sub_name) as sub:
                            try:
                                path_val, _ = winreg.QueryValueEx(sub, "PATH")
                                if path_val and os.path.normcase(path_val) == os.path.normcase(game_folder):
                                    vote(8, f"реестр GOG: {sub_name} PATH совпадает", "gog")
                            except Exception:
                                pass
                    except Exception:
                        break
        except Exception:
            pass

        try:
            import winreg
            # Epic: ищем в ProgramData/Epic/EpicGamesLauncher/Data/Manifests
            manifests_dir = os.path.join(
                os.environ.get("PROGRAMDATA", "C:\\ProgramData"),
                "Epic", "EpicGamesLauncher", "Data", "Manifests"
            )
            if os.path.isdir(manifests_dir):
                for fname in os.listdir(manifests_dir):
                    if fname.endswith(".item"):
                        try:
                            with open(os.path.join(manifests_dir, fname), encoding="utf-8") as f:
                                data = json.load(f)
                            install_loc = data.get("InstallLocation", "")
                            if install_loc and os.path.normcase(install_loc) == os.path.normcase(game_folder):
                                vote(8, f"Epic манифест: {fname}", "epic")
                        except Exception:
                            pass
        except Exception:
            pass

    # ── 5б. Linux/macOS: характерные пути без реестра ─────────────────────────
    else:
        # GOG через Minigalaxy или ручную установку
        home = os.path.expanduser("~")
        gog_linux_roots = [
            os.path.join(home, "GOG Games"),
            os.path.join(home, "gog"),
            "/opt/GOG Games",
        ]
        for root in gog_linux_roots:
            if norm_path.startswith(root.lower().replace("\\", "/")):
                vote(5, f"Linux GOG root: {root}", "gog")

        # Epic через Heroic — manifest файлы
        heroic_gog_manifest = os.path.join(
            home, ".config", "heroic", "gog_store", "installed.json"
        )
        heroic_epic_manifest = os.path.join(
            home, ".config", "heroic", "store", "installed.json"
        )
        for manifest_path, st in [(heroic_gog_manifest, "gog"), (heroic_epic_manifest, "epic")]:
            if os.path.isfile(manifest_path):
                try:
                    with open(manifest_path, encoding="utf-8") as f:
                        installed = json.load(f)
                    # Heroic хранит массив или dict
                    items = installed if isinstance(installed, list) else installed.values()
                    for item in items:
                        if isinstance(item, dict):
                            loc = item.get("install_path", "") or item.get("folder_name", "")
                            if loc and os.path.normcase(loc) in norm_path:
                                vote(7, f"Heroic manifest {st}: {os.path.basename(manifest_path)}", st)
                except Exception:
                    pass

        # Bottles/Wine (Linux) — снижаем уверенность, не меняем store
        if "/bottles/" in norm_path or "/.wine/" in norm_path:
            evidence.append("⚠ Wine/Bottles окружение — определение магазина менее надёжно")

    # ── 6. Финальный вердикт ──────────────────────────────────────────────────
    best_store = max(votes, key=votes.get)
    if votes[best_store] > 0:
        store = best_store
    else:
        store = "other" if evidence else "unknown"

    # ── 7. Версия ─────────────────────────────────────────────────────────────
    version = ""
    if params.get("version_file"):
        version = _pf_read_file_value(game_folder, params["version_file"], ctx) or ""
    if not version:
        version = _auto_detect_version(game_folder, store)

    return {
        "store":       store,
        "version":     version,
        "evidence":    evidence,
        "game_folder": game_folder,
        "votes":       votes,   # для отладки
    }


def _auto_detect_version(game_folder: str, store: str) -> str:
    """
    Пытается автоматически найти версию игры по характерным файлам магазина.
    Возвращает строку версии или "".
    """
    # Steam: steam_appid.txt содержит только appid, не версию.
    # Версия может быть в buildmanifest
    if store == "steam":
        # Ищем .acf манифест на уровень выше (steamapps/)
        parent = os.path.dirname(game_folder)
        for fname in os.listdir(parent) if os.path.isdir(parent) else []:
            if fname.endswith(".acf"):
                acf_path = os.path.join(parent, fname)
                try:
                    content = open(acf_path, encoding="utf-8", errors="replace").read()
                    m = re.search(r'"buildid"\s+"(\d+)"', content)
                    if m:
                        return f"build:{m.group(1)}"
                except Exception:
                    pass

    # GOG: goggame-*.info содержит версию
    if store == "gog":
        for fname in os.listdir(game_folder):
            if fname.startswith("goggame-") and fname.endswith(".info"):
                try:
                    with open(os.path.join(game_folder, fname), encoding="utf-8") as f:
                        data = json.load(f)
                    ver = data.get("gameId", "") or data.get("version", "")
                    if ver:
                        return str(ver)
                except Exception:
                    pass

    # Epic: .egstore/*.item содержит AppVersionString
    if store == "epic":
        egstore = os.path.join(game_folder, ".egstore")
        if os.path.isdir(egstore):
            for fname in os.listdir(egstore):
                if fname.endswith(".item"):
                    try:
                        with open(os.path.join(egstore, fname), encoding="utf-8") as f:
                            data = json.load(f)
                        ver = data.get("AppVersionString", "") or data.get("BuildVersion", "")
                        if ver:
                            return str(ver)
                    except Exception:
                        pass

    return ""


# ── Параметрическая функция: чтение значения из файла ─────────────────────────

def _pf_read_file_value(base_folder: str, params: dict, ctx: dict) -> str | None:
    """
    Универсальная параметрическая функция чтения значения из файла.
    Позволяет извлечь версию игры, путь, ключ конфига — что угодно.

    params:
      file      — путь к файлу (относительно base_folder или абсолютный)
                  Поддерживает шаблоны: {game_folder}, {APPDATA} и т.д.
                  Поддерживает glob: "*.info", "data/version_*.txt"
      format    — формат файла: "text" | "json" | "ini" | "binary" | "auto"
                  auto (default) — определяется по расширению
      extract   — как извлечь значение:

        Для format=text / binary:
          regex       — регулярное выражение; возвращает group(1) если есть группа
          line        — номер строки (0-based); -1 = последняя
          strip       — bool, обрезать пробелы (default True)

        Для format=json:
          path        — точечная нотация: "version", "app.build.number"
          regex       — применяется к строковому значению после извлечения

        Для format=ini:
          section     — имя секции (default DEFAULT)
          key         — имя ключа
          regex       — применяется к значению ключа

        Для format=binary:
          offset      — смещение в байтах (int или hex-строка "0x1C")
          length      — количество байт для чтения
          encoding    — кодировка строки ("utf-8", "utf-16-le", "ascii", default "utf-8")
          regex       — применяется к декодированной строке

      fallback  — значение если файл/ключ не найден
      transform — "strip" | "lower" | "upper" | "split_first:<sep>" | "split_last:<sep>"
                  преобразование результата перед возвратом

    Возвращает строку или None (если не найдено и нет fallback).
    """
    tpl_vars = {
        "game_folder":  ctx.get("game_folder", base_folder),
        "mod_folder":   ctx.get("mod_folder", ""),
        "APPDATA":      os.environ.get("APPDATA", ""),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
        "USERPROFILE":  os.path.expanduser("~"),
        **ctx.get("user_vars", {}),
    }
    fallback = params.get("fallback")

    # ── Разворачиваем путь ────────────────────────────────────────────────────
    raw_file = params.get("file", "")
    try:
        raw_file = raw_file.format(**tpl_vars)
    except KeyError:
        pass

    # Абсолютный или относительный
    if not os.path.isabs(raw_file):
        raw_file = os.path.join(base_folder, raw_file)

    # Glob
    matches = glob.glob(raw_file, recursive=True)
    filepath = matches[0] if matches else raw_file

    if not os.path.isfile(filepath):
        return fallback

    # ── Определяем формат ─────────────────────────────────────────────────────
    fmt = params.get("format", "auto")
    if fmt == "auto":
        ext = os.path.splitext(filepath)[1].lower()
        if ext in (".json",):                              fmt = "json"
        elif ext in (".ini", ".cfg", ".conf", ".toml"):    fmt = "ini"
        elif ext in (".exe", ".dll", ".bin", ".pak"):      fmt = "binary"
        else:                                              fmt = "text"

    extract = params.get("extract", {})
    result  = None

    # ── TEXT ──────────────────────────────────────────────────────────────────
    if fmt == "text":
        try:
            enc  = extract.get("encoding", "utf-8")
            text = open(filepath, encoding=enc, errors="replace").read()
        except Exception:
            return fallback

        regex = extract.get("regex")
        if regex:
            m = re.search(regex, text, re.MULTILINE)
            result = m.group(1) if m and m.lastindex else (m.group(0) if m else None)
        else:
            lines = text.splitlines()
            line_no = extract.get("line", 0)
            if lines:
                result = lines[line_no] if abs(line_no) < len(lines) else lines[-1]
            else:
                result = text

    # ── JSON ──────────────────────────────────────────────────────────────────
    elif fmt == "json":
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return fallback

        path_keys = extract.get("path", "").split(".")
        node = data
        for k in path_keys:
            if not k:
                continue
            if isinstance(node, dict):
                node = node.get(k)
            elif isinstance(node, list):
                try:
                    node = node[int(k)]
                except (ValueError, IndexError):
                    node = None
            else:
                node = None
            if node is None:
                return fallback

        result = str(node) if node is not None else None
        regex = extract.get("regex")
        if result and regex:
            m = re.search(regex, result)
            result = m.group(1) if m and m.lastindex else (m.group(0) if m else result)

    # ── INI ───────────────────────────────────────────────────────────────────
    elif fmt == "ini":
        try:
            cfg = configparser.ConfigParser(strict=False)
            cfg.optionxform = str
            cfg.read(filepath, encoding="utf-8")
        except Exception:
            return fallback

        section = extract.get("section", "DEFAULT")
        key     = extract.get("key", "")
        try:
            result = cfg.get(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

        regex = extract.get("regex")
        if result and regex:
            m = re.search(regex, result)
            result = m.group(1) if m and m.lastindex else (m.group(0) if m else result)

    # ── BINARY ────────────────────────────────────────────────────────────────
    elif fmt == "binary":
        try:
            offset_raw = extract.get("offset", 0)
            offset = int(offset_raw, 16) if isinstance(offset_raw, str) and offset_raw.startswith("0x") \
                     else int(offset_raw)
            length   = int(extract.get("length", 256))
            encoding = extract.get("encoding", "utf-8")

            with open(filepath, "rb") as f:
                f.seek(offset)
                raw_bytes = f.read(length)

            # Декодируем — обрезаем по нулевому байту
            text = raw_bytes.split(b"\x00")[0].decode(encoding, errors="replace")
            regex = extract.get("regex")
            if regex:
                m = re.search(regex, text)
                result = m.group(1) if m and m.lastindex else (m.group(0) if m else None)
            else:
                result = text.strip()
        except Exception:
            return fallback

    # ── Трансформация ─────────────────────────────────────────────────────────
    if result is None:
        return fallback
    result = str(result)
    if extract.get("strip", True):
        result = result.strip()

    transform = params.get("transform", "")
    if transform == "strip":
        result = result.strip()
    elif transform == "lower":
        result = result.lower()
    elif transform == "upper":
        result = result.upper()
    elif transform.startswith("split_first:"):
        sep = transform[12:] or "."
        result = result.split(sep)[0]
    elif transform.startswith("split_last:"):
        sep = transform[11:] or "."
        result = result.split(sep)[-1]

    return result or fallback


def _pf_smart_copy(src_root: str, dst_root: str, params: dict, log_cb) -> list[str]:
    """
    Функция умного копирования и распаковки (основной Action).
    params:
      files     — список {from, to, overwrite, extract}
                  from: паттерн glob относительно src_root
                  to:   путь относительно dst_root
                  overwrite: bool (default True)
                  extract: bool — распаковать архив (zip/7z)
      flatten   — bool: игнорировать структуру папок при копировании
    Возвращает список скопированных файлов.
    """
    copied = []
    flatten = params.get("flatten", False)

    for rule in params.get("files", []):
        pattern  = rule.get("from", "**")
        rel_dst  = rule.get("to", ".")
        overwrite = rule.get("overwrite", True)
        do_extract = rule.get("extract", False)

        # Ищем файлы
        full_pattern = os.path.join(src_root, pattern)
        matches = glob.glob(full_pattern, recursive=True)
        if not matches:
            # Попробуем fnmatch
            matches = [
                os.path.join(dp, f)
                for dp, _, files in os.walk(src_root)
                for f in files
                if fnmatch.fnmatch(f, os.path.basename(pattern))
            ]

        abs_dst = os.path.join(dst_root, rel_dst)
        os.makedirs(abs_dst, exist_ok=True)

        for src_file in matches:
            if os.path.isdir(src_file):
                continue
            if flatten:
                dst_file = os.path.join(abs_dst, os.path.basename(src_file))
            else:
                rel = os.path.relpath(src_file, src_root)
                dst_file = os.path.join(abs_dst, rel)
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)

            if os.path.exists(dst_file) and not overwrite:
                log_cb(f"  ⏭ пропуск (уже есть): {os.path.basename(dst_file)}")
                continue

            if do_extract and src_file.lower().endswith(".zip"):
                log_cb(f"  📦 распаковка: {os.path.basename(src_file)} → {rel_dst}")
                try:
                    with zipfile.ZipFile(src_file, "r") as z:
                        z.extractall(abs_dst)
                    copied.append(abs_dst)
                except Exception as e:
                    log_cb(f"  ❌ ошибка распаковки: {e}")
            else:
                try:
                    shutil.copy2(src_file, dst_file)
                    copied.append(dst_file)
                    log_cb(f"  ✅ скопировано: {os.path.relpath(dst_file, dst_root)}")
                except Exception as e:
                    log_cb(f"  ❌ ошибка копирования {os.path.basename(src_file)}: {e}")
    return copied


def _pf_safe_eval_condition(condition: str, ctx: dict) -> bool:
    """
    Расширенный вычислитель условий (when).

    Поддерживает логические выражения с &&, ||, !, скобки:
      "(store == 'steam' || store == 'gog') && version != ''"
      "file_exists('{game_folder}/game.exe') && platform == 'win'"
      "!file_exists('{game_folder}/mod_list.xml')"

    Атомарные выражения:
      store == 'steam'              — сравнение переменной ctx
      version != ''                 — неравенство
      version >= '1.5'              — лексикографическое сравнение
      platform == 'win'|'linux'|'mac'
      file_exists('path')           — файл существует
      dir_exists('path')            — папка существует
      file_contains('path','regex') — файл содержит паттерн
      disk_free('path') > 1000      — свободное место в МБ
      env_set('VAR')                — переменная окружения задана
      env('VAR') == 'value'         — значение переменной окружения
      var_set('name')               — переменная ctx задана и не пуста
      True / False                  — литералы
    """
    if not condition:
        return True

    cond = condition.strip()

    # Подстановка шаблонов {var} из ctx
    tpl = _build_tpl(ctx)
    try:
        cond = cond.format(**tpl)
    except (KeyError, ValueError):
        pass

    return _eval_expr(cond, ctx)


def _build_tpl(ctx: dict) -> dict:
    """Собирает словарь для подстановки {var} в when-условиях из ctx."""
    tpl = {
        # Системные
        "USERPROFILE":    ctx.get("USERPROFILE",  os.path.expanduser("~")),
        "APPDATA":        ctx.get("APPDATA",      os.environ.get("APPDATA", "")),
        "LOCALAPPDATA":   ctx.get("LOCALAPPDATA", os.environ.get("LOCALAPPDATA", "")),
        "PROGRAMFILES":   ctx.get("PROGRAMFILES", os.environ.get("ProgramFiles", "")),
        "PROGRAMFILES86": ctx.get("PROGRAMFILES86", os.environ.get("ProgramFiles(x86)", "")),
        "STEAM":          ctx.get("STEAM", ""),

        # Идентификаторы
        "game_id":   ctx.get("game_id",   ""),
        "mod_id":    ctx.get("mod_id",    ""),
        "game_name": ctx.get("game_name", ""),
        # Счётчики модов — доступны в when-условиях
        "mod_index":    ctx.get("mod_index",    "0"),
        "mod_number":   ctx.get("mod_number",   "1"),
        "mod_total":    ctx.get("mod_total",    "1"),
        "mod_count":    ctx.get("mod_count",    "1"),
        "mod_is_first": ctx.get("mod_is_first", "true"),
        "mod_is_last":  ctx.get("mod_is_last",  "true"),

        # Папки
        "game_folder":    ctx.get("game_folder",    ""),
        "mod_folder":     ctx.get("mod_folder",     ""),
        "content_folder": ctx.get("content_folder", ""),
        "steamcmd_root":  ctx.get("steamcmd_root",  ""),

        # Магазин и версия
        "store":    ctx.get("store",    ""),
        "version":  ctx.get("version",  ""),
        "platform": ctx.get("platform", ""),

        "is_win":   ctx.get("is_win",   str(IS_WIN).lower()),
        "is_linux": ctx.get("is_linux", str(IS_LINUX).lower()),
        "is_mac":   ctx.get("is_mac",   str(IS_MAC).lower()),
    }
    tpl.update(ctx.get("user_vars", {}))
    return tpl


def _eval_expr(expr: str, ctx: dict) -> bool:
    """Рекурсивный парсер логических выражений."""
    expr = expr.strip()
    if not expr:
        return True

    # ── Скобки — рекурсия ────────────────────────────────────────────────────
    # Ищем внешние скобки (не вложенные)
    if expr.startswith("("):
        depth = 0
        for i, ch in enumerate(expr):
            if ch == "(": depth += 1
            elif ch == ")": depth -= 1
            if depth == 0:
                inner  = expr[1:i]
                rest   = expr[i+1:].strip()
                result = _eval_expr(inner, ctx)
                if not rest:
                    return result
                # Продолжение: && или ||
                if rest.startswith("&&"):
                    return result and _eval_expr(rest[2:].strip(), ctx)
                if rest.startswith("||"):
                    return result or  _eval_expr(rest[2:].strip(), ctx)
                return result

    # ── Отрицание ─────────────────────────────────────────────────────────────
    if expr.startswith("!") and not expr.startswith("!="):
        return not _eval_expr(expr[1:].strip(), ctx)

    # ── || (OR) — ищем вне скобок и кавычек ──────────────────────────────────
    idx = _find_operator(expr, "||")
    if idx >= 0:
        return _eval_expr(expr[:idx], ctx) or _eval_expr(expr[idx+2:], ctx)

    # ── && (AND) ──────────────────────────────────────────────────────────────
    idx = _find_operator(expr, "&&")
    if idx >= 0:
        return _eval_expr(expr[:idx], ctx) and _eval_expr(expr[idx+2:], ctx)

    # ── Атомарные выражения ───────────────────────────────────────────────────
    return _eval_atom(expr.strip(), ctx)


def _find_operator(expr: str, op: str) -> int:
    """Ищет оператор op вне скобок и строковых литералов."""
    depth = 0
    in_str = None
    i = 0
    while i < len(expr):
        ch = expr[i]
        if in_str:
            if ch == in_str:
                in_str = None
        elif ch in ('"', "'"):
            in_str = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and expr[i:i+len(op)] == op:
            return i
        i += 1
    return -1


def _eval_atom(atom: str, ctx: dict) -> bool:
    """
    Вычисляет одно атомарное условие.
    """
    atom = atom.strip()
    vars_ = ctx.get("user_vars", {})

    # ── Функции ───────────────────────────────────────────────────────────────
    # file_exists('path')
    m = re.match(r"^file_exists\(['\"](.*?)['\"]\)$", atom)
    if m:
        return os.path.isfile(m.group(1))

    # dir_exists('path')
    m = re.match(r"^dir_exists\(['\"](.*?)['\"]\)$", atom)
    if m:
        return os.path.isdir(m.group(1))

    # file_contains('path', 'regex')
    m = re.match(r"^file_contains\(['\"](.*?)['\"],\s*['\"](.*?)['\"]\)$", atom)
    if m:
        fpath, pattern = m.group(1), m.group(2)
        try:
            content = open(fpath, encoding="utf-8", errors="replace").read()
            return bool(re.search(pattern, content))
        except Exception:
            return False

    # disk_free('path') > N  или  disk_free('path') >= N
    m = re.match(r"^disk_free\(['\"](.*?)['\"]\)\s*(>=|>|==|<|<=)\s*(\d+)$", atom)
    if m:
        path_, op_, mb_ = m.group(1), m.group(2), int(m.group(3))
        try:
            free_mb = shutil.disk_usage(path_).free // (1024 * 1024)
            return _compare(free_mb, op_, mb_)
        except Exception:
            return False

    # env_set('VAR')
    m = re.match(r"^env_set\(['\"](.*?)['\"]\)$", atom)
    if m:
        return bool(os.environ.get(m.group(1), ""))

    # env('VAR') == 'value'
    m = re.match(r"^env\(['\"](.*?)['\"]\)\s*(==|!=)\s*['\"]?(.*?)['\"]?$", atom)
    if m:
        env_val = os.environ.get(m.group(1), "")
        return _compare_str(env_val, m.group(2), m.group(3))

    # var_set('name')
    m = re.match(r"^var_set\(['\"](.*?)['\"]\)$", atom)
    if m:
        return bool(vars_.get(m.group(1), ""))

    # platform == 'win'|'linux'|'mac'
    m = re.match(r"^platform\s*(==|!=)\s*['\"](\w+)['\"]$", atom)
    if m:
        op_, plat = m.group(1), m.group(2).lower()
        current = "win" if IS_WIN else ("mac" if IS_MAC else "linux")
        return _compare_str(current, op_, plat)

    # ── Сравнения переменных  var == 'value' / var != '' / var >= '1.2' ───────
    m = re.match(r"^(\w+)\s*(==|!=|>=|<=|>|<)\s*['\"]?(.*?)['\"]?$", atom)
    if m:
        var_name, op_, rhs = m.group(1), m.group(2), m.group(3)
        # Ищем в user_vars, потом в ctx
        lhs = str(vars_.get(var_name, ctx.get(var_name, "")))
        return _compare_str(lhs, op_, rhs)

    # Литералы True / False / "true" / "false"
    if atom.lower() in ("true", "1", "yes"):  return True
    if atom.lower() in ("false", "0", "no"):  return False

    # Непустая строка = True
    return bool(atom)


def _compare(a, op: str, b) -> bool:
    if op == "==": return a == b
    if op == "!=": return a != b
    if op == ">":  return a > b
    if op == ">=": return a >= b
    if op == "<":  return a < b
    if op == "<=": return a <= b
    return False

def _compare_str(a: str, op: str, b: str) -> bool:
    return _compare(a, op, b)



def _pf_patch_ini(filepath: str, patches: list, log_cb) -> bool:
    """
    Функция для работы с INI файлами.
    patches: [{section, key, value, create_if_missing}]
    """
    if not os.path.isfile(filepath):
        log_cb(f"  ⚠ INI не найден: {filepath}")
        return False
    cfg = configparser.ConfigParser(strict=False)
    cfg.optionxform = str   # сохраняем регистр
    cfg.read(filepath, encoding="utf-8")
    for patch in patches:
        sec = patch.get("section", "DEFAULT")
        key = patch.get("key", "")
        val = str(patch.get("value", ""))
        create = patch.get("create_if_missing", True)
        if sec not in cfg:
            if create:
                cfg[sec] = {}
            else:
                log_cb(f"  ⚠ секция [{sec}] не найдена, пропуск")
                continue
        cfg[sec][key] = val
        log_cb(f"  ✏ INI [{sec}] {key} = {val}")
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            cfg.write(f)
        return True
    except Exception as e:
        log_cb(f"  ❌ ошибка записи INI: {e}")
        return False


def _pf_patch_json(filepath: str, patches: list, log_cb) -> bool:
    """
    Функция для работы с JSON конфигами.
    patches: [{path: "key.subkey.subsubkey", value: ..., create_if_missing: true}]
    path поддерживает точечную нотацию.
    """
    if not os.path.isfile(filepath):
        log_cb(f"  ⚠ JSON не найден: {filepath}")
        return False
    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log_cb(f"  ❌ ошибка чтения JSON: {e}")
        return False

    for patch in patches:
        key_path = patch.get("path", "")
        value    = patch.get("value")
        create   = patch.get("create_if_missing", True)
        keys     = key_path.split(".")
        node     = data
        try:
            for k in keys[:-1]:
                if k not in node and create:
                    node[k] = {}
                node = node[k]
            node[keys[-1]] = value
            log_cb(f"  ✏ JSON {key_path} = {json.dumps(value, ensure_ascii=False)}")
        except Exception as e:
            log_cb(f"  ⚠ не удалось применить патч {key_path}: {e}")

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log_cb(f"  ❌ ошибка записи JSON: {e}")
        return False


# ── Диалог вопросов к пользователю ────────────────────────────────────────────

class InstallQuestionsDialog(QDialog):
    """
    Диалог для задания вопросов пользователю в процессе установки.

    Поддерживает типы вопросов:
      text     — текстовый ввод (с опциональной кнопкой обзора файла/папки)
      select   — выпадающий список
      checkbox — флажок

    Поддерживает подстановку {переменных} контекста во всех полях:
      default, placeholder, label, hint, items[].label
    Это позволяет показывать пользователю уже известные значения
    (например папку игры из истории) как значение по умолчанию.
    """
    def __init__(self, questions: list, mod_title: str, total_mods: int,
                 ctx: dict = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"⚙ Установка: {mod_title}")
        self.setMinimumWidth(500)
        self._answers      = {}
        self._apply_to_all = False
        self._ctx          = ctx or {}

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        header = QLabel(f"<b>Настройка установки:</b><br>{mod_title}")
        header.setWordWrap(True)
        lay.addWidget(header)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); lay.addWidget(sep)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); inner_lay = QVBoxLayout(inner); inner_lay.setSpacing(10)

        self._widgets = {}
        for q in questions:
            qid   = q.get("id", "")
            qtype = q.get("type", "text")

            # ── Подстановка переменных во все строковые поля ─────────────────
            label       = self._render(q.get("label",   qid))
            hint        = self._render(q.get("hint",    ""))
            default     = self._render(str(q.get("default", "")))
            placeholder = self._render(q.get("placeholder", ""))

            grp = QGroupBox(label)
            gl  = QVBoxLayout(grp)
            gl.setSpacing(4)

            # ── text ──────────────────────────────────────────────────────────
            if qtype == "text":
                row_w = QWidget(); row_l = QHBoxLayout(row_w); row_l.setContentsMargins(0,0,0,0)

                w = QLineEdit()
                w.setText(default)
                w.setPlaceholderText(placeholder or self._render(
                    q.get("placeholder_hint", "")
                ))
                row_l.addWidget(w)

                # Кнопка обзора файла/папки
                browse = q.get("browse", "")   # "folder" | "file" | ""
                if browse:
                    btn_browse = QPushButton("📂" if browse == "folder" else "📄")
                    btn_browse.setFixedWidth(32)
                    btn_browse.setToolTip(
                        "Выбрать папку" if browse == "folder" else "Выбрать файл"
                    )
                    filter_str = q.get("browse_filter", "Все файлы (*)")

                    def _make_browse(widget, btype, flt):
                        def _do():
                            if btype == "folder":
                                path = QFileDialog.getExistingDirectory(
                                    self, "Выберите папку", widget.text() or ""
                                )
                            else:
                                path, _ = QFileDialog.getOpenFileName(
                                    self, "Выберите файл", widget.text() or "", flt
                                )
                            if path:
                                widget.setText(path)
                        return _do

                    btn_browse.clicked.connect(_make_browse(w, browse, filter_str))
                    row_l.addWidget(btn_browse)

                # Если есть значение из истории — показываем подсказку
                history_val = self._ctx.get("game_folder", "") if qid == "GAME_PATH" else ""
                if not history_val:
                    history_val = self._ctx.get("user_vars", {}).get(qid, "")
                if history_val and history_val != default:
                    lbl_hist = QLabel(
                        f"<span style='color:#5c9;font-size:11px'>"
                        f"📂 Из истории: <code>{history_val}</code>"
                        f"</span>"
                    )
                    lbl_hist.setWordWrap(True)
                    lbl_hist.setCursor(Qt.PointingHandCursor)
                    lbl_hist.mousePressEvent = lambda e, v=history_val, ww=w: ww.setText(v)
                    lbl_hist.setToolTip("Нажмите чтобы подставить")
                    gl.addWidget(lbl_hist)

                gl.addWidget(row_w)
                self._widgets[qid] = ("text", w)

            # ── select ────────────────────────────────────────────────────────
            elif qtype == "select":
                w = QComboBox()
                items = q.get("items", [])
                for it in items:
                    if isinstance(it, dict):
                        item_label = self._render(it.get("label", str(it.get("value", ""))))
                        item_value = self._render(str(it.get("value", "")))
                        w.addItem(item_label, userData=item_value)
                    else:
                        rendered = self._render(str(it))
                        w.addItem(rendered, userData=it)
                # Выбираем default (поддерживает подстановку)
                rendered_default = self._render(str(q.get("default", "")))
                for i in range(w.count()):
                    if str(w.itemData(i)) == rendered_default:
                        w.setCurrentIndex(i); break
                gl.addWidget(w)
                self._widgets[qid] = ("select", w)

            # ── checkbox ──────────────────────────────────────────────────────
            elif qtype == "checkbox":
                chk_label = self._render(q.get("checkbox_label", "Включить"))
                w = QCheckBox(chk_label)
                # default может быть "true"/"false" строкой из контекста
                raw_default = q.get("default", False)
                if isinstance(raw_default, str):
                    checked = raw_default.lower() in ("true", "1", "yes")
                else:
                    checked = bool(raw_default)
                w.setChecked(checked)
                gl.addWidget(w)
                self._widgets[qid] = ("checkbox", w)

            # ── hint ──────────────────────────────────────────────────────────
            if hint:
                lbl_hint = QLabel(f"<i style='color:#888;font-size:11px'>{hint}</i>")
                lbl_hint.setWordWrap(True)
                gl.addWidget(lbl_hint)

            inner_lay.addWidget(grp)

        inner_lay.addStretch()
        scroll.setWidget(inner)
        lay.addWidget(scroll)

        # «Применить ко всем модам»
        if total_mods > 1:
            self._chk_all = QCheckBox(f"Применить эти настройки ко всем {total_mods} модам")
            lay.addWidget(self._chk_all)
        else:
            self._chk_all = None

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("✅ Применить")
        btns.button(QDialogButtonBox.Cancel).setText("Отмена")
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _render(self, text: str) -> str:
        """Подставляет {переменные} контекста в строку."""
        if not text or "{" not in text:
            return text
        tpl = _build_tpl(self._ctx)
        try:
            return text.format(**tpl)
        except (KeyError, ValueError):
            # Частичная подстановка — заменяем только известные
            for k, v in tpl.items():
                text = text.replace(f"{{{k}}}", str(v))
            return text

    def _accept(self):
        for qid, (qtype, widget) in self._widgets.items():
            if qtype == "text":
                self._answers[qid] = widget.text()
            elif qtype == "select":
                self._answers[qid] = widget.currentData()
            elif qtype == "checkbox":
                self._answers[qid] = widget.isChecked()
        if self._chk_all:
            self._apply_to_all = self._chk_all.isChecked()
        self.accept()

    def get_answers(self) -> dict:
        return self._answers

    def apply_to_all(self) -> bool:
        return self._apply_to_all


# ── Движок установки одного мода ──────────────────────────────────────────────


def _pf_patch_xml(filepath: str, patches: list, log_cb) -> bool:
    """
    Функция для работы с XML конфигами.
    patches: [{xpath, attribute, value, create_if_missing, action}]
      xpath            — XPath выражение для поиска элемента
      attribute        — атрибут для изменения (если пустой — меняем text элемента)
      value            — новое значение
      create_if_missing — bool (default False)
      action           — "set"(default) | "delete" | "append_child"
                         append_child: value содержит XML-строку нового дочернего элемента
    """
    try:
        import xml.etree.ElementTree as ET
    except ImportError:
        log_cb("  ❌ xml.etree.ElementTree недоступен")
        return False

    if not os.path.isfile(filepath):
        log_cb(f"  ⚠ XML не найден: {filepath}")
        return False
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
    except Exception as e:
        log_cb(f"  ❌ Ошибка парсинга XML: {e}")
        return False

    for patch in patches:
        xpath   = patch.get("xpath", "")
        attr    = patch.get("attribute", "")
        value   = str(patch.get("value", ""))
        action  = patch.get("action", "set")
        create  = patch.get("create_if_missing", False)

        elements = root.findall(xpath)
        if not elements:
            if create and action == "set":
                # Создаём элемент по простому пути (без предикатов)
                parts = xpath.strip("./").split("/")
                node = root
                for part in parts:
                    child = node.find(part)
                    if child is None:
                        import xml.etree.ElementTree as ET2
                        child = ET2.SubElement(node, part)
                    node = child
                elements = [node]
            else:
                log_cb(f"  ⚠ XML xpath не найден: {xpath}")
                continue

        for el in elements:
            if action == "set":
                if attr:
                    el.set(attr, value)
                    log_cb(f"  ✏ XML {xpath} @{attr} = {value}")
                else:
                    el.text = value
                    log_cb(f"  ✏ XML {xpath} text = {value}")
            elif action == "delete":
                parent = root.find(xpath + "/..")
                if parent is not None:
                    parent.remove(el)
                    log_cb(f"  🗑 XML удалён элемент {xpath}")
            elif action == "append_child":
                try:
                    import xml.etree.ElementTree as ET3
                    child = ET3.fromstring(value)
                    el.append(child)
                    log_cb(f"  ➕ XML добавлен дочерний элемент в {xpath}")
                except Exception as e:
                    log_cb(f"  ❌ XML append_child: {e}")

    try:
        # Сохраняем с сохранением отступов
        ET.indent(tree, space="  ")
        tree.write(filepath, encoding="unicode", xml_declaration=True)
        return True
    except AttributeError:
        # ET.indent появился в Python 3.9
        tree.write(filepath, encoding="unicode", xml_declaration=True)
        return True
    except Exception as e:
        log_cb(f"  ❌ Ошибка записи XML: {e}")
        return False


def _pf_patch_cfg(filepath: str, patches: list, log_cb) -> bool:
    """
    Функция для работы с CFG/простыми конфигами формата 'key = value' или 'key value'.
    Поддерживает однострочные комментарии // и #.
    patches: [{key, value, separator, create_if_missing, comment}]
      key              — имя ключа
      value            — новое значение
      separator        — разделитель " = " (default) | " " | ":"
      create_if_missing — bool (default True): добавить если нет
      comment          — строка комментария над строкой (опционально)
      section          — для CFG с секциями [Section] (опционально)
    """
    if not os.path.isfile(filepath):
        log_cb(f"  ⚠ CFG не найден: {filepath}")
        return False
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        log_cb(f"  ❌ Ошибка чтения CFG: {e}")
        return False

    for patch in patches:
        key       = patch.get("key", "")
        value     = str(patch.get("value", ""))
        sep       = patch.get("separator", " = ")
        create    = patch.get("create_if_missing", True)
        section   = patch.get("section", "")
        comment   = patch.get("comment", "")
        found     = False
        in_section = not section  # если секция не задана — считаем что сразу внутри

        for idx, line in enumerate(lines):
            stripped = line.strip()
            # Смена секции
            if stripped.startswith("[") and stripped.endswith("]"):
                in_section = (stripped[1:-1].strip() == section)
                continue
            if not in_section:
                continue
            # Пропуск комментариев
            if stripped.startswith(("#", "//")):
                continue
            # Ищем ключ (любой разделитель = / : / пробел)
            m = re.match(rf"^({re.escape(key)})\s*[=: ]\s*(.*)$", stripped)
            if m:
                new_line = f"{key}{sep}{value}\n"
                lines[idx] = new_line
                log_cb(f"  ✏ CFG {key}{sep}{value}")
                found = True
                break

        if not found and create:
            if comment:
                lines.append(f"# {comment}\n")
            lines.append(f"{key}{sep}{value}\n")
            log_cb(f"  ➕ CFG добавлен {key}{sep}{value}")

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception as e:
        log_cb(f"  ❌ Ошибка записи CFG: {e}")
        return False


def _pf_rename_files(base_folder: str, rules: list, log_cb) -> int:
    """
    Функция переименования файлов по regex.
    rules: [{pattern, replacement, glob, recursive, dry_run}]
      glob        — паттерн файлов для поиска (default "**/*")
      pattern     — regex для поиска в имени файла
      replacement — строка замены (поддерживает \\1, \\2 — группы)
      recursive   — bool (default True)
      dry_run     — bool: только показать что будет переименовано
    Возвращает количество переименованных файлов.
    """
    renamed = 0
    for rule in rules:
        file_glob   = rule.get("glob", "**/*")
        pattern     = rule.get("pattern", "")
        replacement = rule.get("replacement", "")
        recursive   = rule.get("recursive", True)
        dry_run     = rule.get("dry_run", False)

        if not pattern:
            log_cb("  ⚠ rename: не задан pattern")
            continue

        matches = glob.glob(os.path.join(base_folder, file_glob), recursive=recursive)
        for fpath in matches:
            if os.path.isdir(fpath):
                continue
            dirname  = os.path.dirname(fpath)
            basename = os.path.basename(fpath)
            new_name = re.sub(pattern, replacement, basename)
            if new_name == basename:
                continue
            new_path = os.path.join(dirname, new_name)
            if dry_run:
                log_cb(f"  🔍 [dry_run] переименую: {basename} → {new_name}")
            else:
                try:
                    os.rename(fpath, new_path)
                    log_cb(f"  📝 переименован: {basename} → {new_name}")
                    renamed += 1
                except Exception as e:
                    log_cb(f"  ❌ ошибка переименования {basename}: {e}")
    return renamed


def _pf_delete_files(base_folder: str, rules: list, log_cb) -> int:
    """
    Функция удаления файлов и папок.
    rules: [{glob, recursive, missing_ok, dry_run}]
      glob        — паттерн (glob) относительно base_folder
      recursive   — bool: удалять папки рекурсивно (default False)
      missing_ok  — bool: не ошибаться если нет (default True)
      dry_run     — bool: только показать
    Возвращает количество удалённых объектов.
    """
    deleted = 0
    for rule in rules:
        pattern    = rule.get("glob", "")
        recursive  = rule.get("recursive", False)
        missing_ok = rule.get("missing_ok", True)
        dry_run    = rule.get("dry_run", False)

        if not pattern:
            log_cb("  ⚠ delete: не задан glob")
            continue

        matches = glob.glob(os.path.join(base_folder, pattern), recursive=True)
        if not matches and not missing_ok:
            log_cb(f"  ⚠ delete: не найдено файлов по паттерну {pattern}")
            continue

        for fpath in matches:
            if dry_run:
                log_cb(f"  🔍 [dry_run] удалю: {os.path.relpath(fpath, base_folder)}")
                continue
            try:
                if os.path.isdir(fpath):
                    if recursive:
                        shutil.rmtree(fpath)
                        log_cb(f"  🗑 удалена папка: {os.path.relpath(fpath, base_folder)}")
                        deleted += 1
                    else:
                        log_cb(f"  ⚠ {fpath} — папка, укажите recursive=true")
                else:
                    os.remove(fpath)
                    log_cb(f"  🗑 удалён файл: {os.path.relpath(fpath, base_folder)}")
                    deleted += 1
            except Exception as e:
                log_cb(f"  ❌ ошибка удаления {os.path.basename(fpath)}: {e}")
    return deleted


def _pf_check_disk(path: str, required_mb: int) -> dict:
    """
    Проверка свободного места на диске.
    Возвращает: {ok, free_mb, required_mb, path}
    """
    try:
        usage   = shutil.disk_usage(path)
        free_mb = usage.free // (1024 * 1024)
        return {"ok": free_mb >= required_mb, "free_mb": free_mb, "required_mb": required_mb, "path": path}
    except Exception as e:
        return {"ok": False, "free_mb": 0, "required_mb": required_mb, "path": path, "error": str(e)}


def _pf_backup_file(filepath: str, log_cb, suffix: str = ".bak", keep: int = 3) -> str | None:
    """
    Создаёт резервную копию файла.
      suffix — расширение бэкапа (default .bak)
      keep   — сколько версий хранить (default 3): file.bak, file.bak.1, file.bak.2
    Возвращает путь к созданному бэкапу или None при ошибке.
    """
    if not os.path.isfile(filepath):
        log_cb(f"  ⚠ backup: файл не найден: {filepath}")
        return None

    base = filepath + suffix
    # Ротация: .bak.2 ← .bak.1 ← .bak ← оригинал
    for i in range(keep - 1, 0, -1):
        old = f"{base}.{i}"
        new = f"{base}.{i+1}" if i + 1 < keep else None
        if os.path.exists(old):
            if new:
                try:
                    shutil.copy2(old, new)
                except Exception:
                    pass
            try:
                os.remove(old)
            except Exception:
                pass
    if os.path.exists(base):
        try:
            shutil.copy2(base, base + ".1")
            os.remove(base)
        except Exception:
            pass

    try:
        shutil.copy2(filepath, base)
        log_cb(f"  💾 бэкап создан: {os.path.basename(base)}")
        return base
    except Exception as e:
        log_cb(f"  ❌ ошибка создания бэкапа: {e}")
        return None


class ModInstaller:
    """
    Выполняет установку одного мода согласно инструкции (recipe).
    Поддерживает оба формата:
      - Параметрический (declarative): только JSON-steps
      - Гибридный: JSON-steps + запуск внешнего Python-плагина
    """

    STEP_HANDLERS = {
        # Поиск и определение
        "find_game_folder": "_step_find_game_folder",
        "detect_store":     "_step_detect_store",
        "read_file":        "_step_read_file",
        # Управление переменными и счётчики
        "set_var":          "_step_set_var",
        "increment":        "_step_increment",
        # Файловые операции
        "copy":             "_step_copy",
        "rename":           "_step_rename",
        "delete":           "_step_delete",
        "backup":           "_step_backup",
        # Патчи конфигов
        "patch_ini":        "_step_patch_ini",
        "patch_json":       "_step_patch_json",
        "patch_xml":        "_step_patch_xml",
        "patch_cfg":        "_step_patch_cfg",
        # Системные
        "check_disk":       "_step_check_disk",
        # Гибридный режим
        "plugin":           "_step_plugin",
    }

    # Псевдо-действия управления потоком — обрабатываются в run() напрямую
    _FLOW_ACTIONS = {"if", "else", "elif", "end_if", "for", "end_for", "while", "end_while"}

    def __init__(self, recipe: dict, mod_folder: str, log_cb,
                 user_answers: dict = None, extra_ctx: dict = None):
        self.recipe       = recipe
        self.mod_folder   = mod_folder
        self.log          = log_cb

        # ── Базовый контекст ──────────────────────────────────────────────────
        # Всё что может понадобиться в шагах и conditions
        self.ctx = {
            # Источник
            "workshopdl_source": True,      # мод всегда из SteamCMD Workshop

            # Папки — заполняются шагами или из extra_ctx
            "game_folder":   "",
            "mod_folder":    mod_folder,
            "steamcmd_root": "",            # корень steamcmd (родитель steamapps/)

            # Идентификаторы
            "game_id":   "",               # Steam App ID игры
            "mod_id":    "",               # Steam Workshop ID текущего мода
            "game_name": "",               # человекочитаемое название игры

            # Магазин и версия (заполняются detect_store)
            "store":   "",
            "version": "",

            # Платформа
            "platform": "win" if IS_WIN else ("mac" if IS_MAC else "linux"),
            "is_win":   str(IS_WIN).lower(),
            "is_linux": str(IS_LINUX).lower(),
            "is_mac":   str(IS_MAC).lower(),

            # Системные пути
            "USERPROFILE":  os.path.expanduser("~"),
            "APPDATA":      os.environ.get("APPDATA", ""),
            "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
            "PROGRAMFILES": os.environ.get("ProgramFiles", ""),
            "PROGRAMFILES86": os.environ.get("ProgramFiles(x86)", ""),
            "STEAM":        _find_steam_path(),

            # Ответы пользователя на вопросы + set_var переменные
            "user_vars": dict(user_answers or {}),

            # Служебное
            "_install_mode": "install",
        }

        # Поверх базового — данные из вызывающего кода (game_id, mod_id, история и т.д.)
        if extra_ctx:
            for k, v in extra_ctx.items():
                if k == "user_vars" and isinstance(v, dict):
                    self.ctx["user_vars"].update(v)
                else:
                    self.ctx[k] = v

        # Если game_folder пришёл из истории — записываем сразу
        if self.ctx.get("game_folder"):
            self.ctx["user_vars"].setdefault("game_folder", self.ctx["game_folder"])

    def run(self) -> bool:
        """Выполняет все шаги инструкции с поддержкой if/else/for/while."""
        steps = self.recipe.get("steps", [])
        if not steps:
            self.log("  ⚠ Инструкция пуста — шагов нет")
            return False
        ok = self._exec_steps(steps)
        return ok

    def _exec_steps(self, steps: list, depth: int = 0) -> bool:
        """
        Основной исполнитель шагов. Поддерживает вложенные блоки:
          if / elif / else / end_if
          for  (итерация по массиву)
          while (цикл с условием, max_iter защита от бесконечного цикла)
        """
        i = 0
        while i < len(steps):
            step   = steps[i]
            action = step.get("action", "")
            label  = step.get("label", action)

            # ── IF ────────────────────────────────────────────────────────────
            if action == "if":
                # Собираем все ветки до end_if
                branches, end_idx = self._collect_if_branches(steps, i)
                self._exec_if(branches)
                i = end_idx + 1
                continue

            # ── FOR ───────────────────────────────────────────────────────────
            if action == "for":
                body, end_idx = self._collect_block(steps, i + 1, "end_for")
                self._exec_for(step, body)
                i = end_idx + 1
                continue

            # ── WHILE ─────────────────────────────────────────────────────────
            if action == "while":
                body, end_idx = self._collect_block(steps, i + 1, "end_while")
                self._exec_while(step, body)
                i = end_idx + 1
                continue

            # Пропускаем закрывающие маркеры если попали сюда напрямую
            if action in ("end_if", "end_for", "end_while", "else", "elif"):
                i += 1
                continue

            # ── Обычный шаг ───────────────────────────────────────────────────
            when = step.get("when", "")
            if when and not _pf_safe_eval_condition(when, self.ctx):
                self.log(f"  ⏭ «{label}» — пропущен (when={when!r})")
                i += 1
                continue

            self.log(f"  ▶ {label}")
            handler_name = self.STEP_HANDLERS.get(action)
            if not handler_name:
                self.log(f"  ⚠ Неизвестное действие: {action!r}")
                i += 1
                continue

            try:
                ok = getattr(self, handler_name)(step)
            except Exception as e:
                self.log(f"  ❌ Ошибка в шаге «{label}»: {e}")
                ok = False

            if not ok and step.get("required", False):
                self.log(f"  🛑 Шаг «{label}» обязательный, прерываем установку")
                return False

            i += 1
        return True

    # ── Управление потоком ────────────────────────────────────────────────────

    def _collect_if_branches(self, steps: list, start: int):
        """
        Собирает ветки if/elif/else/end_if начиная с позиции start.
        Возвращает (branches, end_idx).
        branches = [{"cond": str|None, "body": [steps]}]
        """
        branches = []
        cur_cond = steps[start].get("when", steps[start].get("condition", "True"))
        cur_body = []
        depth = 0
        i = start + 1
        while i < len(steps):
            a = steps[i].get("action", "")
            if a == "if":
                depth += 1
            if depth == 0:
                if a in ("elif", "else", "end_if"):
                    branches.append({"cond": cur_cond, "body": cur_body})
                    if a == "end_if":
                        return branches, i
                    cur_cond = steps[i].get("condition", "") if a == "elif" else None
                    cur_body = []
                    i += 1
                    continue
            if a == "end_if" and depth > 0:
                depth -= 1
            cur_body.append(steps[i])
            i += 1
        branches.append({"cond": cur_cond, "body": cur_body})
        return branches, i - 1

    def _exec_if(self, branches: list):
        for branch in branches:
            cond = branch["cond"]
            # else ветка
            if cond is None or _pf_safe_eval_condition(cond, self.ctx):
                self._exec_steps(branch["body"])
                return

    def _collect_block(self, steps: list, start: int, end_action: str):
        """Собирает тело блока до end_action с учётом вложенности."""
        body  = []
        depth = 0
        outer_action = end_action.replace("end_", "")
        i = start
        while i < len(steps):
            a = steps[i].get("action", "")
            if a == outer_action:
                depth += 1
            if a == end_action:
                if depth == 0:
                    return body, i
                depth -= 1
            body.append(steps[i])
            i += 1
        return body, i - 1

    def _exec_for(self, step: dict, body: list):
        """
        for-loop по массиву.
        step:
          var       — имя переменной итерации (default "item")
          index_var — имя переменной-счётчика 0-based (default "{var}_index")
          items     — список значений ["a","b","c"]
          items_var — имя переменной ctx содержащей список (альтернатива items)

        Автоматически устанавливает:
          {var}             — текущий элемент
          {var}_index       — индекс 0-based (0, 1, 2 …)
          {var}_number      — номер 1-based (1, 2, 3 …)
          {var}_total       — общее число элементов
          {var}_is_first    — "true" / "false"
          {var}_is_last     — "true" / "false"
        """
        var_name  = step.get("var", "item")
        idx_var   = step.get("index_var", f"{var_name}_index")
        items     = step.get("items")
        items_var = step.get("items_var", "")

        if items is None and items_var:
            raw   = self.ctx["user_vars"].get(items_var, "")
            items = raw if isinstance(raw, list) else [x.strip() for x in str(raw).split(",")]
        if not items:
            self.log(f"  ⚠ for: items пустой")
            return

        total = len(items)
        self._set_uv(f"{var_name}_total", str(total))

        for idx, val in enumerate(items):
            val_str = str(val).strip()
            self._set_uv(var_name,            val_str)
            self._set_uv(idx_var,             str(idx))
            self._set_uv(f"{var_name}_number", str(idx + 1))
            self._set_uv(f"{var_name}_is_first", "true" if idx == 0       else "false")
            self._set_uv(f"{var_name}_is_last",  "true" if idx == total-1 else "false")
            self.log(f"  🔁 for [{idx+1}/{total}] {var_name} = {val_str!r}")
            self._exec_steps(body)

    def _exec_while(self, step: dict, body: list):
        """
        while-loop с автоматическим счётчиком итераций.
        step:
          condition  — выражение (тот же синтаксис что when)
          max_iter   — защита от бесконечного цикла (default 100)
          index_var  — имя переменной-счётчика (default "while_index")

        Автоматически устанавливает:
          {index_var}        — индекс 0-based
          {index_var}_number — номер 1-based
        """
        condition = step.get("condition", step.get("when", "False"))
        max_iter  = int(step.get("max_iter", 100))
        idx_var   = step.get("index_var", "while_index")
        it = 0
        while _pf_safe_eval_condition(condition, self.ctx):
            if it >= max_iter:
                self.log(f"  ⚠ while: достигнут лимит {max_iter} итераций, выходим")
                break
            self._set_uv(idx_var,              str(it))
            self._set_uv(f"{idx_var}_number",  str(it + 1))
            self.log(f"  🔁 while итерация {it + 1}")
            self._exec_steps(body)
            it += 1

    def _set_uv(self, key: str, value: str):
        """Вспомогательный метод: записывает значение в user_vars и синхронизирует ctx."""
        self.ctx["user_vars"][key] = value
        _SYNC = {"game_folder", "store", "version", "game_id", "mod_id", "game_name"}
        if key in _SYNC:
            self.ctx[key] = value

    # ── Шаги ─────────────────────────────────────────────────────────────────

    # ── set_var ───────────────────────────────────────────────────────────────
    def _step_set_var(self, step: dict) -> bool:
        """
        Задаёт переменную в ctx["user_vars"].
        step:
          vars: {"name": "value", ...}        — задать несколько сразу
          name / value                         — задать одну
          eval: "expression"                   — вычислить как условие → "true"/"false"
          concat: ["part1", "{var}", "part2"]  — склеить строки

        Особые переменные (game_folder, store, version, game_id, mod_id, game_name)
        автоматически синхронизируются в корень ctx и доступны в when-условиях.
        """
        tpl = self._tpl()

        def _apply(k: str, v: str):
            self._set_uv(k, v)
            # game_folder → сохраняем в историю
            if k == "game_folder" and v and os.path.isdir(v) and self.ctx.get("game_id"):
                history_set_game_folder(self.ctx["game_id"], v)

        for k, v in step.get("vars", {}).items():
            rendered = str(v).format(**tpl) if isinstance(v, str) else str(v)
            _apply(k, rendered)
            self.log(f"  📌 {k} = {rendered!r}")

        name = step.get("name", "")
        if name:
            if "eval" in step:
                result = "true" if _pf_safe_eval_condition(step["eval"], self.ctx) else "false"
                _apply(name, result)
                self.log(f"  📌 {name} = {result!r} (eval)")
            elif "concat" in step:
                parts  = [str(p).format(**tpl) for p in step["concat"]]
                result = "".join(parts)
                _apply(name, result)
                self.log(f"  📌 {name} = {result!r} (concat)")
            else:
                val = str(step.get("value", "")).format(**tpl)
                _apply(name, val)
                self.log(f"  📌 {name} = {val!r}")
        return True

    # ── increment ─────────────────────────────────────────────────────────────
    def _step_increment(self, step: dict) -> bool:
        """
        Инкрементирует / декрементирует числовую переменную.
        step:
          name  — имя переменной (обязательно)
          by    — на сколько изменить (default 1, может быть отрицательным)
          init  — начальное значение если переменная не задана (default 0)
          log   — bool: писать в лог (default True)

        Пример использования как счётчик обработанных файлов:
          { "action": "increment", "name": "files_done" }
          { "action": "increment", "name": "errors",     "by": 1 }
          { "action": "increment", "name": "retry_left", "by": -1, "init": 3 }
        """
        name = step.get("name", "")
        if not name:
            self.log("  ⚠ increment: не задан name")
            return False

        by   = int(step.get("by",   1))
        init = int(step.get("init", 0))
        do_log = step.get("log", True)

        cur_raw = self.ctx["user_vars"].get(name, str(init))
        try:
            cur = int(cur_raw)
        except (ValueError, TypeError):
            cur = init

        new_val = cur + by
        self._set_uv(name, str(new_val))

        if do_log:
            arrow = f"{cur} → {new_val}"
            self.log(f"  🔢 {name}: {arrow}  (by {by:+d})")
        return True

    # ── find_game_folder ──────────────────────────────────────────────────────
    def _step_find_game_folder(self, step: dict) -> bool:
        folder = _pf_find_game_folder(step, self.ctx)
        if folder:
            self.ctx["game_folder"] = folder
            self.ctx["user_vars"]["game_folder"] = folder
            self.log(f"  📂 Папка игры найдена: {folder}")
            # Сохраняем в историю чтобы следующий раз не искать
            if self.ctx.get("game_id"):
                history_set_game_folder(self.ctx["game_id"], folder)
                self.log(f"  💾 Путь сохранён в историю для App ID {self.ctx['game_id']}")
            return True
        manual = step.get("manual_fallback")
        if manual:
            self.ctx["game_folder"] = manual
            self.ctx["user_vars"]["game_folder"] = manual
            self.log(f"  ⚠ Используется fallback: {manual}")
            return True
        self.log("  ⚠ Папка игры не найдена")
        return False


    # ── Шаг: detect_store ────────────────────────────────────────────────────
    def _step_detect_store(self, step: dict) -> bool:
        """
        Определяет КАК УСТАНОВЛЕНА ИГРА (Steam/GOG/Epic/other).

        Ключевой момент: WorkshopDL скачивает моды через SteamCMD, значит
        скачанный мод — всегда Steam-источник. Но ИГРА может быть установлена
        из GOG или Epic — и тогда папка назначения для мода отличается.

        Логика:
          - ctx["workshopdl_source"] = True → мод точно из Steam (Workshop)
          - game_folder определяется через find_game_folder перед этим шагом
          - _pf_detect_game_store ищет признаки в папке ИГРЫ, не мода

        Результат в ctx:
          ctx["store"]   — магазин игры ("steam"/"gog"/"epic"/"other")
          ctx["version"] — версия игры или ""
          ctx["user_vars"]["store"]   — доступно в шаблонах как {store}
          ctx["user_vars"]["version"] — доступно как {version}

        Если game_folder не найдена — определяем по пути из ctx["mod_folder"]
        (мод лежит в steamapps/workshop → игра вероятно тоже в Steam).
        """
        game_folder = self.ctx.get("game_folder", "")

        # ── Особый случай: game_folder не задана ──────────────────────────────
        # Мод скачан через WorkshopDL → он всегда из SteamCMD.
        # Если папку игры ещё не нашли — определяем store по пути мода.
        if not game_folder:
            mod_folder = self.ctx.get("mod_folder", "")
            norm_mod = mod_folder.replace("\\", "/").lower()
            if "steamapps/workshop/content" in norm_mod:
                # 100% Steam — мод лежит в workshop/content
                self.ctx["store"]   = "steam"
                self.ctx["version"] = ""
                self.ctx["user_vars"]["store"]   = "steam"
                self.ctx["user_vars"]["version"] = ""
                self.log("  🎮 Магазин: STEAM (WorkshopDL — мод из SteamCMD workshop)")
                self.log("  ℹ  game_folder не задана — запустите find_game_folder для установки")
                return True
            self.log("  ⚠ detect_store: game_folder не задана, запустите find_game_folder раньше")
            return False

        result  = _pf_detect_game_store(game_folder, step, self.ctx)
        store   = result["store"]
        version = result["version"]
        evidence = result["evidence"]
        votes    = result.get("votes", {})

        self.ctx["store"]   = store
        self.ctx["version"] = version
        self.ctx["user_vars"]["store"]   = store
        self.ctx["user_vars"]["version"] = version

        store_icon = {"steam": "🎮", "gog": "🌌", "epic": "⚡", "other": "📦"}.get(store, "❓")
        self.log(f"  {store_icon} Магазин игры: {store.upper()}")

        # Показываем голоса если есть соперники
        if votes:
            vote_str = "  " + "  ".join(
                f"{s.upper()}:{v}" for s, v in sorted(votes.items(), key=lambda x: -x[1]) if v > 0
            )
            if vote_str.strip():
                self.log(f"  📊 Голоса детектора:{vote_str}")

        if version:
            self.log(f"  🏷  Версия игры: {version}")

        if evidence:
            shown = evidence[:4]
            rest  = len(evidence) - 4
            self.log("  🔍 Признаки: " + ", ".join(shown) + (f" + ещё {rest}" if rest > 0 else ""))

        # Предупреждение: WorkshopDL скачивает только через Steam —
        # если игра GOG/Epic, это нормально, мод всё равно Steam-версии
        if store in ("gog", "epic"):
            self.log(
                f"  ℹ  Игра установлена через {store.upper()}, "
                f"но мод скачан через SteamCMD — убедитесь что игра "
                f"поддерживает Steam Workshop моды в {store.upper()} версии"
            )

        return True

    # ── Шаг: read_file ────────────────────────────────────────────────────────
    def _step_read_file(self, step: dict) -> bool:
        """
        Читает значение из файла и сохраняет в ctx["user_vars"][save_as].
        JSON-инструкция:
          {
            "action": "read_file",
            "label": "Читаем версию",
            "save_as": "game_version",      // ключ в user_vars (default: "read_value")
            "required": false,
            "file":   "version.txt",
            "format": "auto",               // text | json | ini | binary | auto
            "extract": {
              "regex": "Version[:\\s]+([\\d.]+)"
            }
          }
        После выполнения значение доступно как {game_version} в шаблонах путей.
        """
        save_as = step.get("save_as", "read_value")
        base    = self.ctx.get("game_folder", self.ctx.get("mod_folder", ""))
        value   = _pf_read_file_value(base, step, self.ctx)

        if value is not None:
            self.ctx["user_vars"][save_as] = value
            self.log(f"  📄 {save_as} = {value!r}")
            return True
        else:
            fallback = step.get("fallback")
            if fallback is not None:
                self.ctx["user_vars"][save_as] = str(fallback)
                self.log(f"  📄 {save_as} = {fallback!r} (fallback)")
                return True
            self.log(f"  ⚠ read_file: значение не найдено ({step.get('file', '?')})")
            return not step.get("required", False)


    def _step_copy(self, step: dict) -> bool:
        src = step.get("src", "{mod_folder}").format(**self._tpl())
        dst = step.get("dst", "{game_folder}").format(**self._tpl())
        if not dst:
            self.log("  ⚠ Целевая папка не задана (нет game_folder?)")
            return False
        os.makedirs(dst, exist_ok=True)
        copied = _pf_smart_copy(src, dst, step, self.log)
        return bool(copied) or not step.get("required", False)

    # ── rename ────────────────────────────────────────────────────────────────
    def _step_rename(self, step: dict) -> bool:
        base = step.get("base", "{game_folder}").format(**self._tpl())
        rules = step.get("rules", [step])   # можно одно правило прямо в шаге
        count = _pf_rename_files(base, rules, self.log)
        self.log(f"  📝 Переименовано файлов: {count}")
        return True

    # ── delete ────────────────────────────────────────────────────────────────
    def _step_delete(self, step: dict) -> bool:
        base  = step.get("base", "{game_folder}").format(**self._tpl())
        rules = step.get("rules", [step])
        count = _pf_delete_files(base, rules, self.log)
        self.log(f"  🗑 Удалено объектов: {count}")
        return True

    # ── backup ────────────────────────────────────────────────────────────────
    def _step_backup(self, step: dict) -> bool:
        """
        Создаёт .bak копию файла или всей папки.
          path   — путь к файлу или папке (шаблон)
          suffix — расширение бэкапа (default ".bak")
          keep   — сколько версий ротировать (default 3)
          folder — true: бэкапить всю папку как .bak.zip
        """
        tpl    = self._tpl()
        path   = step.get("path", "").format(**tpl)
        suffix = step.get("suffix", ".bak")
        keep   = int(step.get("keep", 3))

        if not path:
            self.log("  ⚠ backup: не задан path")
            return False

        if step.get("folder") and os.path.isdir(path):
            # Бэкап папки → zip
            zip_path = path.rstrip("/\\") + suffix + ".zip"
            try:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for dp, _, files in os.walk(path):
                        for f in files:
                            fp = os.path.join(dp, f)
                            zf.write(fp, os.path.relpath(fp, os.path.dirname(path)))
                self.log(f"  💾 бэкап папки: {os.path.basename(zip_path)}")
                return True
            except Exception as e:
                self.log(f"  ❌ ошибка бэкапа папки: {e}")
                return False

        # Бэкап файла
        if os.path.isfile(path):
            result = _pf_backup_file(path, self.log, suffix=suffix, keep=keep)
            return result is not None
        # Glob: бэкапим несколько файлов
        matches = glob.glob(path)
        if not matches:
            self.log(f"  ⚠ backup: файл не найден: {path}")
            return not step.get("required", False)
        for fp in matches:
            _pf_backup_file(fp, self.log, suffix=suffix, keep=keep)
        return True

    # ── check_disk ────────────────────────────────────────────────────────────
    def _step_check_disk(self, step: dict) -> bool:
        """
        Проверяет свободное место на диске.
          path        — путь для проверки (default game_folder или mod_folder)
          required_mb — сколько нужно МБ
          save_as     — имя переменной для результата "true"/"false" (опционально)
          required    — если true и места нет — прерывает установку
        """
        tpl     = self._tpl()
        path    = step.get("path", tpl.get("game_folder") or tpl.get("mod_folder", "."))
        path    = path.format(**tpl)
        req_mb  = int(step.get("required_mb", 0))
        save_as = step.get("save_as", "")

        result  = _pf_check_disk(path or ".", req_mb)
        ok      = result["ok"]
        free_mb = result["free_mb"]

        status = "✅" if ok else "⚠"
        self.log(f"  {status} Диск {path}: свободно {free_mb} МБ, требуется {req_mb} МБ — {'OK' if ok else 'НЕДОСТАТОЧНО'}")

        if save_as:
            self.ctx["user_vars"][save_as] = "true" if ok else "false"
            self.log(f"  📌 {save_as} = {'true' if ok else 'false'}")

        if not ok and step.get("required", False):
            self.log(f"  🛑 Недостаточно места: нужно {req_mb} МБ, доступно {free_mb} МБ")
            return False
        return True

    # ── patch_ini ─────────────────────────────────────────────────────────────
    def _step_patch_ini(self, step: dict) -> bool:
        path = step.get("file", "").format(**self._tpl())
        return _pf_patch_ini(path, step.get("patches", []), self.log)

    # ── patch_json ────────────────────────────────────────────────────────────
    def _step_patch_json(self, step: dict) -> bool:
        path = step.get("file", "").format(**self._tpl())
        return _pf_patch_json(path, step.get("patches", []), self.log)

    # ── patch_xml ─────────────────────────────────────────────────────────────
    def _step_patch_xml(self, step: dict) -> bool:
        path = step.get("file", "").format(**self._tpl())
        return _pf_patch_xml(path, step.get("patches", []), self.log)

    # ── patch_cfg ─────────────────────────────────────────────────────────────
    def _step_patch_cfg(self, step: dict) -> bool:
        path = step.get("file", "").format(**self._tpl())
        return _pf_patch_cfg(path, step.get("patches", []), self.log)

    # ── plugin (гибридный режим) ──────────────────────────────────────────────
    def _step_plugin(self, step: dict) -> bool:
        """
        Запускает внешний Python-плагин.
        plugin_file: имя .py в INSTALL_LOCAL_DIR/plugins/
        plugin_url:  прямой URL до скрипта на GitHub
        Плагин должен содержать: install(ctx, log_cb) -> bool
                              и опционально: uninstall(ctx, log_cb) -> bool
        """
        plugin_file = step.get("plugin_file", "")
        plugin_url  = step.get("plugin_url", "")

        if plugin_url:
            fname = os.path.basename(plugin_url.split("?")[0]) or "plugin_temp.py"
            plugin_path = os.path.join(INSTALL_LOCAL_DIR, "plugins", fname)
            os.makedirs(os.path.dirname(plugin_path), exist_ok=True)
            try:
                r = requests.get(plugin_url, timeout=10)
                r.raise_for_status()
                with open(plugin_path, "w", encoding="utf-8") as f:
                    f.write(r.text)
            except Exception as e:
                self.log(f"  ❌ Не удалось скачать плагин: {e}")
                return False
        elif plugin_file:
            plugin_path = os.path.join(INSTALL_LOCAL_DIR, "plugins", plugin_file)
            if not os.path.isfile(plugin_path):
                self.log(f"  ❌ Плагин не найден: {plugin_path}")
                return False
        else:
            self.log("  ❌ plugin: не указан plugin_file или plugin_url")
            return False

        try:
            spec   = importlib.util.spec_from_file_location("wdl_plugin", plugin_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            mode       = self.ctx.get("_install_mode", "install")
            fn_name    = "uninstall" if mode == "uninstall" else "install"
            fn         = getattr(module, fn_name, None)
            if fn is None:
                self.log(f"  ⚠ плагин не содержит функцию {fn_name}(), пропуск")
                return True
            plugin_ctx = {**self.ctx, **step.get("params", {})}
            return bool(fn(plugin_ctx, self.log))
        except Exception as e:
            self.log(f"  ❌ Ошибка выполнения плагина: {e}")
            return False

    def _tpl(self) -> dict:
        """
        Словарь подстановок для format() в путях и значениях.
        Порядок приоритетов (от низшего к высшему):
          1. Системные пути (APPDATA, STEAM и т.д.) — из ctx напрямую
          2. Идентификаторы игры/мода (game_id, mod_id, game_name)
          3. Рабочие папки (game_folder, mod_folder, steamcmd_root)
          4. Магазин и версия (store, version, platform)
          5. user_vars — ответы пользователя и set_var; перекрывают всё выше
        """
        base = {
            # Системные
            "USERPROFILE":    self.ctx.get("USERPROFILE",  os.path.expanduser("~")),
            "APPDATA":        self.ctx.get("APPDATA",      os.environ.get("APPDATA", "")),
            "LOCALAPPDATA":   self.ctx.get("LOCALAPPDATA", os.environ.get("LOCALAPPDATA", "")),
            "PROGRAMFILES":   self.ctx.get("PROGRAMFILES", os.environ.get("ProgramFiles", "")),
            "PROGRAMFILES86": self.ctx.get("PROGRAMFILES86", os.environ.get("ProgramFiles(x86)", "")),
            "STEAM":          self.ctx.get("STEAM",        _find_steam_path()),

            # Идентификаторы
            "game_id":   self.ctx.get("game_id",   ""),
            "mod_id":    self.ctx.get("mod_id",    ""),
            "game_name": self.ctx.get("game_name", ""),
            # Счётчики модов
            "mod_index":    self.ctx.get("mod_index",    "0"),
            "mod_number":   self.ctx.get("mod_number",   "1"),
            "mod_total":    self.ctx.get("mod_total",    "1"),
            "mod_count":    self.ctx.get("mod_count",    "1"),
            "mod_is_first": self.ctx.get("mod_is_first", "true"),
            "mod_is_last":  self.ctx.get("mod_is_last",  "true"),

            # Папки
            "game_folder":    self.ctx.get("game_folder",    ""),
            "mod_folder":     self.ctx.get("mod_folder",     ""),
            "content_folder": self.ctx.get("content_folder", ""),
            "steamcmd_root":  self.ctx.get("steamcmd_root",  ""),

            # Магазин и версия
            "store":    self.ctx.get("store",    ""),
            "version":  self.ctx.get("version",  ""),
            "platform": self.ctx.get("platform", ""),
        }
        # user_vars в конце — перекрывают базовые если есть одноимённые
        base.update(self.ctx.get("user_vars", {}))
        return base

    def run_uninstall(self) -> bool:
        """Запускает блок uninstall из инструкции (если он есть)."""
        steps = self.recipe.get("uninstall", [])
        if not steps:
            self.log("  ℹ Блок uninstall в инструкции не найден")
            return False
        self.ctx["_install_mode"] = "uninstall"
        self.log("🗑 Запуск деинсталляции мода...")
        return self._exec_steps(steps)


# ── Фоновый воркер установки (пакетная установка нескольких модов) ────────────

class InstallWorker(QThread):
    log_line   = pyqtSignal(str)
    progress   = pyqtSignal(int, int)   # current, total
    mod_status = pyqtSignal(str, bool)  # mod_id, success
    finished   = pyqtSignal(int, int)   # success_count, fail_count

    def __init__(self, recipe: dict, mod_folders: dict, user_answers: dict,
                 extra_ctx: dict = None):
        """
        recipe       — инструкция установки
        mod_folders  — {mod_id: folder_path}
        user_answers — ответы пользователя на вопросы (из InstallQuestionsDialog)
        extra_ctx    — дополнительный контекст: game_id, game_name, game_folder из истории и т.д.
        """
        super().__init__()
        self.recipe       = recipe
        self.mod_folders  = mod_folders
        self.user_answers = user_answers
        self.extra_ctx    = extra_ctx or {}

    def run(self):
        total   = len(self.mod_folders)
        success = fail = 0
        for i, (mod_id, folder) in enumerate(self.mod_folders.items(), 1):
            self.progress.emit(i - 1, total)
            self.log_line.emit(f"\n📦 [{i}/{total}] Установка мода {mod_id}...")
            self.log_line.emit(f"   Папка мода: {folder}")

            # Контекст специфичный для этого конкретного мода
            per_mod_ctx = {
                **self.extra_ctx,
                # Идентификатор текущего мода
                "mod_id": mod_id,
                # Счётчики — доступны в шагах и when-условиях как {mod_index} и т.д.
                "mod_index":    str(i - 1),   # 0-based: 0, 1, 2 …
                "mod_number":   str(i),        # 1-based: 1, 2, 3 …
                "mod_total":    str(total),    # всего модов в этой установке
                "mod_is_first": "true" if i == 1     else "false",
                "mod_is_last":  "true" if i == total else "false",
            }

            installer = ModInstaller(
                self.recipe, folder,
                self.log_line.emit,
                user_answers=self.user_answers,
                extra_ctx=per_mod_ctx,
            )

            # Логируем ключевые поля контекста
            ctx = installer.ctx
            if ctx.get("game_id"):
                self.log_line.emit(f"   App ID: {ctx['game_id']}  ({ctx.get('game_name', '')})")
            if ctx.get("game_folder"):
                self.log_line.emit(f"   Папка игры: {ctx['game_folder']}")
            self.log_line.emit(
                f"   Мод {i} из {total}"
                + ("  [первый]" if i == 1 else "")
                + ("  [последний]" if i == total else "")
            )

            ok = installer.run()

            # После установки — сохраняем game_folder в историю если появился
            found_folder = installer.ctx.get("game_folder", "")
            game_id_ctx  = installer.ctx.get("game_id", "")
            if found_folder and game_id_ctx:
                history_set_game_folder(game_id_ctx, found_folder)
                self.log_line.emit(f"   💾 Путь к игре сохранён в историю")

            if ok:
                success += 1
                self.log_line.emit(f"  ✅ Мод {mod_id} установлен успешно  [{i}/{total}]")
            else:
                fail += 1
                self.log_line.emit(f"  ❌ Мод {mod_id} — ошибка установки  [{i}/{total}]")
            self.mod_status.emit(mod_id, ok)

        self.progress.emit(total, total)
        self.finished.emit(success, fail)


# ── Главный диалог установки (точка входа из MainWindow) ──────────────────────

class InstallDialog(QDialog):
    """
    Диалог, который:
    1. Показывает инструкцию и список модов
    2. Задаёт вопросы пользователю (если есть)
    3. Запускает InstallWorker и показывает прогресс + лог
    """

    def __init__(self, recipe: dict, mod_folders: dict, extra_ctx: dict = None, parent=None):
        super().__init__(parent)
        self.recipe      = recipe
        self.mod_folders = mod_folders
        self.extra_ctx   = extra_ctx or {}
        self._worker     = None
        self._answers    = {}

        game_name = recipe.get("game_name", self.extra_ctx.get("game_name", "Игра"))
        game_id   = self.extra_ctx.get("game_id", "")
        self.setWindowTitle(f"📥 Установка модов — {game_name}")
        self.setMinimumSize(640, 500)

        lay = QVBoxLayout(self)

        # Заголовок с контекстом
        hist_folder = self.extra_ctx.get("game_folder", "")
        folder_line = f"<br><b>Папка игры (из истории):</b> <code>{hist_folder}</code>" if hist_folder else ""
        gameid_line = f"  <span style='color:#888'>App ID: {game_id}</span>" if game_id else ""
        info_text = (
            f"<b>Игра:</b> {game_name}{gameid_line}{folder_line}<br>"
            f"<b>Описание:</b> {recipe.get('description', '—')}<br>"
            f"<b>Модов для установки:</b> {len(mod_folders)}"
        )
        info = QLabel(info_text)
        info.setWordWrap(True)
        lay.addWidget(info)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); lay.addWidget(sep)

        # Список модов
        grp = QGroupBox("Моды:")
        gl  = QVBoxLayout(grp)
        self._mod_list = QListWidget()
        for mod_id, folder in mod_folders.items():
            self._mod_list.addItem(f"  {mod_id}  ({folder})")
        gl.addWidget(self._mod_list)
        lay.addWidget(grp)

        # Прогресс
        self._progress = QProgressBar()
        self._progress.setFormat("%v / %m")
        self._progress.setMaximum(len(mod_folders))
        self._progress.setValue(0)
        lay.addWidget(self._progress)

        # Лог
        grp_log = QGroupBox("Лог установки:")
        ll = QVBoxLayout(grp_log)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        self._log.setMinimumHeight(160)
        ll.addWidget(self._log)
        lay.addWidget(grp_log)

        # Кнопки
        self._btn_install = QPushButton("▶ Начать установку")
        self._btn_install.setFixedHeight(34)
        f = self._btn_install.font(); f.setBold(True); self._btn_install.setFont(f)
        self._btn_install.clicked.connect(self._start)
        self._btn_close = QPushButton("Закрыть")
        self._btn_close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(self._btn_install)
        row.addWidget(self._btn_close)
        lay.addLayout(row)

    def _start(self):
        self._btn_install.setEnabled(False)
        questions = self.recipe.get("questions", [])
        # Задаём вопросы если они есть
        if questions:
            dlg = InstallQuestionsDialog(
                questions,
                mod_title=self.recipe.get("game_name", "Игра"),
                total_mods=len(self.mod_folders),
                ctx=self.extra_ctx,
                parent=self,
            )
            if dlg.exec_() != QDialog.Accepted:
                self._btn_install.setEnabled(True)
                return
            self._answers = dlg.get_answers()
            self._log_append(f"✍ Ответы пользователя: {self._answers}")

        self._log_append("🚀 Установка началась...\n")
        self._worker = InstallWorker(
            self.recipe, self.mod_folders, self._answers,
            extra_ctx=self.extra_ctx,
        )
        self._worker.log_line.connect(self._log_append)
        self._worker.progress.connect(lambda c, t: self._progress.setValue(c))
        self._worker.mod_status.connect(self._on_mod_status)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _log_append(self, text: str):
        self._log.append(text)
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum()
        )

    def _on_mod_status(self, mod_id: str, success: bool):
        icon = "✅" if success else "❌"
        for i in range(self._mod_list.count()):
            if mod_id in self._mod_list.item(i).text():
                self._mod_list.item(i).setText(
                    f"  {icon} {mod_id}"
                )
                break

    def _on_finished(self, ok: int, fail: int):
        self._btn_close.setText("✔ Готово")
        total = ok + fail
        self._log_append(
            f"\n{'='*50}\n"
            f"📊 Итог установки: {ok}/{total} успешно, {fail} с ошибками\n"
            f"{'='*50}"
        )
        QMessageBox.information(
            self, "Установка завершена",
            f"Установлено: {ok} из {total}\n"
            f"С ошибками: {fail}\n\n"
            "Подробности — в логе установки."
        )


# ══════════════════════════════════════════════════════════════════════════════
# КОНЕЦ МОД-УСТАНОВЩИКА
# ══════════════════════════════════════════════════════════════════════════════


class MainWindow(QMainWindow):
    # Сигналы для безопасного обновления UI из фоновых потоков
    _sig_set_game_id   = pyqtSignal(str, str)   # app_id, name
    _sig_log           = pyqtSignal(str)
    _sig_add_mod_items = pyqtSignal(list)        # [mod_id, ...]
    _sig_launch_update = pyqtSignal()            # запустить _do_launch_update с pending ids

    def __init__(self):
        super().__init__()
        self.setWindowTitle(t("app_title"))
        self.setMinimumSize(920, 720)
        self.worker     = None
        self.upd_worker = None
        self._outdated_ids = []
        self._upd_rows  = {}
        self.cfg = load_config()
        # Подключаем сигналы к слотам в главном потоке
        self._sig_set_game_id.connect(self._slot_set_game_id)
        self._sig_log.connect(self._log)
        self._sig_add_mod_items.connect(self._slot_add_mod_items)
        self._sig_launch_update.connect(self._slot_launch_update)
        self._pending_update_ids = []
        self._build_ui()
        self._load_settings()
        self._scan_and_refresh_history()
        self._check_resume()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        c = QWidget(); self.setCentralWidget(c)
        root = QVBoxLayout(c)
        root.setSpacing(8); root.setContentsMargins(12, 12, 12, 12)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self.tabs.addTab(self._tab_download(), t("tab_download"))
        self.tabs.addTab(self._tab_history(),  t("tab_history"))
        self.tabs.addTab(self._tab_updates(),  t("tab_updates"))
        self.tabs.addTab(self._tab_settings(), t("tab_settings"))

    # ── Вкладка: Скачать ──────────────────────────────────────────────────────
    def _tab_download(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(6)

        rg = QHBoxLayout()
        rg.addWidget(QLabel(t("game_id_label")))
        self.inp_game = QLineEdit()
        self.inp_game.setPlaceholderText(t("game_id_placeholder"))
        rg.addWidget(self.inp_game)
        btn_find = QPushButton(t("btn_auto_find"))
        btn_find.setToolTip(t("btn_auto_find_tip"))
        btn_find.clicked.connect(self._auto_find_game)
        rg.addWidget(btn_find)
        lay.addLayout(rg)

        rm = QHBoxLayout()
        rm.addWidget(QLabel(t("mod_id_label")))
        self.inp_ws = QLineEdit()
        self.inp_ws.setPlaceholderText(t("mod_id_placeholder"))
        self.inp_ws.returnPressed.connect(self._add_to_list)
        self.inp_ws.textChanged.connect(self._on_mod_id_changed)
        rm.addWidget(self.inp_ws)
        btn_add = QPushButton(t("btn_add_to_list"))
        btn_add.clicked.connect(self._add_to_list)
        rm.addWidget(btn_add)
        lay.addLayout(rm)

        rc = QHBoxLayout()
        self.inp_col = QLineEdit()
        self.inp_col.setPlaceholderText(t("collection_placeholder"))
        rc.addWidget(self.inp_col)
        btn_col = QPushButton(t("btn_load_collection"))
        btn_col.clicked.connect(self._import_collection)
        rc.addWidget(btn_col)
        lay.addLayout(rc)

        grp = QGroupBox(t("group_mod_list"))
        gl = QVBoxLayout(grp)
        self.mod_list = QListWidget()
        self.mod_list.setSelectionMode(QListWidget.ExtendedSelection)
        gl.addWidget(self.mod_list)
        rb = QHBoxLayout()
        for lbl, slot in [(t("btn_remove_selected"), self._remove_selected),
                          (t("btn_clear_all"),       self.mod_list.clear),
                          (t("btn_import_txt"),      self._import_txt)]:
            b = QPushButton(lbl); b.clicked.connect(slot); rb.addWidget(b)
        gl.addLayout(rb); lay.addWidget(grp)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFormat("%v / %m")
        self.progress_bar.setMaximum(0)
        lay.addWidget(self.progress_bar)

        row_btns = QHBoxLayout()
        self.btn_download = QPushButton(t("btn_download"))
        self.btn_download.setFixedHeight(36)
        f = self.btn_download.font(); f.setBold(True); self.btn_download.setFont(f)
        self.btn_download.clicked.connect(lambda: self._start_download())
        self.btn_pause = QPushButton(t("btn_pause"))
        self.btn_pause.setFixedHeight(36); self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._pause_download)
        self.btn_cancel = QPushButton(t("btn_cancel"))
        self.btn_cancel.setFixedHeight(36); self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_download)
        for b in [self.btn_download, self.btn_pause, self.btn_cancel]:
            row_btns.addWidget(b)
        lay.addLayout(row_btns)

        grp_log = QGroupBox(t("group_log"))
        ll = QVBoxLayout(grp_log)
        self.log = QTextEdit(); self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9)); self.log.setMinimumHeight(130)
        ll.addWidget(self.log); lay.addWidget(grp_log)
        return w

    # ── Вкладка: История ─────────────────────────────────────────────────────
    def _tab_history(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.addWidget(QLabel(t("history_label")))
        self.history_list = QListWidget()
        self.history_list.itemDoubleClicked.connect(self._history_use)
        lay.addWidget(self.history_list)
        row = QHBoxLayout()
        for lbl, slot in [(t("btn_open_folder"),    self._history_open_folder),
                          (t("btn_use_game_id"),    self._history_use),
                          (t("btn_delete_history"), self._history_delete),
                          (t("btn_refresh_history"),self._scan_and_refresh_history)]:
            b = QPushButton(lbl); b.clicked.connect(slot); row.addWidget(b)
        lay.addLayout(row)
        return w

    # ── Вкладка: Проверка обновлений ──────────────────────────────────────────
    def _tab_updates(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(6)

        # Путь
        grp_path = QGroupBox(t("upd_group_path"))
        gp = QVBoxLayout(grp_path)
        gp.addWidget(QLabel(t("upd_path_desc")))
        rp = QHBoxLayout()
        self.cmb_update_paths = QComboBox()
        self.cmb_update_paths.setEditable(True)
        self.cmb_update_paths.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cmb_update_paths.lineEdit().setPlaceholderText(t("upd_path_placeholder"))
        rp.addWidget(self.cmb_update_paths)
        for icon, tip, slot in [("📁", "Обзор папки",        self._browse_update_path),
                                 ("✖",  "Удалить этот путь", self._delete_update_path)]:
            b = QPushButton(icon); b.setFixedWidth(34); b.setToolTip(tip)
            b.clicked.connect(slot); rp.addWidget(b)
        gp.addLayout(rp); lay.addWidget(grp_path)

        # Прогресс + флаг дат
        row_pg = QHBoxLayout()
        self.upd_progress = QProgressBar()
        self.upd_progress.setFormat(t("upd_progress_format"))
        self.upd_progress.setValue(0)
        row_pg.addWidget(self.upd_progress)
        self.chk_show_dates = QCheckBox(t("chk_show_dates"))
        self.chk_show_dates.setChecked(False)
        self.chk_show_dates.stateChanged.connect(self._toggle_date_columns)
        row_pg.addWidget(self.chk_show_dates)
        lay.addLayout(row_pg)

        # Кнопки управления
        row_btns = QHBoxLayout()
        self.btn_check_upd = QPushButton(t("btn_check_updates"))
        self.btn_check_upd.setFixedHeight(34)
        f = self.btn_check_upd.font(); f.setBold(True); self.btn_check_upd.setFont(f)
        self.btn_check_upd.clicked.connect(self._start_update_check)

        self.btn_update_all = QPushButton(t("btn_download_all_outdated"))
        self.btn_update_all.setFixedHeight(34); self.btn_update_all.setEnabled(False)
        self.btn_update_all.clicked.connect(self._update_all_outdated)

        self.btn_update_sel = QPushButton(t("btn_download_selected"))
        self.btn_update_sel.setFixedHeight(34); self.btn_update_sel.setEnabled(False)
        self.btn_update_sel.clicked.connect(self._update_selected_outdated)

        self.btn_enable_all  = QPushButton(t("btn_enable_all"))
        self.btn_enable_all.setFixedHeight(34); self.btn_enable_all.setEnabled(False)
        self.btn_enable_all.clicked.connect(lambda: self._toggle_all_mods(enable=True))

        self.btn_disable_all = QPushButton(t("btn_disable_all"))
        self.btn_disable_all.setFixedHeight(34); self.btn_disable_all.setEnabled(False)
        self.btn_disable_all.clicked.connect(lambda: self._toggle_all_mods(enable=False))

        for b in [self.btn_check_upd, self.btn_update_all, self.btn_update_sel,
                  self.btn_enable_all, self.btn_disable_all]:
            row_btns.addWidget(b)
        lay.addLayout(row_btns)

        # Таблица
        # Колонки: 0=Статус 1=Название 2=Размер 3=Steam 4=Вкл/Выкл 5=Папка 6=Дата лок 7=Дата сервер
        self.upd_table = QTableWidget(0, 8)
        self.upd_table.setHorizontalHeaderLabels([
            t("col_status"), t("col_name"), t("col_size"),
            t("col_steam"), t("col_toggle"), t("col_folder"),
            t("col_local_date"), t("col_server_date")
        ])
        hh = self.upd_table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSortIndicatorShown(True)
        self.upd_table.setSortingEnabled(True)
        self.upd_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.upd_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.upd_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.upd_table.setAlternatingRowColors(True)
        self.upd_table.verticalHeader().setVisible(False)
        self.upd_table.setColumnWidth(0, 40)   # статус
        self.upd_table.setColumnWidth(2, 75)   # размер
        self.upd_table.setColumnWidth(3, 60)   # steam
        self.upd_table.setColumnWidth(4, 80)   # toggle
        self.upd_table.setColumnWidth(5, 60)   # папка
        self.upd_table.setColumnWidth(6, 125)  # дата лок
        self.upd_table.setColumnWidth(7, 125)  # дата сервер
        self.upd_table.setFont(QFont("Segoe UI", 9))
        self.upd_table.cellClicked.connect(self._upd_table_clicked)
        lay.addWidget(self.upd_table)

        # Скрываем столбцы дат по умолчанию
        self.upd_table.setColumnHidden(6, True)
        self.upd_table.setColumnHidden(7, True)

        self.upd_status = QLabel("")
        lay.addWidget(self.upd_status)
        return w

    # ── Вкладка: Настройки ───────────────────────────────────────────────────
    def _tab_settings(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(10)

        self.chk_anon = QCheckBox(t("settings_anon"))
        self.chk_anon.stateChanged.connect(self._toggle_anon)
        lay.addWidget(self.chk_anon)

        grp_acc = QGroupBox(t("settings_account_group"))
        ga = QVBoxLayout(grp_acc)
        for lbl_key, attr, echo in [("settings_login", "inp_user", False),
                                     ("settings_password", "inp_pass", True)]:
            r = QHBoxLayout(); r.addWidget(QLabel(t(lbl_key)))
            field = QLineEdit()
            if echo: field.setEchoMode(QLineEdit.Password)
            setattr(self, attr, field); r.addWidget(field); ga.addLayout(r)
        lay.addWidget(grp_acc)

        # ── SteamCMD ──────────────────────────────────────────────────────────
        grp_scmd = QGroupBox(t("settings_steamcmd_group"))
        gs = QVBoxLayout(grp_scmd)

        # Путь вручную — создаём ПЕРВЫМ, т.к. _refresh_steamcmd_status его читает
        rp = QHBoxLayout()
        self.inp_steamcmd = QLineEdit(); self.inp_steamcmd.setPlaceholderText(STEAMCMD_DEF)
        rp.addWidget(self.inp_steamcmd)
        btn_browse = QPushButton(t("settings_browse"))
        btn_browse.clicked.connect(self._browse_steamcmd)
        rp.addWidget(btn_browse)
        gs.addLayout(rp)

        # Строка статуса — создаём ПОСЛЕ inp_steamcmd
        self.lbl_steamcmd_status = QLabel()
        self._refresh_steamcmd_status()
        gs.addWidget(self.lbl_steamcmd_status)

        # Кнопка скачать + прогресс
        row_dl = QHBoxLayout()
        self.btn_dl_steamcmd = QPushButton(t("steamcmd_dl_btn"))
        self.btn_dl_steamcmd.setFixedHeight(32)
        self.btn_dl_steamcmd.clicked.connect(self._download_steamcmd)
        row_dl.addWidget(self.btn_dl_steamcmd)
        self.pb_steamcmd = QProgressBar()
        self.pb_steamcmd.setFixedHeight(18)
        self.pb_steamcmd.setMaximum(100); self.pb_steamcmd.setValue(0)
        self.pb_steamcmd.setVisible(False)
        row_dl.addWidget(self.pb_steamcmd)
        gs.addLayout(row_dl)

        self.lbl_steamcmd_dl = QLabel("")
        gs.addWidget(self.lbl_steamcmd_dl)

        # Лог установки (скрыт пока не нажата кнопка)
        self.log_steamcmd = QTextEdit()
        self.log_steamcmd.setReadOnly(True)
        self.log_steamcmd.setFont(QFont("Consolas", 8))
        self.log_steamcmd.setMaximumHeight(120)
        self.log_steamcmd.setVisible(False)
        gs.addWidget(self.log_steamcmd)

        lay.addWidget(grp_scmd)

        # ── Язык ──────────────────────────────────────────────────────────────
        grp_lang = QGroupBox(t("settings_language_group"))
        gl2 = QVBoxLayout(grp_lang)

        # Строка 1: выпадающий список языков с GitHub + кнопка обновить список
        row_cmb = QHBoxLayout()
        self.cmb_lang = QComboBox()
        self.cmb_lang.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cmb_lang.setToolTip("Языки с GitHub — нажми ⟳ чтобы обновить список")
        row_cmb.addWidget(self.cmb_lang)
        self.btn_lang_refresh = QPushButton("⟳")
        self.btn_lang_refresh.setFixedWidth(34)
        self.btn_lang_refresh.setToolTip("Обновить список языков с GitHub")
        self.btn_lang_refresh.clicked.connect(self._fetch_lang_list)
        row_cmb.addWidget(self.btn_lang_refresh)
        self.btn_lang_dl = QPushButton("⬇ Скачать")
        self.btn_lang_dl.setFixedWidth(90)
        self.btn_lang_dl.clicked.connect(self._download_selected_lang)
        row_cmb.addWidget(self.btn_lang_dl)
        self.btn_lang_apply = QPushButton(t("settings_language_apply"))
        self.btn_lang_apply.setFixedWidth(90)
        self.btn_lang_apply.clicked.connect(self._apply_lang_from_combo)
        row_cmb.addWidget(self.btn_lang_apply)
        gl2.addLayout(row_cmb)

        # Статус
        self.lbl_lang_status = QLabel("  ⟳ Нажмите ⟳ чтобы загрузить список языков с GitHub")
        self.lbl_lang_status.setStyleSheet("color: #888;")
        gl2.addWidget(self.lbl_lang_status)

        # Строка 2: свой файл
        row_custom = QHBoxLayout()
        row_custom.addWidget(QLabel(t("settings_language_label")))
        self.inp_lang = QLineEdit()
        self.inp_lang.setPlaceholderText(LANG_DEF_PATH)
        row_custom.addWidget(self.inp_lang)
        btn_lang_browse = QPushButton(t("settings_language_browse"))
        btn_lang_browse.clicked.connect(self._browse_lang)
        row_custom.addWidget(btn_lang_browse)
        btn_lang_file_apply = QPushButton(t("settings_language_apply"))
        btn_lang_file_apply.clicked.connect(self._apply_language)
        row_custom.addWidget(btn_lang_file_apply)
        gl2.addLayout(row_custom)

        gl2.addWidget(QLabel(t("settings_language_note")))
        lay.addWidget(grp_lang)

        btn_save = QPushButton(t("settings_save"))
        btn_save.clicked.connect(self._save_settings)

        # ── Зависимости и загрузка ────────────────────────────────────────────
        grp_deps = QGroupBox("🔗 Зависимости и загрузка")
        gd = QVBoxLayout(grp_deps)

        # Поведение зависимостей
        gd.addWidget(QLabel("Что делать если у мода есть незагруженные зависимости:"))
        self.cmb_deps_behavior = QComboBox()
        self.cmb_deps_behavior.addItem("❓ Всегда спрашивать",       userData="ask")
        self.cmb_deps_behavior.addItem("⬇ Скачивать автоматически",  userData="auto")
        self.cmb_deps_behavior.addItem("🚫 Всегда пропускать",       userData="skip")
        gd.addWidget(self.cmb_deps_behavior)

        # Размер пачки
        row_batch = QHBoxLayout()
        row_batch.addWidget(QLabel("Размер пачки (модов за 1 сессию SteamCMD):"))
        self.spn_batch = QSpinBox()
        self.spn_batch.setRange(1, 50)
        self.spn_batch.setValue(1)
        self.spn_batch.setFixedWidth(70)
        self.spn_batch.setToolTip(
            "1 = один мод за раз (безопаснее, подробный лог)\n"
            "5–10 = меньше переподключений, быстрее при большом списке\n"
            "Не влияет на скорость интернета — только на число сессий SteamCMD"
        )
        row_batch.addWidget(self.spn_batch)
        row_batch.addStretch()
        gd.addLayout(row_batch)

        # Очистка кеша
        row_cache = QHBoxLayout()
        self.btn_clear_cache = QPushButton("🧹 Очистить кеш SteamCMD")
        self.btn_clear_cache.setToolTip(
            "Удаляет steamcmd/userdata/ и steamcmd/steamapps/\n"
            "Помогает если моды перестали скачиваться без причины"
        )
        self.btn_clear_cache.clicked.connect(self._clear_steamcmd_cache)
        row_cache.addWidget(self.btn_clear_cache)
        self.lbl_cache_status = QLabel("")
        row_cache.addWidget(self.lbl_cache_status)
        row_cache.addStretch()
        gd.addLayout(row_cache)

        lay.addWidget(grp_deps)

        # ── Репозиторий инструкций установки ─────────────────────────────────
        grp_inst = QGroupBox("📥 Репозиторий инструкций установки модов")
        gi = QVBoxLayout(grp_inst)
        gi.addWidget(QLabel(
            "Формат: <b>owner/repo</b> или <b>owner/repo/tree/branch/folder</b><br>"
            f"По умолчанию: <code>{INSTALL_REPO_DEFAULT}</code> → папка <code>{INSTALL_PATH_DEFAULT}/</code>"
        ))
        row_repo = QHBoxLayout()
        self.inp_install_repo = QLineEdit()
        self.inp_install_repo.setPlaceholderText(
            f"{INSTALL_REPO_DEFAULT}/{INSTALL_PATH_DEFAULT}"
        )
        self.inp_install_repo.setToolTip(
            "Репозиторий GitHub с JSON-инструкциями установки.\n"
            "Файлы должны быть: <папка>/<game_id>.json\n"
            "Примеры:\n"
            "  Pushkinmazila2/WorkshopDL\n"
            "  MyOrg/MyRepo/tree/main/game-installers"
        )
        row_repo.addWidget(self.inp_install_repo)
        self.btn_repo_test = QPushButton("🔍 Проверить")
        self.btn_repo_test.setFixedWidth(100)
        self.btn_repo_test.clicked.connect(self._test_install_repo)
        row_repo.addWidget(self.btn_repo_test)
        btn_repo_reset = QPushButton("↺ По умолч.")
        btn_repo_reset.setFixedWidth(90)
        btn_repo_reset.clicked.connect(lambda: self.inp_install_repo.clear())
        row_repo.addWidget(btn_repo_reset)
        gi.addLayout(row_repo)
        self.lbl_repo_status = QLabel("  Введите репозиторий и нажмите Проверить")
        self.lbl_repo_status.setStyleSheet("color: #888; font-size: 11px;")
        gi.addWidget(self.lbl_repo_status)

        row_cache2 = QHBoxLayout()
        self.btn_clear_install_cache = QPushButton("🗑 Очистить кеш инструкций")
        self.btn_clear_install_cache.setToolTip(
            "Удаляет локально кешированные .json инструкции.\n"
            "При следующей установке они будут заново скачаны с GitHub."
        )
        self.btn_clear_install_cache.clicked.connect(self._clear_install_cache)
        row_cache2.addWidget(self.btn_clear_install_cache)
        self.lbl_install_cache_info = QLabel("")
        self.lbl_install_cache_info.setStyleSheet("color: #888; font-size: 11px;")
        row_cache2.addWidget(self.lbl_install_cache_info)
        row_cache2.addStretch()
        gi.addLayout(row_cache2)
        self._refresh_install_cache_info()
        lay.addWidget(grp_inst)

        btn_save = QPushButton(t("settings_save"))
        btn_save.clicked.connect(self._save_settings)

        lay.addWidget(btn_save); lay.addStretch()
        return w


    def _load_settings(self):
        anon = cfg_get(self.cfg, "WorkshopDL", "Anonymous Mode", "1") == "1"
        self.chk_anon.setChecked(anon)
        self.inp_user.setText(cfg_get(self.cfg, "Steam", "Username"))
        self.inp_pass.setText(cfg_get(self.cfg, "Steam", "Password"))
        p = cfg_get(self.cfg, "WorkshopDL", "SteamCMDPath")
        if p: self.inp_steamcmd.setText(p)
        saved_path = cfg_get(self.cfg, "WorkshopDL", "ModsUpdatePath")
        if saved_path: mod_paths_add(saved_path)
        self._reload_update_paths_combo(saved_path or "")
        self._toggle_anon()

        deps_behavior = cfg_get(self.cfg, "WorkshopDL", "DepsBehavior", "ask")
        for i in range(self.cmb_deps_behavior.count()):
            if self.cmb_deps_behavior.itemData(i) == deps_behavior:
                self.cmb_deps_behavior.setCurrentIndex(i)
                break
        try:
            self.spn_batch.setValue(int(cfg_get(self.cfg, "WorkshopDL", "BatchSize", "1")))
        except Exception:
            pass

        # Репозиторий инструкций
        install_repo = cfg_get(self.cfg, "WorkshopDL", "InstallRepo", "")
        if install_repo:
            self.inp_install_repo.setText(install_repo)
        # Обновляем глобальные URL
        global GITHUB_INSTALL_RAW, GITHUB_INSTALL_API
        GITHUB_INSTALL_RAW, GITHUB_INSTALL_API = _install_repo_url(self.cfg)

        # Загружаем сохранённый язык
        lang_path = cfg_get(self.cfg, "WorkshopDL", "LangPath")
        if lang_path and os.path.exists(lang_path):
            self.inp_lang.setText(lang_path)
            lang_load(lang_path)
        else:
            lang_code = cfg_get(self.cfg, "WorkshopDL", "LangCode", "en")
            bundled = os.path.join(APP_DIR, f"lang_{lang_code}.json")
            local   = lang_local_path(lang_code)
            for candidate in (bundled, local):
                if os.path.exists(candidate):
                    lang_load(candidate)
                    self.inp_lang.setText(candidate)
                    break

    def _save_settings(self):
        for s in ("WorkshopDL", "Steam"):
            if s not in self.cfg: self.cfg[s] = {}
        self.cfg["WorkshopDL"]["Anonymous Mode"] = "1" if self.chk_anon.isChecked() else "0"
        self.cfg["Steam"]["Username"] = self.inp_user.text()
        self.cfg["Steam"]["Password"] = self.inp_pass.text()
        if self.inp_steamcmd.text():
            self.cfg["WorkshopDL"]["SteamCMDPath"] = self.inp_steamcmd.text()
        lang = self.inp_lang.text().strip()
        if lang:
            self.cfg["WorkshopDL"]["LangPath"] = lang
        cur_upd = self.cmb_update_paths.currentText().strip()
        if cur_upd:
            self.cfg["WorkshopDL"]["ModsUpdatePath"] = cur_upd
            mod_paths_add(cur_upd)
        self.cfg["WorkshopDL"]["DepsBehavior"] = self.cmb_deps_behavior.currentData()
        self.cfg["WorkshopDL"]["BatchSize"]    = str(self.spn_batch.value())

        # Репозиторий инструкций
        repo_val = self.inp_install_repo.text().strip()
        if repo_val:
            self.cfg["WorkshopDL"]["InstallRepo"] = repo_val
        else:
            self.cfg["WorkshopDL"].pop("InstallRepo", None)
        # Пересчитываем глобальные URL сразу
        global GITHUB_INSTALL_RAW, GITHUB_INSTALL_API
        GITHUB_INSTALL_RAW, GITHUB_INSTALL_API = _install_repo_url(self.cfg)

        save_config(self.cfg)
        QMessageBox.information(self, t("app_title"), t("msg_settings_saved"))

    def _test_install_repo(self):
        """Проверяет доступность репозитория инструкций — делает запрос к API."""
        repo_val = self.inp_install_repo.text().strip()
        # Временно применяем введённое значение для теста
        tmp_cfg = configparser.ConfigParser()
        tmp_cfg["WorkshopDL"] = {"InstallRepo": repo_val} if repo_val else {}
        raw_url, api_url = _install_repo_url(tmp_cfg if repo_val else None)

        self.lbl_repo_status.setText("  ⏳ Проверка...")
        self.lbl_repo_status.setStyleSheet("color: #888;")
        self.btn_repo_test.setEnabled(False)

        def _check():
            try:
                # Пробуем получить список файлов через API
                r = requests.get(api_url, timeout=8)
                if r.status_code == 200:
                    files = r.json()
                    json_count = sum(1 for f in files if isinstance(f, dict)
                                     and f.get("name", "").endswith(".json"))
                    msg = f"  ✅ Репозиторий доступен, найдено {json_count} инструкций"
                    color = "#4CAF50"
                elif r.status_code == 404:
                    msg = "  ❌ Репозиторий или папка не найдены (404)"
                    color = "#f44336"
                else:
                    msg = f"  ⚠ Ответ сервера: {r.status_code}"
                    color = "#FF9800"
            except Exception as e:
                msg   = f"  ❌ Ошибка подключения: {e}"
                color = "#f44336"

            from PyQt5.QtCore import QMetaObject, Q_ARG
            QMetaObject.invokeMethod(self, "_slot_repo_test_result",
                Qt.QueuedConnection,
                Q_ARG(str, msg), Q_ARG(str, color))

        threading.Thread(target=_check, daemon=True).start()

    @pyqtSlot(str, str)
    def _slot_repo_test_result(self, msg: str, color: str):
        self.lbl_repo_status.setText(msg)
        self.lbl_repo_status.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.btn_repo_test.setEnabled(True)

    def _refresh_install_cache_info(self):
        """Обновляет метку с информацией о кеше инструкций."""
        if not os.path.isdir(INSTALL_LOCAL_DIR):
            self.lbl_install_cache_info.setText("кеш пуст")
            return
        files = [f for f in os.listdir(INSTALL_LOCAL_DIR) if f.endswith(".json")]
        total_kb = sum(
            os.path.getsize(os.path.join(INSTALL_LOCAL_DIR, f))
            for f in files
        ) // 1024
        self.lbl_install_cache_info.setText(
            f"кешировано: {len(files)} инструкций, {total_kb} КБ"
        )

    def _clear_install_cache(self):
        """Удаляет кешированные JSON инструкции (не папку plugins/)."""
        if not os.path.isdir(INSTALL_LOCAL_DIR):
            return
        removed = 0
        for f in os.listdir(INSTALL_LOCAL_DIR):
            if f.endswith(".json"):
                try:
                    os.remove(os.path.join(INSTALL_LOCAL_DIR, f))
                    removed += 1
                except Exception:
                    pass
        self.lbl_install_cache_info.setText(f"удалено {removed} файлов")
        QMessageBox.information(self, "WorkshopDL",
            f"Кеш инструкций очищен: удалено {removed} файлов.\n"
            "При следующей установке инструкции будут заново скачаны с GitHub.")



    def _toggle_anon(self):
        anon = self.chk_anon.isChecked()
        self.inp_user.setEnabled(not anon)
        self.inp_pass.setEnabled(not anon)

    # ── Слоты для вызова из фоновых потоков (через сигналы) ───────────────────
    def _slot_set_game_id(self, app_id: str, name: str):
        """Вызывается в главном потоке — безопасно обновляет Game ID."""
        self.inp_game.setText(app_id)
        self._log(t("msg_game_id_found", id=app_id) + (f"  ({name})" if name else ""))
        history_add(app_id, name)
        self._refresh_history()

    def _slot_add_mod_items(self, items: list):
        """Добавляет моды в список — безопасно из фонового потока."""
        for mid in items:
            self.mod_list.addItem(mid)

    def _slot_launch_update(self):
        """Запускает обновление устаревших модов после получения game_id."""
        if self._pending_update_ids:
            self._do_launch_update(self._pending_update_ids)
            self._pending_update_ids = []

    def _browse_steamcmd(self):
        if IS_WIN:
            f, _ = QFileDialog.getOpenFileName(self, "steamcmd.exe", "", "steamcmd.exe (steamcmd.exe)")
        else:
            f, _ = QFileDialog.getOpenFileName(self, STEAMCMD_BIN, "", "All Files (*)")
        if f: self.inp_steamcmd.setText(f)

    def _browse_lang(self):
        path, _ = QFileDialog.getOpenFileName(self, "Файл локализации", "", "JSON (*.json)")
        if path: self.inp_lang.setText(path)

    # ── GitHub языки ──────────────────────────────────────────────────────────
    def _populate_lang_combo_local(self):
        """Заполняет комбо из локально доступных языков."""
        self.cmb_lang.blockSignals(True)
        self.cmb_lang.clear()
        saved_code = cfg_get(self.cfg, "WorkshopDL", "LangCode", "en")
        select_idx = 0
        for i, (code, name, path) in enumerate(lang_list_local()):
            self.cmb_lang.addItem(name, userData=(code, path, True))
            if code == saved_code:
                select_idx = i
        self.cmb_lang.blockSignals(False)
        if self.cmb_lang.count():
            self.cmb_lang.setCurrentIndex(select_idx)

    def _fetch_lang_list(self):
        """Запрашивает список языков с GitHub."""
        self.btn_lang_refresh.setEnabled(False)
        self.lbl_lang_status.setText("  ⟳ Загружаю список с GitHub...")
        self.lbl_lang_status.setStyleSheet("color: #888;")
        self._lang_fetch_worker = LangFetchWorker()
        self._lang_fetch_worker.list_ready.connect(self._on_lang_list_ready)
        self._lang_fetch_worker.start()

    def _on_lang_list_ready(self, remote_list):
        self.btn_lang_refresh.setEnabled(True)
        if not remote_list:
            self.lbl_lang_status.setText("  ⚠  Нет соединения с GitHub")
            self.lbl_lang_status.setStyleSheet("color: #e74c3c;")
            return

        saved_code = cfg_get(self.cfg, "WorkshopDL", "LangCode", "en")
        self.cmb_lang.blockSignals(True)
        self.cmb_lang.clear()
        select_idx = 0
        for i, (code, name, is_local) in enumerate(remote_list):
            # Ищем локальный путь если файл уже скачан
            local_path = lang_local_path(code)
            # Также проверяем рядом со скриптом (lang_XX.json)
            bundled = os.path.join(APP_DIR, f"lang_{code}.json")
            if os.path.exists(bundled):
                local_path = bundled
                is_local = True
            label = f"{name}  {'✅' if is_local else '☁'}"
            self.cmb_lang.addItem(label, userData=(code, local_path if is_local else "", is_local))
            if code == saved_code:
                select_idx = i
        self.cmb_lang.blockSignals(False)
        if self.cmb_lang.count():
            self.cmb_lang.setCurrentIndex(select_idx)

        downloaded = sum(1 for _, _, loc in remote_list if loc)
        total = len(remote_list)
        self.lbl_lang_status.setText(
            f"  ✅ {total} языков на GitHub  |  {downloaded} скачано локально  "
            f"|  ✅ = есть  ☁ = нажмите ⬇ Скачать"
        )
        self.lbl_lang_status.setStyleSheet("color: #27ae60;")

    def _download_selected_lang(self):
        idx = self.cmb_lang.currentIndex()
        if idx < 0: return
        code, local_path, is_local = self.cmb_lang.itemData(idx)
        if is_local and local_path and os.path.exists(local_path):
            self.lbl_lang_status.setText(f"  ✅ Язык уже скачан: {local_path}")
            return
        self.btn_lang_dl.setEnabled(False)
        self._lang_dl_worker = LangFetchWorker(download_code=code)
        self._lang_dl_worker.dl_progress.connect(self.lbl_lang_status.setText)
        self._lang_dl_worker.dl_done.connect(self._on_lang_downloaded)
        self._lang_dl_worker.start()

    def _on_lang_downloaded(self, success, path_or_err):
        self.btn_lang_dl.setEnabled(True)
        if success:
            self.lbl_lang_status.setText(f"  ✅ Скачано: {path_or_err}")
            self.lbl_lang_status.setStyleSheet("color: #27ae60;")
            # Обновляем комбо
            self._fetch_lang_list()
        else:
            self.lbl_lang_status.setText(f"  ❌ Ошибка: {path_or_err}")
            self.lbl_lang_status.setStyleSheet("color: #e74c3c;")

    def _apply_lang_from_combo(self):
        """Применяет язык выбранный в комбо."""
        idx = self.cmb_lang.currentIndex()
        if idx < 0: return
        code, local_path, is_local = self.cmb_lang.itemData(idx)
        if not is_local or not local_path or not os.path.exists(local_path):
            self.lbl_lang_status.setText("  ⚠  Сначала скачайте язык (кнопка ⬇ Скачать)")
            self.lbl_lang_status.setStyleSheet("color: #e74c3c;")
            return
        # Сохраняем код языка в конфиг
        if "WorkshopDL" not in self.cfg: self.cfg["WorkshopDL"] = {}
        self.cfg["WorkshopDL"]["LangCode"] = code
        self.cfg["WorkshopDL"]["LangPath"] = local_path
        save_config(self.cfg)
        self.inp_lang.setText(local_path)
        self._apply_language(path_override=local_path)

    def _apply_language(self, path_override: str = ""):
        """Применяет язык немедленно — пересоздаёт весь UI."""
        path = path_override or self.inp_lang.text().strip()
        if path and not os.path.exists(path):
            QMessageBox.warning(self, t("app_title"),
                f"Файл не найден:\n{path}"); return

        # Сохраняем важные значения до пересоздания UI
        game_id   = self.inp_game.text()
        steamcmd  = self.inp_steamcmd.text()
        lang_path = path
        anon      = self.chk_anon.isChecked()
        user      = self.inp_user.text()
        pwd       = self.inp_pass.text()
        upd_cur   = self.cmb_update_paths.currentText()
        lang_code = cfg_get(self.cfg, "WorkshopDL", "LangCode", "en")

        # Сохраняем путь к языку в конфиг
        if lang_path:
            if "WorkshopDL" not in self.cfg: self.cfg["WorkshopDL"] = {}
            self.cfg["WorkshopDL"]["LangPath"] = lang_path
            save_config(self.cfg)

        lang_load(lang_path)

        # Пересоздаём UI
        old_tab = self.tabs.currentIndex()
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8); root.setContentsMargins(12, 12, 12, 12)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self.tabs.addTab(self._tab_download(), t("tab_download"))
        self.tabs.addTab(self._tab_history(),  t("tab_history"))
        self.tabs.addTab(self._tab_updates(),  t("tab_updates"))
        self.tabs.addTab(self._tab_settings(), t("tab_settings"))

        # Восстанавливаем значения
        self.inp_game.setText(game_id)
        self.inp_steamcmd.setText(steamcmd)
        self.inp_lang.setText(lang_path)
        self.chk_anon.setChecked(anon)
        self.inp_user.setText(user)
        self.inp_pass.setText(pwd)
        self._reload_update_paths_combo(upd_cur)
        self._toggle_anon()
        self._refresh_history()
        self._refresh_steamcmd_status()
        self._populate_lang_combo_local()
        self.tabs.setCurrentIndex(old_tab)
        self.setWindowTitle(t("app_title"))

    def _refresh_steamcmd_status(self):
        exe = self._get_steamcmd()
        if os.path.exists(exe):
            self.lbl_steamcmd_status.setText(f"✅  {exe}")
            self.lbl_steamcmd_status.setStyleSheet("color: #27ae60; font-weight: bold;")
        else:
            self.lbl_steamcmd_status.setText(t("steamcmd_not_found"))
            self.lbl_steamcmd_status.setStyleSheet("color: #e74c3c;")

    def _download_steamcmd(self):
        self.btn_dl_steamcmd.setEnabled(False)
        self.pb_steamcmd.setVisible(True)
        self.pb_steamcmd.setValue(0)
        self.log_steamcmd.clear()
        self.log_steamcmd.setVisible(True)
        self.lbl_steamcmd_dl.setText(t("steamcmd_dl_downloading"))
        self.lbl_steamcmd_dl.setStyleSheet("")

        self._scmd_installer = SteamCMDInstallWorker()
        self._scmd_installer.status.connect(self.lbl_steamcmd_dl.setText)
        self._scmd_installer.percent.connect(self.pb_steamcmd.setValue)
        self._scmd_installer.log_line.connect(self._steamcmd_log_line)
        self._scmd_installer.done.connect(self._on_steamcmd_installed)
        self._scmd_installer.start()

    def _steamcmd_log_line(self, line: str):
        self.log_steamcmd.append(line)
        self.log_steamcmd.verticalScrollBar().setValue(
            self.log_steamcmd.verticalScrollBar().maximum()
        )

    def _on_steamcmd_installed(self, success, path_or_err):
        self.btn_dl_steamcmd.setEnabled(True)
        self.pb_steamcmd.setVisible(False)
        if success:
            self.inp_steamcmd.setText(path_or_err)
            self.lbl_steamcmd_dl.setText(t("steamcmd_dl_done"))
            self.lbl_steamcmd_dl.setStyleSheet("color: #27ae60; font-weight: bold;")
            self._refresh_steamcmd_status()
            if "WorkshopDL" not in self.cfg: self.cfg["WorkshopDL"] = {}
            self.cfg["WorkshopDL"]["SteamCMDPath"] = path_or_err
            save_config(self.cfg)
        else:
            self.lbl_steamcmd_dl.setText(t("steamcmd_dl_error", err=path_or_err))
            self.lbl_steamcmd_dl.setStyleSheet("color: #e74c3c;")

    def _clear_steamcmd_cache(self):
        """Удаляет userdata/ и steamapps/ внутри папки steamcmd."""
        steamcmd_dir = os.path.dirname(self._get_steamcmd())
        targets = [
            os.path.join(steamcmd_dir, "userdata"),
            os.path.join(steamcmd_dir, "steamapps"),
        ]
        existing = [p for p in targets if os.path.exists(p)]
        if not existing:
            self.lbl_cache_status.setText("✅ Кеш уже чистый")
            self.lbl_cache_status.setStyleSheet("color: #27ae60;")
            return
        reply = QMessageBox.question(
            self, "Очистка кеша SteamCMD",
            "Будут удалены:\n" + "\n".join(f"  • {p}" for p in existing) +
            "\n\nПродолжить?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes: return
        errors = []
        for p in existing:
            try:
                shutil.rmtree(p)
            except Exception as e:
                errors.append(str(e))
        if errors:
            self.lbl_cache_status.setText(f"⚠ Ошибка: {errors[0]}")
            self.lbl_cache_status.setStyleSheet("color: #e74c3c;")
        else:
            self.lbl_cache_status.setText("✅ Кеш очищен")
            self.lbl_cache_status.setStyleSheet("color: #27ae60;")

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _extract_id(self, text):
        m = re.search(r"\d{5,}", text)
        return m.group(0) if m else text.strip()

    def _get_steamcmd(self):
        p = self.inp_steamcmd.text().strip()
        return p if p else STEAMCMD_DEF

    def _log(self, text):
        self.log.append(text)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    # ── Список модов ─────────────────────────────────────────────────────────
    def _on_mod_id_changed(self, text):
        mid = self._extract_id(text)
        if len(mid) >= 7 and not self.inp_game.text().strip():
            def _bg():
                app_id, name = fetch_game_id_for_mod(mid)
                if app_id:
                    self._sig_set_game_id.emit(app_id, name)
            threading.Thread(target=_bg, daemon=True).start()

    def _add_to_list(self):
        raw = self.inp_ws.text().strip()
        if not raw: return
        mid = self._extract_id(raw)
        if mid: self.mod_list.addItem(mid); self.inp_ws.clear()

    def _remove_selected(self):
        for item in self.mod_list.selectedItems():
            self.mod_list.takeItem(self.mod_list.row(item))

    def _import_txt(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт", "", "Text Files (*.txt)")
        if not path: return
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                mid = self._extract_id(line.strip())
                if mid: self.mod_list.addItem(mid)
        self._log(t("msg_import_done", path=path))

    def _import_collection(self):
        raw = self.inp_col.text().strip()
        if not raw: return
        col_id = self._extract_id(raw)
        self._log(t("msg_collection_loading", id=col_id))
        def _bg():
            ids = fetch_collection(col_id)
            if not ids:
                self._sig_log.emit(t("msg_collection_fail")); return
            self._sig_add_mod_items.emit(ids)
            self._sig_log.emit(t("msg_collection_done", count=len(ids)))
            if ids:
                app_id, name = fetch_game_id_for_mod(ids[0])
                if app_id:
                    self._sig_set_game_id.emit(app_id, name)
        threading.Thread(target=_bg, daemon=True).start()

    def _auto_find_game(self):
        mid = (self.mod_list.item(0).text() if self.mod_list.count() > 0
               else self._extract_id(self.inp_ws.text()))
        if not mid: QMessageBox.warning(self, t("app_title"), t("msg_add_mod_first")); return
        self._log(t("msg_searching_game_id", id=mid))
        def _bg():
            app_id, name = fetch_game_id_for_mod(mid)
            if app_id:
                self._sig_set_game_id.emit(app_id, name)
            else:
                self._sig_log.emit(t("msg_game_id_not_found"))
        threading.Thread(target=_bg, daemon=True).start()

    # ── История ───────────────────────────────────────────────────────────────
    def _scan_and_refresh_history(self):
        base = os.path.dirname(self._get_steamcmd())
        history_scan_from_disk(os.path.join(base, "steamapps", "workshop", "content"))
        self._refresh_history()

    def _refresh_history(self):
        self.history_list.clear()
        for gid, name in history_load().items():
            label = f"{name}  [{gid}]" if name != gid else f"[{gid}]"
            item = QListWidgetItem(label); item.setData(Qt.UserRole, gid)
            self.history_list.addItem(item)

    def _history_use(self):
        item = self.history_list.currentItem()
        if item: self.inp_game.setText(item.data(Qt.UserRole))

    def _history_open_folder(self):
        item = self.history_list.currentItem()
        if not item: return
        gid = item.data(Qt.UserRole)
        base = os.path.dirname(self._get_steamcmd())
        folder = os.path.join(base, "steamapps", "workshop", "content", gid)
        if not open_folder(folder):
            QMessageBox.information(self, t("app_title"), t("msg_folder_not_found", path=folder))

    def _history_delete(self):
        item = self.history_list.currentItem()
        if not item: return
        data = history_load(); data.pop(item.data(Qt.UserRole), None)
        history_save(data); self._refresh_history()

    # ── Проверка незавершённой загрузки ───────────────────────────────────────
    def _check_resume(self):
        q = queue_load()
        if not q: return
        done = q.get("done_count", 0); total = len(q.get("mod_ids", []))
        reply = QMessageBox.question(self, t("msg_resume_title"),
            t("msg_resume_text", game_id=q["game_id"], done=done,
              total=total, remaining=total-done),
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.inp_game.setText(q["game_id"]); self.mod_list.clear()
            for mid in q["mod_ids"]: self.mod_list.addItem(mid)
            self._start_download(resume_from=done)
        else:
            queue_clear()

    # ── Скачка ────────────────────────────────────────────────────────────────
    def _start_download(self, resume_from=0):
        game_id = self.inp_game.text().strip()
        if not game_id: QMessageBox.warning(self, t("app_title"), t("msg_no_game_id")); return
        mod_ids = [self.mod_list.item(i).text() for i in range(self.mod_list.count())]
        if not mod_ids:
            single = self._extract_id(self.inp_ws.text().strip())
            if single: mod_ids = [single]
        if not mod_ids: QMessageBox.warning(self, t("app_title"), t("msg_no_mods")); return
        anon = self.chk_anon.isChecked(); user = self.inp_user.text(); pwd = self.inp_pass.text()
        if not anon and (not user or not pwd):
            QMessageBox.warning(self, t("app_title"), t("msg_no_credentials")); return
        steamcmd = self._get_steamcmd()
        if not os.path.exists(steamcmd):
            QMessageBox.critical(self, t("app_title"), t("msg_steamcmd_missing", path=steamcmd)); return

        n = len(mod_ids)
        self.progress_bar.setMaximum(n); self.progress_bar.setValue(resume_from)
        self.progress_bar.setFormat(f"%v / {n}")
        if not resume_from: self.log.clear()
        self._log(t("log_start", count=n, game_id=game_id)
                  + (t("log_resume", n=resume_from+1) if resume_from else ""))
        self.btn_download.setEnabled(False); self.btn_pause.setEnabled(True); self.btn_cancel.setEnabled(True)
        history_add(game_id); self._refresh_history()
        batch_size = int(cfg_get(self.cfg, "WorkshopDL", "BatchSize", "1"))
        self.worker = DownloadWorker(steamcmd, game_id, mod_ids, anon, user, pwd,
                                     start_from=resume_from, batch_size=batch_size)
        self.worker.log_line.connect(self._log)
        self.worker.progress.connect(lambda cur, tot: self.progress_bar.setValue(cur))
        self.worker.finished.connect(self._on_finished)
        self.worker.deps_found.connect(self._on_deps_found)
        self.worker.paused.connect(self._on_paused)
        self.worker.start()

    def _pause_download(self):
        if self.worker: self.worker.pause(); self._log(t("log_paused"))
        self.btn_pause.setEnabled(False)

    def _cancel_download(self):
        if self.worker: self.worker.stop(); self._log(t("msg_cancelled"))
        self.btn_download.setEnabled(True); self.btn_pause.setEnabled(False); self.btn_cancel.setEnabled(False)

    def _on_paused(self, remaining):
        self.btn_download.setEnabled(True); self.btn_pause.setEnabled(False); self.btn_cancel.setEnabled(False)
        self._log(t("log_paused_remaining", remaining=remaining))
        QMessageBox.information(self, t("app_title"), t("msg_paused", remaining=remaining))

    def _on_finished(self, success, fail):
        self.btn_download.setEnabled(True); self.btn_pause.setEnabled(False); self.btn_cancel.setEnabled(False)
        self._log("\n" + t("log_separator"))
        self._log(t("log_result", success=success, fail=fail))
        self._log(t("log_separator"))
        game_id = self.inp_game.text().strip()
        base = os.path.dirname(self._get_steamcmd())
        folder = os.path.join(base, "steamapps", "workshop", "content", game_id)
        self._scan_and_refresh_history()
        reply = QMessageBox.question(self, t("app_title"),
            t("msg_finished", success=success, fail=fail),
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            if not open_folder(folder):
                QMessageBox.warning(self, t("app_title"), t("msg_folder_not_found", path=folder))

        # ── Предложить установку если есть инструкция ─────────────────────
        if success > 0:
            self._offer_install(game_id, folder)

    # ── Установка модов ───────────────────────────────────────────────────────

    def _offer_install(self, game_id: str, content_folder: str):
        """
        Вызывается после скачивания.
        Проверяет наличие инструкции на GitHub — если есть, предлагает установить.
        """
        self._log("🔍 Проверяю инструкцию установки...")
        cfg = self.cfg

        def _bg():
            recipe = install_fetch_recipe(game_id, cfg=cfg)
            if recipe:
                self._sig_log.emit(
                    f"📥 Найдена инструкция установки для игры {game_id} "
                    f"({recipe.get('game_name', '')})"
                )
                from PyQt5.QtCore import QMetaObject, Q_ARG
                QMetaObject.invokeMethod(
                    self, "_slot_open_install_dialog",
                    Qt.QueuedConnection,
                    Q_ARG(str, game_id),
                    Q_ARG(str, content_folder),
                )
            else:
                self._sig_log.emit(
                    f"ℹ Инструкции установки для игры {game_id} нет — "
                    f"моды остаются в папке загрузки"
                )

        threading.Thread(target=_bg, daemon=True).start()

    @pyqtSlot(str, str)
    def _slot_open_install_dialog(self, game_id: str, content_folder: str):
        """Открывает диалог установки (всегда из главного потока)."""
        recipe = install_fetch_recipe(game_id, cfg=self.cfg)
        if not recipe:
            return

        # ── Строим расширенный контекст ───────────────────────────────────────
        game_name       = history_get_name(game_id)
        history_folder  = history_get_game_folder(game_id)   # из истории если уже знаем
        steamcmd_root   = os.path.dirname(self._get_steamcmd())  # папка steamcmd

        extra_ctx = {
            # Идентификаторы игры
            "game_id":   game_id,
            "game_name": game_name,

            # Папки
            "game_folder":   history_folder,   # "" если неизвестно — найдёт find_game_folder
            "content_folder": content_folder,  # steamapps/workshop/content/<game_id>
            "steamcmd_root": steamcmd_root,

            # Системные пути (удобно в шаблонах)
            "STEAM": _find_steam_path(),
        }

        # Если из истории есть папка игры — сразу показываем пользователю
        if history_folder:
            self._log(f"📂 Папка игры из истории: {history_folder}")
        else:
            self._log(f"ℹ Папка игры для {game_name} неизвестна — будет найдена при установке")

        # ── Спрашиваем пользователя ───────────────────────────────────────────
        hist_note = f"\n\n📂 Папка игры: {history_folder}" if history_folder else ""
        reply = QMessageBox.question(
            self, "📥 Установка модов",
            f"Найдена инструкция установки для игры:\n"
            f"<b>{game_name}</b>  (App ID: {game_id})\n\n"
            f"{recipe.get('description', '')}{hist_note}\n\n"
            f"Установить скачанные моды прямо сейчас?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            self._log("⏭ Установка пропущена пользователем")
            return

        # ── Собираем папки модов ──────────────────────────────────────────────
        mod_ids = [self.mod_list.item(i).text() for i in range(self.mod_list.count())]
        mod_folders = {}
        for mid in mod_ids:
            candidate = os.path.join(content_folder, mid)
            if os.path.isdir(candidate):
                mod_folders[mid] = candidate
            else:
                for dirpath, dirs, _ in os.walk(content_folder):
                    if os.path.basename(dirpath) == mid:
                        mod_folders[mid] = dirpath
                        break

        if not mod_folders:
            self._log(f"⚠ Папки модов не найдены в {content_folder}")
            return

        self._log(f"📂 Найдено {len(mod_folders)} папок модов для установки")

        # Добавляем список mod_id и счётчики в контекст
        # (mod_index / mod_number / mod_total выставляются per-мод в InstallWorker)
        extra_ctx["mod_ids_list"] = list(mod_folders.keys())
        extra_ctx["mod_total"]    = str(len(mod_folders))
        extra_ctx["mod_count"]    = str(len(mod_folders))   # синоним для удобства

        dlg = InstallDialog(recipe, mod_folders, extra_ctx=extra_ctx, parent=self)
        dlg.exec_()

        self._log("\n" + "─" * 50)
        self._log("Лог установки доступен в окне установщика выше.")

    # ── Проверка обновлений: пути ─────────────────────────────────────────────
    def _browse_update_path(self):
        path = QFileDialog.getExistingDirectory(self, "Выбери папку с модами")
        if path:
            mod_paths_add(path); self._reload_update_paths_combo(path)

    def _delete_update_path(self):
        cur = self.cmb_update_paths.currentText().strip()
        if not cur: return
        paths = mod_paths_load()
        if cur in paths: paths.remove(cur); mod_paths_save(paths)
        self._reload_update_paths_combo()

    def _reload_update_paths_combo(self, select=""):
        self.cmb_update_paths.blockSignals(True); self.cmb_update_paths.clear()
        for p in mod_paths_load(): self.cmb_update_paths.addItem(p)
        if select: self.cmb_update_paths.setCurrentText(select)
        self.cmb_update_paths.blockSignals(False)

    def _toggle_date_columns(self):
        show = self.chk_show_dates.isChecked()
        self.upd_table.setColumnHidden(6, not show)
        self.upd_table.setColumnHidden(7, not show)

    # ── Проверка обновлений: старт ────────────────────────────────────────────
    def _start_update_check(self):
        path = self.cmb_update_paths.currentText().strip()
        if not path or not os.path.isdir(path):
            QMessageBox.warning(self, t("app_title"), t("msg_invalid_folder")); return
        mod_paths_add(path); self._reload_update_paths_combo(path)
        self.upd_table.setSortingEnabled(False)
        self.upd_table.setRowCount(0)
        self._upd_rows.clear(); self._outdated_ids = []
        self.upd_progress.setValue(0)
        for b in [self.btn_check_upd, self.btn_update_all, self.btn_update_sel,
                  self.btn_enable_all, self.btn_disable_all]:
            b.setEnabled(False)
        self.upd_status.setText(t("msg_checking"))
        self.upd_worker = UpdateCheckWorker(path)
        self.upd_worker.progress.connect(lambda c, m: (self.upd_progress.setMaximum(m), self.upd_progress.setValue(c)))
        self.upd_worker.mod_result.connect(self._on_upd_result)
        self.upd_worker.finished.connect(self._on_upd_finished)
        self.upd_worker.missing_deps.connect(self._on_missing_deps_found)
        self.upd_worker.start()

    # ── Проверка обновлений: результат ────────────────────────────────────────
    def _on_upd_result(self, mod_id, title, local_ts, server_ts, status, folder, size_mb, mod_missing):
        local_dt  = datetime.datetime.fromtimestamp(local_ts).strftime("%Y-%m-%d %H:%M") if local_ts else "—"
        server_dt = datetime.datetime.fromtimestamp(server_ts).strftime("%Y-%m-%d %H:%M") if server_ts else "—"

        COLOR = {"outdated": "#fde8e8", "ok": "#e8fde8",
                 "disabled": "#f0f0f0", "unknown": "#fafafa"}
        ICON  = {"outdated": "🔴", "ok": "🟢", "disabled": "🔘", "unknown": "⚪"}
        SORT  = {"outdated": "0",  "ok": "2",  "disabled": "3",  "unknown": "1"}

        if status == "outdated": self._outdated_ids.append(mod_id)
        row_color = QColor(COLOR[status])

        row = self.upd_table.rowCount()
        self.upd_table.insertRow(row)
        self._upd_rows[mod_id] = row

        def cell(text, sort_val=None, align=Qt.AlignCenter):
            it = QTableWidgetItem(text)
            it.setBackground(QBrush(row_color))
            it.setTextAlignment(align)
            if sort_val is not None: it.setData(Qt.UserRole, sort_val)
            return it

        # 0: статус — если есть незагруженные зависимости добавляем ⚠
        has_missing = bool(mod_missing)
        status_icon = ICON[status] + (" ⚠" if has_missing else "")
        st_item = cell(status_icon, SORT[status])
        tip = t(f"status_{status}")
        if has_missing:
            deps_text = "\n".join(f"  • {mid}: {name}" for mid, name in mod_missing)
            tip += f"\n\n⚠ Отсутствующие зависимости ({len(mod_missing)}):\n{deps_text}"
        st_item.setToolTip(tip)
        # 1: название
        name_item = QTableWidgetItem(title if title != mod_id else "—")
        name_item.setBackground(QBrush(row_color))
        name_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if has_missing:
            name_item.setToolTip(f"⚠ {len(mod_missing)} зависимост(ей) не скачаны")
        # 2: размер
        size_str = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{size_mb*1024:.0f} KB"
        sz_item = cell(size_str, size_mb)
        # 3: Steam ссылка
        steam_item = cell("🔗", mod_id)
        steam_item.setForeground(QBrush(QColor("#1a73e8")))
        steam_item.setToolTip(f"steamcommunity.com/sharedfiles/filedetails/?id={mod_id}")
        # 4: вкл/выкл
        toggle_label = "▶ Включить" if status == "disabled" else "⏸ Выкл"
        tog_item = cell(toggle_label, mod_id)
        tog_item.setForeground(QBrush(QColor("#2980b9")))
        tog_item.setData(Qt.UserRole + 1, folder)
        # 5: папка
        folder_item = cell("📁", mod_id)
        folder_item.setForeground(QBrush(QColor("#27ae60")))
        folder_item.setToolTip(folder)
        # 6: дата лок
        loc_item = cell(local_dt, int(local_ts) if local_ts else 0)
        # 7: дата сервер
        srv_item = cell(server_dt, server_ts)

        for col, item in enumerate([st_item, name_item, sz_item, steam_item,
                                     tog_item, folder_item, loc_item, srv_item]):
            self.upd_table.setItem(row, col, item)

        if status == "outdated":
            f = QFont(); f.setBold(True)
            for col in [0, 1, 2]: self.upd_table.item(row, col).setFont(f)

    def _on_upd_finished(self, outdated, ok_count):
        self.upd_table.setSortingEnabled(True)
        self.upd_table.sortByColumn(0, Qt.AscendingOrder)
        self.btn_check_upd.setEnabled(True)
        disabled = sum(1 for r in range(self.upd_table.rowCount())
                       if self.upd_table.item(r, 0) and self.upd_table.item(r, 0).text().startswith("🔘"))
        has_outdated = bool(self._outdated_ids)
        self.btn_update_all.setEnabled(has_outdated)
        self.btn_update_sel.setEnabled(has_outdated)
        self.btn_enable_all.setEnabled(True)
        self.btn_disable_all.setEnabled(True)
        total = self.upd_table.rowCount()
        self.upd_status.setText(
            t("upd_status_template", total=total, outdated=outdated,
              ok=ok_count, disabled=disabled)
        )

    def _on_missing_deps_found(self, deps: dict):
        """Вызывается когда проверка обновлений нашла незагруженные зависимости."""
        self._show_deps_dialog(deps, source="updates")

    def _on_deps_found(self, deps: dict):
        """Вызывается когда воркер скачки нашёл зависимости до старта."""
        self._show_deps_dialog(deps, source="download")

    def _show_deps_dialog(self, deps: dict, source: str):
        """Показывает диалог с найденными зависимостями и предлагает скачать."""
        if not deps: return

        behavior = cfg_get(self.cfg, "WorkshopDL", "DepsBehavior", "ask")

        # Молча скачиваем
        if behavior == "auto":
            self._add_deps_to_list(deps)
            self._log(f"🔗 Авто: добавлено {len(deps)} зависимост(ей) → нажмите ⬇ Скачать")
            return

        # Молча пропускаем
        if behavior == "skip":
            self._log(f"🔗 Пропущено {len(deps)} зависимост(ей) (настройка: всегда пропускать)")
            return

        # Спрашиваем (behavior == "ask")
        lines = "\n".join(f"  • {name}  (ID: {mid})" for mid, name in list(deps.items())[:20])
        if len(deps) > 20:
            lines += f"\n  ... и ещё {len(deps) - 20}"

        msg = QMessageBox(self)
        msg.setWindowTitle("🔗 Зависимости модов")
        msg.setIcon(QMessageBox.Question)
        msg.setText(
            f"Найдено <b>{len(deps)}</b> зависимост(ей) которых нет локально:\n\n"
            f"{lines}\n\n"
            f"Скачать их?"
        )
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.Yes)
        if msg.exec_() == QMessageBox.Yes:
            self._add_deps_to_list(deps)

    def _add_deps_to_list(self, deps: dict):
        """Добавляет зависимости в список и переключается на вкладку Download."""
        existing = {self.mod_list.item(i).text() for i in range(self.mod_list.count())}
        added = 0
        for mid in deps:
            if mid not in existing:
                self.mod_list.addItem(mid)
                added += 1
        if added:
            self.tabs.setCurrentIndex(0)
            self._log(f"🔗 Добавлено {added} зависимост(ей) — нажмите ⬇ Скачать")

    # ── Клики по таблице ─────────────────────────────────────────────────────
    def _upd_table_clicked(self, row, col):
        if col == 3:   # Steam
            id_item = self.upd_table.item(row, 2)
            if id_item:
                QDesktopServices.openUrl(QUrl(
                    f"https://steamcommunity.com/sharedfiles/filedetails/?id={id_item.text()}"))
        elif col == 4:  # Вкл/Выкл
            tog = self.upd_table.item(row, 4)
            if tog:
                mod_id = tog.data(Qt.UserRole)
                folder = tog.data(Qt.UserRole + 1)
                new_folder = mod_toggle(folder)
                # Обновляем кнопку и статус
                was_disabled = folder.endswith(DISABLED_SUFFIX)
                new_status = "ok" if was_disabled else "disabled"
                new_icon   = "🔘" if not was_disabled else "🟢"
                new_lbl    = "▶ Включить" if not was_disabled else "⏸ Выкл"
                self.upd_table.item(row, 0).setText(new_icon)
                tog.setText(new_lbl)
                tog.setData(Qt.UserRole + 1, new_folder)
        elif col == 5:  # Папка
            fold_item = self.upd_table.item(row, 4)  # папка хранится в col 4 UserRole+1
            if fold_item:
                folder = fold_item.data(Qt.UserRole + 1)
                if folder and os.path.isdir(folder):
                    open_folder(folder)

    # ── Включить/Выключить все ────────────────────────────────────────────────
    def _toggle_all_mods(self, enable: bool):
        for row in range(self.upd_table.rowCount()):
            tog = self.upd_table.item(row, 4)
            if not tog: continue
            folder = tog.data(Qt.UserRole + 1)
            if not folder: continue
            is_disabled = folder.endswith(DISABLED_SUFFIX)
            if enable and is_disabled:
                new_folder = mod_toggle(folder)
                tog.setData(Qt.UserRole + 1, new_folder)
                tog.setText("⏸ Выкл")
                self.upd_table.item(row, 0).setText("🟢")
            elif not enable and not is_disabled:
                new_folder = mod_toggle(folder)
                tog.setData(Qt.UserRole + 1, new_folder)
                tog.setText("▶ Включить")
                self.upd_table.item(row, 0).setText("🔘")

    # ── Скачать устаревшие ────────────────────────────────────────────────────
    def _update_all_outdated(self):
        if self._outdated_ids: self._launch_update_download(list(self._outdated_ids))

    def _update_selected_outdated(self):
        sel = set()
        for idx in self.upd_table.selectedIndexes():
            id_item = self.upd_table.item(idx.row(), 3)
            if id_item:
                mid = id_item.data(Qt.UserRole)
                if mid in self._outdated_ids: sel.add(mid)
        if not sel:
            QMessageBox.information(self, t("app_title"), t("msg_no_outdated_selected")); return
        self._launch_update_download(list(sel))

    def _launch_update_download(self, mod_ids):
        game_id = self.inp_game.text().strip()
        if not game_id and mod_ids:
            self.upd_status.setText(t("msg_searching_game_id", id=mod_ids[0]))
            def _bg():
                app_id, name = fetch_game_id_for_mod(mod_ids[0])
                if app_id:
                    self._sig_set_game_id.emit(app_id, name)
                    # _do_launch_update должен выполняться в главном потоке
                    # используем однократное соединение через лямбду
                    self._sig_log.emit("")   # триггер — выполнится после set_game_id
                    self._pending_update_ids = mod_ids
                    self._sig_launch_update.emit()
                else:
                    self._sig_log.emit(t("msg_no_game_id_auto"))
            threading.Thread(target=_bg, daemon=True).start()
        else:
            self._do_launch_update(mod_ids)

    def _do_launch_update(self, mod_ids):
        self.mod_list.clear()
        for mid in mod_ids: self.mod_list.addItem(mid)
        self.tabs.setCurrentIndex(0)
        self._start_download()

# ── Точка входа ───────────────────────────────────────────────────────────────
def main():
    os.makedirs(MODULES_PATH, exist_ok=True)
    lang_load()   # грузим русский по умолчанию
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
