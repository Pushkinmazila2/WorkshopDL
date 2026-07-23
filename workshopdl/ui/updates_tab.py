"""
Вкладка «Проверка обновлений» WorkshopDL.
"""

import os, datetime
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QProgressBar, QCheckBox, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QSizePolicy,
)
from PyQt5.QtCore import Qt, QUrl, pyqtSlot, QMetaObject, Q_ARG
from PyQt5.QtGui import QFont, QColor, QBrush, QDesktopServices

from workshopdl.localization import t
from workshopdl.config import cfg_get, open_folder, DISABLED_SUFFIX, mod_toggle
from workshopdl.storage import mod_paths_load, mod_paths_save, mod_paths_add
from workshopdl.steam_api import fetch_game_id_for_mod
from workshopdl.workers.update_check import UpdateCheckWorker


class UpdatesTabMixin:
    """Смесь, содержащая UI и слоты вкладки «Проверка обновлений»."""

    # ── UI ──────────────────────────────────────────────────────────────────
    def _tab_updates(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(6)

        grp_path = QGroupBox(t("upd_group_path"))
        gp = QVBoxLayout(grp_path)
        gp.addWidget(QLabel(t("upd_path_desc")))
        rp = QHBoxLayout()
        self.cmb_update_paths = QComboBox()
        self.cmb_update_paths.setEditable(True)
        self.cmb_update_paths.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cmb_update_paths.lineEdit().setPlaceholderText(t("upd_path_placeholder"))
        rp.addWidget(self.cmb_update_paths)
        for icon, tip, slot in [(t("btn_browse"), t("btn_browse_tip"),        self._browse_update_path),
                                 (t("btn_delete_path"),  t("btn_delete_path_tip"), self._delete_update_path)]:
            b = QPushButton(icon); b.setFixedWidth(34); b.setToolTip(tip)
            b.clicked.connect(slot); rp.addWidget(b)
        gp.addLayout(rp); lay.addWidget(grp_path)

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
        self.upd_table.setColumnWidth(0, 40)
        self.upd_table.setColumnWidth(2, 75)
        self.upd_table.setColumnWidth(3, 60)
        self.upd_table.setColumnWidth(4, 80)
        self.upd_table.setColumnWidth(5, 60)
        self.upd_table.setColumnWidth(6, 125)
        self.upd_table.setColumnWidth(7, 125)
        self.upd_table.setFont(QFont("Segoe UI", 9))
        self.upd_table.cellClicked.connect(self._upd_table_clicked)
        lay.addWidget(self.upd_table)

        self.upd_table.setColumnHidden(6, True)
        self.upd_table.setColumnHidden(7, True)

        self.upd_status = QLabel("")
        lay.addWidget(self.upd_status)
        return w

    # ── Пути ────────────────────────────────────────────────────────────────
    def _browse_update_path(self):
        from PyQt5.QtWidgets import QFileDialog
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

    # ── Старт проверки ──────────────────────────────────────────────────────
    def _start_update_check(self):
        from PyQt5.QtWidgets import QMessageBox
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

    # ── Результат ───────────────────────────────────────────────────────────
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

        has_missing = bool(mod_missing)
        status_icon = ICON[status] + (" ⚠" if has_missing else "")
        st_item = cell(status_icon, SORT[status])
        tip = t(f"status_{status}")
        if has_missing:
            deps_text = "\n".join(f"  • {mid}: {name}" for mid, name in mod_missing)
            tip += f"\n\n⚠ Отсутствующие зависимости ({len(mod_missing)}):\n{deps_text}"
        st_item.setToolTip(tip)
        name_item = QTableWidgetItem(title if title != mod_id else "—")
        name_item.setForeground(QBrush(QColor("#000000")))
        name_item.setBackground(QBrush(row_color))
        name_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if has_missing:
            name_item.setToolTip(f"⚠ {len(mod_missing)} зависимост(ей) не скачаны")
        size_str = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{size_mb*1024:.0f} KB"
        sz_item = cell(size_str, size_mb)
        sz_item.setForeground(QBrush(QColor("#000000")))
        steam_item = cell("🔗", mod_id)
        steam_item.setForeground(QBrush(QColor("#1a73e8")))
        steam_item.setToolTip(f"steamcommunity.com/sharedfiles/filedetails/?id={mod_id}")
        toggle_label = "▶ Включить" if status == "disabled" else "⏸ Выкл"
        tog_item = cell(toggle_label, mod_id)
        tog_item.setForeground(QBrush(QColor("#2980b9")))
        tog_item.setData(Qt.UserRole + 1, folder)
        folder_item = cell("📁", mod_id)
        folder_item.setForeground(QBrush(QColor("#27ae60")))
        folder_item.setToolTip(folder)
        loc_item = cell(local_dt, int(local_ts) if local_ts else 0)
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
        self._show_deps_dialog(deps, source="updates")

    # ── Клики по таблице ────────────────────────────────────────────────────
    def _upd_table_clicked(self, row, col):
        if col == 3:
            id_item = self.upd_table.item(row, 2)
            if id_item:
                QDesktopServices.openUrl(QUrl(
                    f"https://steamcommunity.com/sharedfiles/filedetails/?id={id_item.text()}"))
        elif col == 4:
            tog = self.upd_table.item(row, 4)
            if tog:
                mod_id = tog.data(Qt.UserRole)
                folder = tog.data(Qt.UserRole + 1)
                new_folder = mod_toggle(folder)
                was_disabled = folder.endswith(DISABLED_SUFFIX)
                new_status = "ok" if was_disabled else "disabled"
                new_icon   = "🔘" if not was_disabled else "🟢"
                new_lbl    = "▶ Включить" if not was_disabled else "⏸ Выкл"
                self.upd_table.item(row, 0).setText(new_icon)
                tog.setText(new_lbl)
                tog.setData(Qt.UserRole + 1, new_folder)
        elif col == 5:
            fold_item = self.upd_table.item(row, 4)
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
        from PyQt5.QtWidgets import QMessageBox
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
        import threading
        game_id = self.inp_game.text().strip()
        if not game_id and mod_ids:
            self.upd_status.setText(t("msg_searching_game_id", id=mod_ids[0]))
            def _bg():
                app_id, name = fetch_game_id_for_mod(mod_ids[0])
                if app_id:
                    self._sig_set_game_id.emit(app_id, name)
                    self._sig_log.emit("")
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