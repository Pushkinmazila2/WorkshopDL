"""
Хранилище данных: очередь, история, пути к модам.
"""

import os, json, datetime

from workshopdl.config import MODULES_PATH, QUEUE_PATH, HISTORY_PATH, MOD_PATHS_PATH

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