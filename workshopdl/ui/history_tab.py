"""
Вкладка «История» WorkshopDL.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget, QListWidgetItem,
)
from PyQt5.QtCore import Qt

from workshopdl.localization import t
from workshopdl.config import open_folder
from workshopdl.storage import (
    history_load, history_save, history_add, history_get_name,
    history_get_game_folder, history_scan_from_disk,
)


class HistoryTabMixin:
    """Смесь, содержащая UI и слоты вкладки «История»."""

    # ── UI ──────────────────────────────────────────────────────────────────
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

    # ── Слоты ───────────────────────────────────────────────────────────────
    def _scan_and_refresh_history(self):
        import os
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
        import os
        from PyQt5.QtWidgets import QMessageBox
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
