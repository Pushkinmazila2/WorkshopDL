"""
Вкладка «Скачать» WorkshopDL.
"""

import threading
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QLabel, QListWidget, QGroupBox, QProgressBar, QTextEdit,
)
from PyQt5.QtCore import Qt, QUrl, pyqtSlot
from PyQt5.QtGui import QFont, QDesktopServices

from workshopdl.config import cfg_get
from workshopdl.config import open_folder
from workshopdl.localization import t
from workshopdl.steam_api import fetch_game_id_for_mod, fetch_collection
from workshopdl.storage import history_add
from workshopdl.workers.download import DownloadWorker


class DownloadTabMixin:
    """Смесь, содержащая UI и слоты вкладки «Скачать»."""

    # ── UI ──────────────────────────────────────────────────────────────────
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

    # ── Слоты ───────────────────────────────────────────────────────────────
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
        from PyQt5.QtWidgets import QFileDialog
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
        if not mid:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, t("app_title"), t("msg_add_mod_first")); return
        self._log(t("msg_searching_game_id", id=mid))
        def _bg():
            app_id, name = fetch_game_id_for_mod(mid)
            if app_id:
                self._sig_set_game_id.emit(app_id, name)
            else:
                self._sig_log.emit(t("msg_game_id_not_found"))
        threading.Thread(target=_bg, daemon=True).start()

    # ── Скачка ──────────────────────────────────────────────────────────────
    def _start_download(self, resume_from=0):
        from PyQt5.QtWidgets import QMessageBox
        import os
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
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(self, t("app_title"), t("msg_paused", remaining=remaining))

    def _on_finished(self, success, fail):
        import os
        from PyQt5.QtWidgets import QMessageBox
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

        if success > 0:
            self._offer_install(game_id, folder)
