"""
Главное окно WorkshopDL.
"""

import sys, os, re, json, threading, configparser, datetime, shutil, requests
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QListWidget, QListWidgetItem, QLabel,
    QTextEdit, QGroupBox, QCheckBox, QTabWidget, QMessageBox,
    QFileDialog, QProgressBar, QComboBox, QSpinBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QSizePolicy,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QUrl, pyqtSlot, QMetaObject, Q_ARG
from PyQt5.QtGui import QDesktopServices, QFont, QColor, QBrush

from workshopdl.config import (
    APP_DIR, STEAMCMD_DEF, INI_PATH, MODULES_PATH, IS_WIN,
    load_config, save_config, cfg_get, open_folder,
    DISABLED_SUFFIX, mod_is_disabled, mod_toggle, folder_size_mb,
    install_repo_url, GITHUB_INSTALL_RAW, GITHUB_INSTALL_API,
    INSTALL_LOCAL_DIR, INSTALL_REPO_DEFAULT, INSTALL_PATH_DEFAULT,
    LANG_DEF_PATH, LANG_LOCAL_DIR,
)
from workshopdl.localization import t, lang_load, lang_list_local, lang_local_path, LangFetchWorker
from workshopdl.storage import (
    queue_save, queue_load, queue_clear,
    history_load, history_save, history_add, history_get_name,
    history_get_game_folder, history_set_game_folder, history_scan_from_disk,
    mod_paths_load, mod_paths_save, mod_paths_add,
)
from workshopdl.steam_api import fetch_game_id_for_mod, fetch_collection
from workshopdl.workers.steamcmd_install import SteamCMDInstallWorker
from workshopdl.workers.download import DownloadWorker
from workshopdl.workers.update_check import UpdateCheckWorker
from workshopdl.installer import install_fetch_recipe
from workshopdl.installer.game_folder import _find_steam_path
from workshopdl.installer.dialogs import InstallDialog


