"""
WorkshopDL — Python Edition v3
Полный аналог WorkshopDL с улучшенным интерфейсом:
- Система локализации (JSON-файлы)
- Таблица модов с кнопками: Steam / Вкл-Выкл / Открыть папку
- Отключение модов (переименование папки .disabled)
- Скрываемые столбцы дат
- Размер мода в таблице
- Пауза / продолжение, история игр, автопоиск Game ID
"""

import sys, os, re, json, subprocess, threading, configparser, datetime, shutil
import zipfile, urllib.request
import requests
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QListWidget, QListWidgetItem, QLabel,
    QTextEdit, QGroupBox, QCheckBox, QTabWidget, QMessageBox,
    QFileDialog, QProgressBar, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSizePolicy, QAction, QToolBar, QSpinBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QUrl
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
def history_load():
    if not os.path.exists(HISTORY_PATH):
        return {}
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def history_save(data):
    os.makedirs(MODULES_PATH, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

def history_add(game_id, game_name=""):
    data = history_load()
    if game_id not in data or (game_name and data[game_id] == game_id):
        data[game_id] = game_name or game_id
        history_save(data)

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
LANG_LOCAL_DIR   = os.path.join(MODULES_PATH, "lang")   # куда сохраняем скачанные языки

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


# ── Главное окно ──────────────────────────────────────────────────────────────
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

        lay.addWidget(btn_save); lay.addStretch()
        return w

    # ── Настройки load/save ───────────────────────────────────────────────────
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

        # Загружаем поведение зависимостей
        deps_behavior = cfg_get(self.cfg, "WorkshopDL", "DepsBehavior", "ask")
        for i in range(self.cmb_deps_behavior.count()):
            if self.cmb_deps_behavior.itemData(i) == deps_behavior:
                self.cmb_deps_behavior.setCurrentIndex(i)
                break

        # Размер пачки
        try:
            self.spn_batch.setValue(int(cfg_get(self.cfg, "WorkshopDL", "BatchSize", "1")))
        except Exception:
            pass

        # Загружаем сохранённый язык
        lang_path = cfg_get(self.cfg, "WorkshopDL", "LangPath")
        if lang_path and os.path.exists(lang_path):
            self.inp_lang.setText(lang_path)
            lang_load(lang_path)
        else:
            # Ищем язык по коду
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
        save_config(self.cfg)
        QMessageBox.information(self, t("app_title"), t("msg_settings_saved"))

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
