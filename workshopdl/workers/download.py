"""
Воркер скачки модов через SteamCMD.
"""

import os, subprocess, re, requests
from PyQt5.QtCore import QThread, pyqtSignal

from workshopdl.config import IS_WIN
from workshopdl.localization import t
from workshopdl.steam_api import fetch_dependencies, fetch_mod_details_batch
from workshopdl.storage import queue_save, queue_clear


class DownloadWorker(QThread):
    log_line   = pyqtSignal(str)
    progress   = pyqtSignal(int, int)
    finished   = pyqtSignal(int, int)
    paused     = pyqtSignal(int)
    deps_found = pyqtSignal(dict)

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
        if self.start_from == 0:
            self.log_line.emit(t("deps_checking"))
            try:
                all_deps = fetch_dependencies(self.mod_ids)
                known    = set(self.mod_ids)
                new_deps = {k: v for k, v in all_deps.items() if k not in known}
                if new_deps:
                    self.log_line.emit(t("deps_found", count=len(new_deps)))
                    self.deps_found.emit(new_deps)
                else:
                    self.log_line.emit(t("deps_none"))
            except Exception as e:
                self.log_line.emit(t("deps_fail", err=str(e)))

        total   = len(self.mod_ids)
        pending = [m for i, m in enumerate(self.mod_ids, 1) if i > self.start_from]
        success = self.start_from
        fail    = 0
        done    = self.start_from

        for batch_start in range(0, len(pending), self.batch_size):
            if self._stop:
                queue_clear(); break
            if self._pause:
                queue_save(self.game_id, self.mod_ids, done)
                self.paused.emit(total - done)
                return

            batch = pending[batch_start : batch_start + self.batch_size]

            if self.batch_size == 1:
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
                first = done + 1
                last  = done + len(batch)
                self.log_line.emit(
                    t("log_batch_start", first=first, last=last, total=total, count=len(batch))
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
        args = ([self.steamcmd, "+login", "anonymous"] if self.anonymous
                else [self.steamcmd, "+login", self.username, self.password])
        for mid in mod_ids:
            args += ["+workshop_download_item", self.game_id, mid]
        args += ["+quit"]

        results = {mid: False for mid in mod_ids}
        try:
            clean_env = os.environ.copy()
            clean_env.pop("LD_LIBRARY_PATH", None)
            clean_env.pop("LD_PRELOAD", None)

            flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
            proc  = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", creationflags=flags,
                env=clean_env
            )

            for line in proc.stdout:
                line = line.rstrip()
                if line: self.log_line.emit(line)
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
        try:
            details = fetch_mod_details_batch([mod_id])
            info    = details.get(mod_id)
            if not info:
                self.log_line.emit(t("diag_not_found", mod_id=mod_id))
                return
            
            title = info.get("title", mod_id)
            r = requests.post(
                "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
                data={"itemcount": "1", "publishedfileids[0]": mod_id}, timeout=8
            )
            item = r.json()["response"]["publishedfiledetails"][0]
            result_code = item.get("result", 0)
            visibility  = item.get("visibility", 0)
            banned      = item.get("banned", False)
            ban_reason  = item.get("ban_reason", "")

            if banned:
                self.log_line.emit(t("diag_banned", title=title, reason=ban_reason))
            elif visibility == 2:
                self.log_line.emit(t("diag_private", title=title))
            elif visibility == 1:
                self.log_line.emit(t("diag_friends", title=title))
            elif result_code != 1:
                self.log_line.emit(t("diag_steam_error", title=title, code=result_code))
            else:
                self.log_line.emit(t("diag_requires_ownership", title=title))
        except Exception:
            pass
