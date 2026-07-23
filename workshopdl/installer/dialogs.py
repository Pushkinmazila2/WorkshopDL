"""
Диалоги установщика модов: InstallQuestionsDialog, InstallDialog.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QListWidget,
    QLabel, QTextEdit, QGroupBox, QCheckBox, QMessageBox, QProgressBar,
    QComboBox, QFileDialog, QDialogButtonBox, QScrollArea, QFrame
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from workshopdl.installer.conditions import _build_tpl
from workshopdl.installer.installer import ModInstaller
from workshopdl.installer.worker import InstallWorker


class InstallQuestionsDialog(QDialog):
    """
    Диалог для задания вопросов пользователю в процессе установки.
    Поддерживает типы вопросов: text, select, checkbox.
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

            label       = self._render(q.get("label",   qid))
            hint        = self._render(q.get("hint",    ""))
            default     = self._render(str(q.get("default", "")))
            placeholder = self._render(q.get("placeholder", ""))

            grp = QGroupBox(label)
            gl  = QVBoxLayout(grp)
            gl.setSpacing(4)

            if qtype == "text":
                row_w = QWidget(); row_l = QHBoxLayout(row_w); row_l.setContentsMargins(0,0,0,0)
                w = QLineEdit()
                w.setText(default)
                w.setPlaceholderText(placeholder or self._render(q.get("placeholder_hint", "")))
                row_l.addWidget(w)

                browse = q.get("browse", "")
                if browse:
                    btn_browse = QPushButton("📂" if browse == "folder" else "📄")
                    btn_browse.setFixedWidth(32)
                    btn_browse.setToolTip("Выбрать папку" if browse == "folder" else "Выбрать файл")
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
                rendered_default = self._render(str(q.get("default", "")))
                for i in range(w.count()):
                    if str(w.itemData(i)) == rendered_default:
                        w.setCurrentIndex(i); break
                gl.addWidget(w)
                self._widgets[qid] = ("select", w)

            elif qtype == "checkbox":
                chk_label = self._render(q.get("checkbox_label", "Включить"))
                w = QCheckBox(chk_label)
                raw_default = q.get("default", False)
                if isinstance(raw_default, str):
                    checked = raw_default.lower() in ("true", "1", "yes")
                else:
                    checked = bool(raw_default)
                w.setChecked(checked)
                gl.addWidget(w)
                self._widgets[qid] = ("checkbox", w)

            if hint:
                lbl_hint = QLabel(f"<i style='color:#888;font-size:11px'>{hint}</i>")
                lbl_hint.setWordWrap(True)
                gl.addWidget(lbl_hint)

            inner_lay.addWidget(grp)

        inner_lay.addStretch()
        scroll.setWidget(inner)
        lay.addWidget(scroll)

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
        if not text or "{" not in text:
            return text
        tpl = _build_tpl(self._ctx)
        try:
            return text.format(**tpl)
        except (KeyError, ValueError):
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

        grp = QGroupBox("Моды:")
        gl  = QVBoxLayout(grp)
        self._mod_list = QListWidget()
        for mod_id, folder in mod_folders.items():
            self._mod_list.addItem(f"  {mod_id}  ({folder})")
        gl.addWidget(self._mod_list)
        lay.addWidget(grp)

        self._progress = QProgressBar()
        self._progress.setFormat("%v / %m")
        self._progress.setMaximum(len(mod_folders))
        self._progress.setValue(0)
        lay.addWidget(self._progress)

        grp_log = QGroupBox("Лог установки:")
        ll = QVBoxLayout(grp_log)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        self._log.setMinimumHeight(160)
        ll.addWidget(self._log)
        lay.addWidget(grp_log)

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
                self._mod_list.item(i).setText(f"  {icon} {mod_id}")
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
            f"Установлено: {ok} из {total}\nС ошибками: {fail}\n\nПодробности — в логе установки."
        )