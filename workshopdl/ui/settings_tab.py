"""
Вкладка «Настройки» WorkshopDL.
"""

import os, threading, configparser, requests
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QCheckBox, QGroupBox, QComboBox, QSpinBox, QTextEdit, QLabel,
    QFileDialog, QProgressBar, QMessageBox,
)
from PyQt5.QtCore import Qt, QMetaObject, Q_ARG, pyqtSlot
from PyQt5.QtGui import QFont

from workshopdl.config import (
    cfg_get, save_config, STEAMCMD_DEF, STEAMCMD_BIN, IS_WIN,
    LANG_DEF_PATH, INSTALL_LOCAL_DIR, INSTALL_REPO_DEFAULT,
    INSTALL_PATH_DEFAULT, GITHUB_INSTALL_RAW, GITHUB_INSTALL_API,
    install_repo_url,
)
from workshopdl.localization import (
    t, lang_load, lang_list_local, lang_local_path, LangFetchWorker,
)
from workshopdl.workers.steamcmd_install import SteamCMDInstallWorker


class SettingsTabMixin:
    """Смесь, содержащая UI и слоты вкладки «Настройки»."""

    # ── UI ──────────────────────────────────────────────────────────────────
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

        grp_scmd = QGroupBox(t("settings_steamcmd_group"))
        gs = QVBoxLayout(grp_scmd)

        rp = QHBoxLayout()
        self.inp_steamcmd = QLineEdit(); self.inp_steamcmd.setPlaceholderText(STEAMCMD_DEF)
        rp.addWidget(self.inp_steamcmd)
        btn_browse = QPushButton(t("settings_browse"))
        btn_browse.clicked.connect(self._browse_steamcmd)
        rp.addWidget(btn_browse)
        gs.addLayout(rp)

        self.lbl_steamcmd_status = QLabel()
        self._refresh_steamcmd_status()
        gs.addWidget(self.lbl_steamcmd_status)

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

        self.log_steamcmd = QTextEdit()
        self.log_steamcmd.setReadOnly(True)
        self.log_steamcmd.setFont(QFont("Consolas", 8))
        self.log_steamcmd.setMaximumHeight(120)
        self.log_steamcmd.setVisible(False)
        gs.addWidget(self.log_steamcmd)

        lay.addWidget(grp_scmd)

        grp_lang = QGroupBox(t("settings_language_group"))
        gl2 = QVBoxLayout(grp_lang)

        row_cmb = QHBoxLayout()
        self.cmb_lang = QComboBox()
        self.cmb_lang.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cmb_lang.setToolTip(t("settings_language_set_tip"))
        row_cmb.addWidget(self.cmb_lang)

        self.btn_lang_refresh = QPushButton(t("settings_language_refresh"))
        self.btn_lang_refresh.setFixedWidth(34)
        self.btn_lang_refresh.setToolTip(t("settings_language_refresh_tip"))
        self.btn_lang_refresh.clicked.connect(self._fetch_lang_list)
        row_cmb.addWidget(self.btn_lang_refresh)
        gl2.addLayout(row_cmb)

        row_actions = QHBoxLayout()
        self.btn_lang_dl = QPushButton(t("settings_language_download"))
        self.btn_lang_dl.setMinimumWidth(100)
        self.btn_lang_dl.clicked.connect(self._download_selected_lang)
        row_actions.addWidget(self.btn_lang_dl)

        self.btn_lang_apply = QPushButton(t("settings_language_apply"))
        self.btn_lang_apply.setMinimumWidth(100)
        self.btn_lang_apply.clicked.connect(self._apply_lang_from_combo)
        row_actions.addWidget(self.btn_lang_apply)

        row_actions.addStretch()
        gl2.addLayout(row_actions)

        self.lbl_lang_status = QLabel(t("settings_language_download_label"))
        self.lbl_lang_status.setStyleSheet("color: Palette(PlaceholderText);")
        gl2.addWidget(self.lbl_lang_status)

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

        grp_deps = QGroupBox(t("settings_dependency_group"))
        gd = QVBoxLayout(grp_deps)

        gd.addWidget(QLabel(t("settings_dependency_label")))
        self.cmb_deps_behavior = QComboBox()
        self.cmb_deps_behavior.addItem(t("settings_dependency_ask"),       userData="ask")
        self.cmb_deps_behavior.addItem(t("settings_dependency_auto"),  userData="auto")
        self.cmb_deps_behavior.addItem(t("settings_dependency_skip"),       userData="skip")
        gd.addWidget(self.cmb_deps_behavior)

        row_batch = QHBoxLayout()
        row_batch.addWidget(QLabel(t("settings_download_batch_label")))
        self.spn_batch = QSpinBox()
        self.spn_batch.setRange(1, 50)
        self.spn_batch.setValue(1)
        self.spn_batch.setFixedWidth(70)
        self.spn_batch.setToolTip(t("settings_download_batch_tip"))
        row_batch.addWidget(self.spn_batch)
        row_batch.addStretch()
        gd.addLayout(row_batch)

        row_cache = QHBoxLayout()
        self.btn_clear_cache = QPushButton(t("settings_download_cache_clear"))
        self.btn_clear_cache.setToolTip(t("settings_download_cache_clear_tip"))
        self.btn_clear_cache.clicked.connect(self._clear_steamcmd_cache)
        row_cache.addWidget(self.btn_clear_cache)
        self.lbl_cache_status = QLabel("")
        row_cache.addWidget(self.lbl_cache_status)
        row_cache.addStretch()
        gd.addLayout(row_cache)

        lay.addWidget(grp_deps)

        grp_inst = QGroupBox(t("settings_install_group"))
        gi = QVBoxLayout(grp_inst)
        gi.addWidget(QLabel(t("settings_install_label").format(repo=INSTALL_REPO_DEFAULT, path=INSTALL_PATH_DEFAULT)))
        row_repo = QHBoxLayout()
        self.inp_install_repo = QLineEdit()
        self.inp_install_repo.setPlaceholderText(f"{INSTALL_REPO_DEFAULT}/{INSTALL_PATH_DEFAULT}")
        self.inp_install_repo.setToolTip(t("settings_install_repo_tip"))
        row_repo.addWidget(self.inp_install_repo)
        self.btn_repo_test = QPushButton(t("settings_install_repo_check"))
        self.btn_repo_test.setFixedWidth(100)
        self.btn_repo_test.clicked.connect(self._test_install_repo)
        row_repo.addWidget(self.btn_repo_test)
        btn_repo_reset = QPushButton(t("settings_install_repo_reset"))
        btn_repo_reset.setFixedWidth(90)
        btn_repo_reset.clicked.connect(lambda: self.inp_install_repo.clear())
        row_repo.addWidget(btn_repo_reset)
        gi.addLayout(row_repo)
        self.lbl_repo_status = QLabel(t("settings_install_repo_label"))
        self.lbl_repo_status.setStyleSheet("color: Palette(PlaceholderText); font-size: 11px;")
        gi.addWidget(self.lbl_repo_status)

        row_cache2 = QHBoxLayout()
        self.btn_clear_install_cache = QPushButton(t("settings_install_cache_clear"))
        self.btn_clear_install_cache.setToolTip(t("settings_install_cache_clear_tip"))
        self.btn_clear_install_cache.clicked.connect(self._clear_install_cache)
        row_cache2.addWidget(self.btn_clear_install_cache)
        self.lbl_install_cache_info = QLabel("")
        self.lbl_install_cache_info.setStyleSheet("color: Palette(PlaceholderText); font-size: 11px;")
        row_cache2.addWidget(self.lbl_install_cache_info)
        row_cache2.addStretch()
        gi.addLayout(row_cache2)
        self._refresh_install_cache_info()
        lay.addWidget(grp_inst)

        btn_save = QPushButton(t("settings_save"))
        btn_save.clicked.connect(self._save_settings)
        lay.addWidget(btn_save); lay.addStretch()
        return w

    # ── Загрузка / сохранение настроек ──────────────────────────────────────
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

        deps_behavior = cfg_get(self.cfg, "WorkshopDL", "DepsBehavior", "ask")
        for i in range(self.cmb_deps_behavior.count()):
            if self.cmb_deps_behavior.itemData(i) == deps_behavior:
                self.cmb_deps_behavior.setCurrentIndex(i)
                break
        try:
            self.spn_batch.setValue(int(cfg_get(self.cfg, "WorkshopDL", "BatchSize", "1")))
        except Exception:
            pass

        install_repo = cfg_get(self.cfg, "WorkshopDL", "InstallRepo", "")
        if install_repo:
            self.inp_install_repo.setText(install_repo)
        global GITHUB_INSTALL_RAW, GITHUB_INSTALL_API
        GITHUB_INSTALL_RAW, GITHUB_INSTALL_API = install_repo_url(self.cfg)

        lang_path = cfg_get(self.cfg, "WorkshopDL", "LangPath")
        if lang_path and os.path.exists(lang_path):
            self.inp_lang.setText(lang_path)
            lang_load(lang_path)
        else:
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

        repo_val = self.inp_install_repo.text().strip()
        if repo_val:
            self.cfg["WorkshopDL"]["InstallRepo"] = repo_val
        else:
            self.cfg["WorkshopDL"].pop("InstallRepo", None)
        global GITHUB_INSTALL_RAW, GITHUB_INSTALL_API
        GITHUB_INSTALL_RAW, GITHUB_INSTALL_API = install_repo_url(self.cfg)

        save_config(self.cfg)
        QMessageBox.information(self, t("app_title"), t("msg_settings_saved"))

    def _toggle_anon(self):
        anon = self.chk_anon.isChecked()
        self.inp_user.setEnabled(not anon)
        self.inp_pass.setEnabled(not anon)

    # ── SteamCMD ────────────────────────────────────────────────────────────
    def _browse_steamcmd(self):
        if IS_WIN:
            f, _ = QFileDialog.getOpenFileName(self, "steamcmd.exe", "", "steamcmd.exe (steamcmd.exe)")
        else:
            f, _ = QFileDialog.getOpenFileName(self, STEAMCMD_BIN, "", "All Files (*)")
        if f: self.inp_steamcmd.setText(f)

    def _browse_lang(self):
        path, _ = QFileDialog.getOpenFileName(self, t("settings_language_browse_title"), "", "JSON (*.json)")
        if path: self.inp_lang.setText(path)

    def _refresh_steamcmd_status(self):
        exe = self._get_steamcmd()
        if os.path.exists(exe):
            self.lbl_steamcmd_status.setText(f"✅  {exe}")
            self.lbl_steamcmd_status.setStyleSheet("color: Palette(Link); font-weight: bold;")
        else:
            self.lbl_steamcmd_status.setText(t("steamcmd_not_found"))
            self.lbl_steamcmd_status.setStyleSheet("color: Palette(ToolTipText);")

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
            self.lbl_steamcmd_dl.setStyleSheet("color: Palette(Link); font-weight: bold;")
            self._refresh_steamcmd_status()
            if "WorkshopDL" not in self.cfg: self.cfg["WorkshopDL"] = {}
            self.cfg["WorkshopDL"]["SteamCMDPath"] = path_or_err
            save_config(self.cfg)
        else:
            self.lbl_steamcmd_dl.setText(t("steamcmd_dl_error", err=path_or_err))
            self.lbl_steamcmd_dl.setStyleSheet("color: Palette(ToolTipText);")

    def _clear_steamcmd_cache(self):
        import shutil
        steamcmd_dir = os.path.dirname(self._get_steamcmd())
        targets = [
            os.path.join(steamcmd_dir, "userdata"),
            os.path.join(steamcmd_dir, "steamapps"),
        ]
        existing = [p for p in targets if os.path.exists(p)]
        if not existing:
            self.lbl_cache_status.setText(t("settings_download_cache_clear"))
            self.lbl_cache_status.setStyleSheet("color: Palette(Link);")
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
            self.lbl_cache_status.setStyleSheet("color: Palette(ToolTipText);")
        else:
            self.lbl_cache_status.setText("✅ Кеш очищен")
            self.lbl_cache_status.setStyleSheet("color: Palette(Link);")

    # ── Install repo ────────────────────────────────────────────────────────
    def _test_install_repo(self):
        repo_val = self.inp_install_repo.text().strip()
        tmp_cfg = configparser.ConfigParser()
        tmp_cfg["WorkshopDL"] = {"InstallRepo": repo_val} if repo_val else {}
        raw_url, api_url = install_repo_url(tmp_cfg if repo_val else None)

        self.lbl_repo_status.setText(t("settings_install_repo_checking"))
        self.lbl_repo_status.setStyleSheet("color: Palette(PlaceholderText);")
        self.btn_repo_test.setEnabled(False)

        def _check():
            try:
                r = requests.get(api_url, timeout=8)
                if r.status_code == 200:
                    files = r.json()
                    json_count = sum(1 for f in files if isinstance(f, dict)
                                     and f.get("name", "").endswith(".json"))
                    msg = t("settings_install_repo_available").format(count=json_count)
                    color = "#4CAF50"
                elif r.status_code == 404:
                    msg = t("settings_install_repo_not_found")
                    color = "#f44336"
                else:
                    msg = t("settings_install_repo_server_error").format(status=r.status_code)
                    color = "#FF9800"
            except Exception as e:
                msg   = t("settings_install_repo_connection_error").format(error=str(e))
                color = "#f44336"

            QMetaObject.invokeMethod(self, "_slot_repo_test_result",
                Qt.QueuedConnection,
                Q_ARG(str, msg), Q_ARG(str, color))

        threading.Thread(target=_check, daemon=True).start()

    @pyqtSlot(str, str)
    def _slot_repo_test_result(self, msg: str, color: str):
        self.lbl_repo_status.setText(msg)
        self.lbl_repo_status.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.btn_repo_test.setEnabled(True)

    def _refresh_install_cache_info(self):
        if not os.path.isdir(INSTALL_LOCAL_DIR):
            self.lbl_install_cache_info.setText(t("settings_install_cache_empty"))
            return
        files = [f for f in os.listdir(INSTALL_LOCAL_DIR) if f.endswith(".json")]
        total_kb = sum(
            os.path.getsize(os.path.join(INSTALL_LOCAL_DIR, f))
            for f in files
        ) // 1024
        self.lbl_install_cache_info.setText(
            t("settings_install_cache_info").format(files_count=len(files), size_kb=total_kb)
        )

    def _clear_install_cache(self):
        if not os.path.isdir(INSTALL_LOCAL_DIR):
            return
        removed = 0
        for f in os.listdir(INSTALL_LOCAL_DIR):
            if f.endswith(".json"):
                try:
                    os.remove(os.path.join(INSTALL_LOCAL_DIR, f))
                    removed += 1
                except Exception:
                    pass
        self.lbl_install_cache_info.setText(t("settings_install_cache_removed_files").format(count=removed))
        QMessageBox.information(self, "WorkshopDL",
            t("settings_install_cache_cleared").format(count=removed)
        )

    # ── GitHub языки ──────────────────────────────────────────────────────────
    def _populate_lang_combo_local(self):
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
        self.btn_lang_refresh.setEnabled(False)
        self.lbl_lang_status.setText(t("settings_language_refreshing"))
        self.lbl_lang_status.setStyleSheet("color: Palette(PlaceholderText);")
        self._lang_fetch_worker = LangFetchWorker()
        self._lang_fetch_worker.list_ready.connect(self._on_lang_list_ready)
        self._lang_fetch_worker.start()

    def _on_lang_list_ready(self, remote_list):
        self.btn_lang_refresh.setEnabled(True)
        if not remote_list:
            self.lbl_lang_status.setText(t("settings_language_refresh_error"))
            self.lbl_lang_status.setStyleSheet("color: Palette(ToolTipText);")
            return

        saved_code = cfg_get(self.cfg, "WorkshopDL", "LangCode", "en")
        self.cmb_lang.blockSignals(True)
        self.cmb_lang.clear()
        select_idx = 0
        for i, (code, name, is_local) in enumerate(remote_list):
            local_path = lang_local_path(code)
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
            t("settings_language_refresh_done").format(total=total, downloaded=downloaded)
        )
        self.lbl_lang_status.setStyleSheet("color: Palette(Link);")

    def _download_selected_lang(self):
        idx = self.cmb_lang.currentIndex()
        if idx < 0: return
        code, local_path, is_local = self.cmb_lang.itemData(idx)
        if is_local and local_path and os.path.exists(local_path):
            self.lbl_lang_status.setText(t("settings_language_download_alreadydone").format(path=local_path))
            return
        self.btn_lang_dl.setEnabled(False)
        self._lang_dl_worker = LangFetchWorker(download_code=code)
        self._lang_dl_worker.dl_progress.connect(self.lbl_lang_status.setText)
        self._lang_dl_worker.dl_done.connect(self._on_lang_downloaded)
        self._lang_dl_worker.start()

    def _on_lang_downloaded(self, success, path_or_err):
        self.btn_lang_dl.setEnabled(True)
        if success:
            self.lbl_lang_status.setText(t("settings_language_downloaded").format(path_or_err=path_or_err))
            self.lbl_lang_status.setStyleSheet("color: Palette(Link);")
            self._fetch_lang_list()
        else:
            self.lbl_lang_status.setText(t("settings_language_download_error").format(error=path_or_err))
            self.lbl_lang_status.setStyleSheet("color: Palette(ToolTipText);")

    def _apply_lang_from_combo(self):
        idx = self.cmb_lang.currentIndex()
        if idx < 0: return
        code, local_path, is_local = self.cmb_lang.itemData(idx)
        if not is_local or not local_path or not os.path.exists(local_path):
            self.lbl_lang_status.setText(t("settings_language_apply_nofile"))
            self.lbl_lang_status.setStyleSheet("color: Palette(ToolTipText);")
            return
        if "WorkshopDL" not in self.cfg: self.cfg["WorkshopDL"] = {}
        self.cfg["WorkshopDL"]["LangCode"] = code
        self.cfg["WorkshopDL"]["LangPath"] = local_path
        save_config(self.cfg)
        self.inp_lang.setText(local_path)
        self._apply_language(path_override=local_path)

    def _apply_language(self, path_override: str = ""):
        path = path_override or self.inp_lang.text().strip()
        if path and not os.path.exists(path):
            QMessageBox.warning(self, t("app_title"), f"Файл не найден:\n{path}"); return

        game_id   = self.inp_game.text()
        steamcmd  = self.inp_steamcmd.text()
        lang_path = path
        anon      = self.chk_anon.isChecked()
        user      = self.inp_user.text()
        pwd       = self.inp_pass.text()
        upd_cur   = self.cmb_update_paths.currentText()
        lang_code = cfg_get(self.cfg, "WorkshopDL", "LangCode", "en")

        if lang_path:
            if "WorkshopDL" not in self.cfg: self.cfg["WorkshopDL"] = {}
            self.cfg["WorkshopDL"]["LangPath"] = lang_path
            save_config(self.cfg)

        lang_load(lang_path)

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