class MainWindow(QMainWindow):
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

    # ── Вкладка: Скачать ──────────────────────────────────────────────────────
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

    # ── Вкладка: История ─────────────────────────────────────────────────────
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

    # ── Вкладка: Проверка обновлений ──────────────────────────────────────────
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

    # ── Вкладка: Настройки ───────────────────────────────────────────────────
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
        self.lbl_lang_status.setStyleSheet("color: #888;")
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
        self.lbl_repo_status.setStyleSheet("color: #888; font-size: 11px;")
        gi.addWidget(self.lbl_repo_status)

        row_cache2 = QHBoxLayout()
        self.btn_clear_install_cache = QPushButton(t("settings_install_cache_clear"))
        self.btn_clear_install_cache.setToolTip(t("settings_install_cache_clear_tip"))
        self.btn_clear_install_cache.clicked.connect(self._clear_install_cache)
        row_cache2.addWidget(self.btn_clear_install_cache)
        self.lbl_install_cache_info = QLabel("")
        self.lbl_install_cache_info.setStyleSheet("color: #888; font-size: 11px;")
        row_cache2.addWidget(self.lbl_install_cache_info)
        row_cache2.addStretch()
        gi.addLayout(row_cache2)
        self._refresh_install_cache_info()
        lay.addWidget(grp_inst)

        btn_save = QPushButton(t("settings_save"))
        btn_save.clicked.connect(self._save_settings)
        lay.addWidget(btn_save); lay.addStretch()
        return w

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

    def _test_install_repo(self):
        repo_val = self.inp_install_repo.text().strip()
        tmp_cfg = configparser.ConfigParser()
        tmp_cfg["WorkshopDL"] = {"InstallRepo": repo_val} if repo_val else {}
        raw_url, api_url = install_repo_url(tmp_cfg if repo_val else None)

        self.lbl_repo_status.setText(t("settings_install_repo_checking"))
        self.lbl_repo_status.setStyleSheet("color: #888;")
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

    def _toggle_anon(self):
        anon = self.chk_anon.isChecked()
        self.inp_user.setEnabled(not anon)
        self.inp_pass.setEnabled(not anon)

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

    def _browse_steamcmd(self):
        if IS_WIN:
            f, _ = QFileDialog.getOpenFileName(self, "steamcmd.exe", "", "steamcmd.exe (steamcmd.exe)")
        else:
            f, _ = QFileDialog.getOpenFileName(self, STEAMCMD_BIN, "", "All Files (*)")
        if f: self.inp_steamcmd.setText(f)

    def _browse_lang(self):
        path, _ = QFileDialog.getOpenFileName(self, t("settings_language_browse_title"), "", "JSON (*.json)")
        if path: self.inp_lang.setText(path)

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
        self.lbl_lang_status.setStyleSheet("color: #888;")
        self._lang_fetch_worker = LangFetchWorker()
        self._lang_fetch_worker.list_ready.connect(self._on_lang_list_ready)
        self._lang_fetch_worker.start()

    def _on_lang_list_ready(self, remote_list):
        self.btn_lang_refresh.setEnabled(True)
        if not remote_list:
            self.lbl_lang_status.setText(t("settings_language_refresh_error"))
            self.lbl_lang_status.setStyleSheet("color: #e74c3c;")
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
        self.lbl_lang_status.setStyleSheet("color: #27ae60;")

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
            self.lbl_lang_status.setStyleSheet("color: #27ae60;")
            self._fetch_lang_list()
        else:
            self.lbl_lang_status.setText(t("settings_language_download_error").format(error=path_or_err))
            self.lbl_lang_status.setStyleSheet("color: #e74c3c;")

    def _apply_lang_from_combo(self):
        idx = self.cmb_lang.currentIndex()
        if idx < 0: return
        code, local_path, is_local = self.cmb_lang.itemData(idx)
        if not is_local or not local_path or not os.path.exists(local_path):
            self.lbl_lang_status.setText(t("settings_language_apply_nofile"))
            self.lbl_lang_status.setStyleSheet("color: #e74c3c;")
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

    def _refresh_steamcmd_status(self):
        exe = self._get_steamcmd()
        if os.path.exists(exe):
            self.lbl_steamcmd_status.setText(f"✅  {exe}")
            self.lbl_steamcmd_status.setStyleSheet("color: #27ae60; font-weight: bold;")
        else:
            self.lbl_steamcmd_status.setText(t("steamcmd_not_found"))
            self.lbl_steamcmd_status.setStyleSheet("color: #e74c3c;")

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
            self.lbl_steamcmd_dl.setStyleSheet("color: #27ae60; font-weight: bold;")
            self._refresh_steamcmd_status()
            if "WorkshopDL" not in self.cfg: self.cfg["WorkshopDL"] = {}
            self.cfg["WorkshopDL"]["SteamCMDPath"] = path_or_err
            save_config(self.cfg)
        else:
            self.lbl_steamcmd_dl.setText(t("steamcmd_dl_error", err=path_or_err))
            self.lbl_steamcmd_dl.setStyleSheet("color: #e74c3c;")

    def _clear_steamcmd_cache(self):
        steamcmd_dir = os.path.dirname(self._get_steamcmd())
        targets = [
            os.path.join(steamcmd_dir, "userdata"),
            os.path.join(steamcmd_dir, "steamapps"),
        ]
        existing = [p for p in targets if os.path.exists(p)]
        if not existing:
            self.lbl_cache_status.setText(t("settings_download_cache_clear"))
            self.lbl_cache_status.setStyleSheet("color: #27ae60;")
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
            self.lbl_cache_status.setStyleSheet("color: #e74c3c;")
        else:
            self.lbl_cache_status.setText("✅ Кеш очищен")
            self.lbl_cache_status.setStyleSheet("color: #27ae60;")

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

    # ── Список модов ─────────────────────────────────────────────────────────
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
        if not mid: QMessageBox.warning(self, t("app_title"), t("msg_add_mod_first")); return
        self._log(t("msg_searching_game_id", id=mid))
        def _bg():
            app_id, name = fetch_game_id_for_mod(mid)
            if app_id:
                self._sig_set_game_id.emit(app_id, name)
            else:
                self._sig_log.emit(t("msg_game_id_not_found"))
        threading.Thread(target=_bg, daemon=True).start()

    # ── История ───────────────────────────────────────────────────────────────
    def _scan_and_refresh_history(self):
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

    # ── Проверка незавершённой загрузки ───────────────────────────────────────
    def _check_resume(self):
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

    # ── Скачка ────────────────────────────────────────────────────────────────
    def _start_download(self, resume_from=0):
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
        QMessageBox.information(self, t("app_title"), t("msg_paused", remaining=remaining))

    def _on_finished(self, success, fail):
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

        dlg = InstallDialog(recipe, mod_folders, extra_ctx=extra_ctx, parent=self)
        dlg.exec_()

        self._log("\n" + "─" * 50)
        self._log("Лог установки доступен в окне установщика выше.")

    # ── Проверка обновлений: пути ─────────────────────────────────────────────
    def _browse_update_path(self):
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

    # ── Проверка обновлений: старт ────────────────────────────────────────────
    def _start_update_check(self):
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

    # ── Проверка обновлений: результат ────────────────────────────────────────
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
        name_item.setBackground(QBrush(row_color))
        name_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if has_missing:
            name_item.setToolTip(f"⚠ {len(mod_missing)} зависимост(ей) не скачаны")
        size_str = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{size_mb*1024:.0f} KB"
        sz_item = cell(size_str, size_mb)
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

    # ── Клики по таблице ─────────────────────────────────────────────────────
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