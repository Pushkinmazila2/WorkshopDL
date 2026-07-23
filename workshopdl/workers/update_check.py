"""
Воркер проверки обновлений модов.
"""

import os
from PyQt5.QtCore import QThread, pyqtSignal

from workshopdl.config import DISABLED_SUFFIX, mod_is_disabled, folder_size_mb
from workshopdl.steam_api import fetch_mod_details_batch


class UpdateCheckWorker(QThread):
    mod_result   = pyqtSignal(str, str, float, int, str, str, float, list)
    progress     = pyqtSignal(int, int)
    finished     = pyqtSignal(int, int)
    missing_deps = pyqtSignal(dict)

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

        all_missing_deps = {}
        for mid, info in server_data.items():
            for child_id in info.get("children", []):
                if child_id not in local_set and child_id not in all_missing_deps:
                    child_info = server_data.get(child_id)
                    all_missing_deps[child_id] = child_info["title"] if child_info else child_id

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