"""
Фоновый воркер установки (пакетная установка нескольких модов).
"""

from PyQt5.QtCore import QThread, pyqtSignal

from workshopdl.storage import history_set_game_folder
from workshopdl.installer.installer import ModInstaller


class InstallWorker(QThread):
    log_line   = pyqtSignal(str)
    progress   = pyqtSignal(int, int)
    mod_status = pyqtSignal(str, bool)
    finished   = pyqtSignal(int, int)

    def __init__(self, recipe: dict, mod_folders: dict, user_answers: dict,
                 extra_ctx: dict = None):
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

            per_mod_ctx = {
                **self.extra_ctx,
                "mod_id": mod_id,
                "mod_index":    str(i - 1),
                "mod_number":   str(i),
                "mod_total":    str(total),
                "mod_is_first": "true" if i == 1     else "false",
                "mod_is_last":  "true" if i == total else "false",
            }

            installer = ModInstaller(
                self.recipe, folder,
                self.log_line.emit,
                user_answers=self.user_answers,
                extra_ctx=per_mod_ctx,
            )

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