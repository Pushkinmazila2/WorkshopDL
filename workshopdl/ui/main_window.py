"""
Главное окно WorkshopDL.

Этот файл содержит тонкий класс MainWindow, который наследуется от
всех mixin-классов для отдельных вкладок. Логика каждой вкладки
вынесена в отдельный файл:
    - download_tab.py   (DownloadTabMixin)
    - history_tab.py    (HistoryTabMixin)
    - updates_tab.py    (UpdatesTabMixin)
    - settings_tab.py   (SettingsTabMixin)
"""

import os, re, threading
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QTabWidget, QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot, QMetaObject, Q_ARG

from workshopdl.config import (
    STEAMCMD_DEF, APP_DIR, load_config, cfg_get, open_folder,
    DISABLED_SUFFIX, mod_toggle,
    install_repo_url, GITHUB_INSTALL_RAW, GITHUB_INSTALL_API,
)
from workshopdl.localization import t
from workshopdl.storage import (
    history_add, history_get_name, history_get_game_folder,
    mod_paths_add,
)
from workshopdl.installer import install_fetch_recipe
from workshopdl.installer.game_folder import _find_steam_path

from workshopdl.ui.download_tab import DownloadTabMixin
from workshopdl.ui.history_tab import HistoryTabMixin
from workshopdl.ui.updates_tab import UpdatesTabMixin
from workshopdl.ui.settings_tab import SettingsTabMixin


class MainWindow(QMainWindow,
                 DownloadTabMixin,
                 HistoryTabMixin,
                 UpdatesTabMixin,
                 SettingsTabMixin):
    _sig_set_game_id   = pyqtSignal(str, str)
    _sig_log           = pyqtSignal(str)
    _sig_add_mod_items = pyqtSignal(list)
    _sig_launch_update = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(t("app_title"))
        self.setMinimumSize(920, 720)
        self.worker     = None
        self.upd_worker = None
        self._outdated_ids = []
        self._upd_rows  = {}
        self.cfg = load_config()
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

    # ── Слоты для вызова из фоновых потоков ───────────────────────────────────
    def _slot_set_game_id(self, app_id: str, name: str):
        self.inp_game.setText(app_id)
        self._log(t("msg_game_id_found", id=app_id) + (f"  ({name})" if name else ""))
        history_add(app_id, name)
        self._refresh_history()

    def _slot_add_mod_items(self, items: list):
        for mid in items:
            self.mod_list.addItem(mid)

    def _slot_launch_update(self):
        if self._pending_update_ids:
            self._do_launch_update(self._pending_update_ids)
            self._pending_update_ids = []

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

    # ── Проверка незавершённой загрузки ───────────────────────────────────────
    def _check_resume(self):
        from workshopdl.storage import queue_load, queue_clear
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

    # ── Установка модов ───────────────────────────────────────────────────────
    def _offer_install(self, game_id: str, content_folder: str):
        self._log("🔍 Проверяю инструкцию установки...")
        cfg = self.cfg

        def _bg():
            recipe = install_fetch_recipe(game_id, cfg=cfg)
            if recipe:
                self._sig_log.emit(
                    f"📥 Найдена инструкция установки для игры {game_id} "
                    f"({recipe.get('game_name', '')})"
                )
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
        recipe = install_fetch_recipe(game_id, cfg=self.cfg)
        if not recipe:
            return

        game_name       = history_get_name(game_id)
        history_folder  = history_get_game_folder(game_id)
        steamcmd_root   = os.path.dirname(self._get_steamcmd())

        extra_ctx = {
            "game_id":   game_id,
            "game_name": game_name,
            "game_folder":   history_folder,
            "content_folder": content_folder,
            "steamcmd_root": steamcmd_root,
            "STEAM": _find_steam_path(),
        }

        if history_folder:
            self._log(f"📂 Папка игры из истории: {history_folder}")
        else:
            self._log(f"ℹ Папка игры для {game_name} неизвестна — будет найдена при установке")

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

        extra_ctx["mod_ids_list"] = list(mod_folders.keys())
        extra_ctx["mod_total"]    = str(len(mod_folders))
        extra_ctx["mod_count"]    = str(len(mod_folders))

        from workshopdl.installer.dialogs import InstallDialog
        dlg = InstallDialog(recipe, mod_folders, extra_ctx=extra_ctx, parent=self)
        dlg.exec_()

        self._log("\n" + "─" * 50)
        self._log("Лог установки доступен в окне установщика выше.")

    # ── Зависимости ───────────────────────────────────────────────────────────
    def _on_deps_found(self, deps: dict):
        self._show_deps_dialog(deps, source="download")

    def _show_deps_dialog(self, deps: dict, source: str):
        if not deps: return

        behavior = cfg_get(self.cfg, "WorkshopDL", "DepsBehavior", "ask")

        if behavior == "auto":
            self._add_deps_to_list(deps)
            self._log(f"🔗 Авто: добавлено {len(deps)} зависимост(ей) → нажмите ⬇ Скачать")
            return

        if behavior == "skip":
            self._log(f"🔗 Пропущено {len(deps)} зависимост(ей) (настройка: всегда пропускать)")
            return

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
        existing = {self.mod_list.item(i).text() for i in range(self.mod_list.count())}
        added = 0
        for mid in deps:
            if mid not in existing:
                self.mod_list.addItem(mid)
                added += 1
        if added:
            self.tabs.setCurrentIndex(0)
            self._log(f"🔗 Добавлено {added} зависимост(ей) — нажмите ⬇ Скачать")
