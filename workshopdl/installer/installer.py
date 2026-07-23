"""
Движок установки одного мода (ModInstaller).
"""

import os, json, re, glob, shutil, zipfile, importlib, requests
import xml.etree.ElementTree as ET

from workshopdl.config import IS_WIN, IS_MAC, IS_LINUX, INSTALL_LOCAL_DIR
from workshopdl.storage import history_set_game_folder
from workshopdl.installer.game_folder import _pf_find_game_folder, _find_steam_path
from workshopdl.installer.store_detector import _pf_detect_game_store, _auto_detect_version
from workshopdl.installer.utils import (
    _pf_read_file_value, _pf_smart_copy, _pf_backup_file,
    _pf_check_disk, _pf_rename_files, _pf_delete_files
)
from workshopdl.installer.conditions import _pf_safe_eval_condition, _build_tpl
from workshopdl.installer.patchers import _pf_patch_ini, _pf_patch_json, _pf_patch_xml, _pf_patch_cfg


class ModInstaller:
    """
    Выполняет установку одного мода согласно инструкции (recipe).
    Поддерживает оба формата:
      - Параметрический (declarative): только JSON-steps
      - Гибридный: JSON-steps + запуск внешнего Python-плагина
    """

    STEP_HANDLERS = {
        "find_game_folder": "_step_find_game_folder",
        "detect_store":     "_step_detect_store",
        "read_file":        "_step_read_file",
        "set_var":          "_step_set_var",
        "increment":        "_step_increment",
        "copy":             "_step_copy",
        "rename":           "_step_rename",
        "delete":           "_step_delete",
        "backup":           "_step_backup",
        "patch_ini":        "_step_patch_ini",
        "patch_json":       "_step_patch_json",
        "patch_xml":        "_step_patch_xml",
        "patch_cfg":        "_step_patch_cfg",
        "check_disk":       "_step_check_disk",
        "plugin":           "_step_plugin",
    }

    _FLOW_ACTIONS = {"if", "else", "elif", "end_if", "for", "end_for", "while", "end_while"}

    def __init__(self, recipe: dict, mod_folder: str, log_cb,
                 user_answers: dict = None, extra_ctx: dict = None):
        self.recipe       = recipe
        self.mod_folder   = mod_folder
        self.log          = log_cb

        self.ctx = {
            "workshopdl_source": True,
            "game_folder":   "",
            "mod_folder":    mod_folder,
            "steamcmd_root": "",
            "game_id":       "",
            "mod_id":        "",
            "game_name":     "",
            "store":         "",
            "version":       "",
            "platform": "win" if IS_WIN else ("mac" if IS_MAC else "linux"),
            "is_win":   str(IS_WIN).lower(),
            "is_linux": str(IS_LINUX).lower(),
            "is_mac":   str(IS_MAC).lower(),
            "USERPROFILE":  os.path.expanduser("~"),
            "APPDATA":      os.environ.get("APPDATA", ""),
            "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
            "PROGRAMFILES": os.environ.get("ProgramFiles", ""),
            "PROGRAMFILES86": os.environ.get("ProgramFiles(x86)", ""),
            "STEAM":        _find_steam_path(),
            "user_vars": dict(user_answers or {}),
            "_install_mode": "install",
        }

        if extra_ctx:
            for k, v in extra_ctx.items():
                if k == "user_vars" and isinstance(v, dict):
                    self.ctx["user_vars"].update(v)
                else:
                    self.ctx[k] = v

        if self.ctx.get("game_folder"):
            self.ctx["user_vars"].setdefault("game_folder", self.ctx["game_folder"])

    def run(self) -> bool:
        steps = self.recipe.get("steps", [])
        if not steps:
            self.log("  ⚠ Инструкция пуста — шагов нет")
            return False
        return self._exec_steps(steps)

    def _exec_steps(self, steps: list, depth: int = 0) -> bool:
        i = 0
        while i < len(steps):
            step   = steps[i]
            action = step.get("action", "")
            label  = step.get("label", action)

            if action == "if":
                branches, end_idx = self._collect_if_branches(steps, i)
                self._exec_if(branches)
                i = end_idx + 1
                continue

            if action == "for":
                body, end_idx = self._collect_block(steps, i + 1, "end_for")
                self._exec_for(step, body)
                i = end_idx + 1
                continue

            if action == "while":
                body, end_idx = self._collect_block(steps, i + 1, "end_while")
                self._exec_while(step, body)
                i = end_idx + 1
                continue

            if action in ("end_if", "end_for", "end_while", "else", "elif"):
                i += 1
                continue

            when = step.get("when", "")
            if when and not _pf_safe_eval_condition(when, self.ctx):
                self.log(f"  ⏭ «{label}» — пропущен (when={when!r})")
                i += 1
                continue

            self.log(f"  ▶ {label}")
            handler_name = self.STEP_HANDLERS.get(action)
            if not handler_name:
                self.log(f"  ⚠ Неизвестное действие: {action!r}")
                i += 1
                continue

            try:
                ok = getattr(self, handler_name)(step)
            except Exception as e:
                self.log(f"  ❌ Ошибка в шаге «{label}»: {e}")
                ok = False

            if not ok and step.get("required", False):
                self.log(f"  🛑 Шаг «{label}» обязательный, прерываем установку")
                return False

            i += 1
        return True

    def _collect_if_branches(self, steps: list, start: int):
        branches = []
        cur_cond = steps[start].get("when", steps[start].get("condition", "True"))
        cur_body = []
        depth = 0
        i = start + 1
        while i < len(steps):
            a = steps[i].get("action", "")
            if a == "if":
                depth += 1
            if depth == 0:
                if a in ("elif", "else", "end_if"):
                    branches.append({"cond": cur_cond, "body": cur_body})
                    if a == "end_if":
                        return branches, i
                    cur_cond = steps[i].get("condition", "") if a == "elif" else None
                    cur_body = []
                    i += 1
                    continue
            if a == "end_if" and depth > 0:
                depth -= 1
            cur_body.append(steps[i])
            i += 1
        branches.append({"cond": cur_cond, "body": cur_body})
        return branches, i - 1

    def _exec_if(self, branches: list):
        for branch in branches:
            cond = branch["cond"]
            if cond is None or _pf_safe_eval_condition(cond, self.ctx):
                self._exec_steps(branch["body"])
                return

    def _collect_block(self, steps: list, start: int, end_action: str):
        body  = []
        depth = 0
        outer_action = end_action.replace("end_", "")
        i = start
        while i < len(steps):
            a = steps[i].get("action", "")
            if a == outer_action:
                depth += 1
            if a == end_action:
                if depth == 0:
                    return body, i
                depth -= 1
            body.append(steps[i])
            i += 1
        return body, i - 1

    def _exec_for(self, step: dict, body: list):
        var_name  = step.get("var", "item")
        idx_var   = step.get("index_var", f"{var_name}_index")
        items     = step.get("items")
        items_var = step.get("items_var", "")

        if items is None and items_var:
            raw   = self.ctx["user_vars"].get(items_var, "")
            items = raw if isinstance(raw, list) else [x.strip() for x in str(raw).split(",")]
        if not items:
            self.log(f"  ⚠ for: items пустой")
            return

        total = len(items)
        self._set_uv(f"{var_name}_total", str(total))

        for idx, val in enumerate(items):
            val_str = str(val).strip()
            self._set_uv(var_name,            val_str)
            self._set_uv(idx_var,             str(idx))
            self._set_uv(f"{var_name}_number", str(idx + 1))
            self._set_uv(f"{var_name}_is_first", "true" if idx == 0       else "false")
            self._set_uv(f"{var_name}_is_last",  "true" if idx == total-1 else "false")
            self.log(f"  🔁 for [{idx+1}/{total}] {var_name} = {val_str!r}")
            self._exec_steps(body)

    def _exec_while(self, step: dict, body: list):
        condition = step.get("condition", step.get("when", "False"))
        max_iter  = int(step.get("max_iter", 100))
        idx_var   = step.get("index_var", "while_index")
        it = 0
        while _pf_safe_eval_condition(condition, self.ctx):
            if it >= max_iter:
                self.log(f"  ⚠ while: достигнут лимит {max_iter} итераций, выходим")
                break
            self._set_uv(idx_var,              str(it))
            self._set_uv(f"{idx_var}_number",  str(it + 1))
            self.log(f"  🔁 while итерация {it + 1}")
            self._exec_steps(body)
            it += 1

    def _set_uv(self, key: str, value: str):
        self.ctx["user_vars"][key] = value
        _SYNC = {"game_folder", "store", "version", "game_id", "mod_id", "game_name"}
        if key in _SYNC:
            self.ctx[key] = value

    # ── Шаги ─────────────────────────────────────────────────────────────────

    def _step_set_var(self, step: dict) -> bool:
        tpl = self._tpl()

        def _apply(k: str, v: str):
            self._set_uv(k, v)
            if k == "game_folder" and v and os.path.isdir(v) and self.ctx.get("game_id"):
                history_set_game_folder(self.ctx["game_id"], v)

        for k, v in step.get("vars", {}).items():
            rendered = str(v).format(**tpl) if isinstance(v, str) else str(v)
            _apply(k, rendered)
            self.log(f"  📌 {k} = {rendered!r}")

        name = step.get("name", "")
        if name:
            if "eval" in step:
                result = "true" if _pf_safe_eval_condition(step["eval"], self.ctx) else "false"
                _apply(name, result)
                self.log(f"  📌 {name} = {result!r} (eval)")
            elif "concat" in step:
                parts  = [str(p).format(**tpl) for p in step["concat"]]
                result = "".join(parts)
                _apply(name, result)
                self.log(f"  📌 {name} = {result!r} (concat)")
            else:
                val = str(step.get("value", "")).format(**tpl)
                _apply(name, val)
                self.log(f"  📌 {name} = {val!r}")
        return True

    def _step_increment(self, step: dict) -> bool:
        name = step.get("name", "")
        if not name:
            self.log("  ⚠ increment: не задан name")
            return False
        by   = int(step.get("by",   1))
        init = int(step.get("init", 0))
        do_log = step.get("log", True)
        cur_raw = self.ctx["user_vars"].get(name, str(init))
        try:
            cur = int(cur_raw)
        except (ValueError, TypeError):
            cur = init
        new_val = cur + by
        self._set_uv(name, str(new_val))
        if do_log:
            arrow = f"{cur} → {new_val}"
            self.log(f"  🔢 {name}: {arrow}  (by {by:+d})")
        return True

    def _step_find_game_folder(self, step: dict) -> bool:
        folder = _pf_find_game_folder(step, self.ctx)
        if folder:
            self.ctx["game_folder"] = folder
            self.ctx["user_vars"]["game_folder"] = folder
            self.log(f"  📂 Папка игры найдена: {folder}")
            if self.ctx.get("game_id"):
                history_set_game_folder(self.ctx["game_id"], folder)
                self.log(f"  💾 Путь сохранён в историю для App ID {self.ctx['game_id']}")
            return True
        manual = step.get("manual_fallback")
        if manual:
            self.ctx["game_folder"] = manual
            self.ctx["user_vars"]["game_folder"] = manual
            self.log(f"  ⚠ Используется fallback: {manual}")
            return True
        self.log("  ⚠ Папка игры не найдена")
        return False

    def _step_detect_store(self, step: dict) -> bool:
        game_folder = self.ctx.get("game_folder", "")

        if not game_folder:
            mod_folder = self.ctx.get("mod_folder", "")
            norm_mod = mod_folder.replace("\\", "/").lower()
            if "steamapps/workshop/content" in norm_mod:
                self.ctx["store"]   = "steam"
                self.ctx["version"] = ""
                self.ctx["user_vars"]["store"]   = "steam"
                self.ctx["user_vars"]["version"] = ""
                self.log("  🎮 Магазин: STEAM (WorkshopDL — мод из SteamCMD workshop)")
                self.log("  ℹ  game_folder не задана — запустите find_game_folder для установки")
                return True
            self.log("  ⚠ detect_store: game_folder не задана, запустите find_game_folder раньше")
            return False

        result  = _pf_detect_game_store(game_folder, step, self.ctx)
        store   = result["store"]
        version = result["version"]
        evidence = result["evidence"]
        votes    = result.get("votes", {})

        self.ctx["store"]   = store
        self.ctx["version"] = version
        self.ctx["user_vars"]["store"]   = store
        self.ctx["user_vars"]["version"] = version

        store_icon = {"steam": "🎮", "gog": "🌌", "epic": "⚡", "other": "📦"}.get(store, "❓")
        self.log(f"  {store_icon} Магазин игры: {store.upper()}")

        if votes:
            vote_str = "  " + "  ".join(
                f"{s.upper()}:{v}" for s, v in sorted(votes.items(), key=lambda x: -x[1]) if v > 0
            )
            if vote_str.strip():
                self.log(f"  📊 Голоса детектора:{vote_str}")

        if version:
            self.log(f"  🏷  Версия игры: {version}")

        if evidence:
            shown = evidence[:4]
            rest  = len(evidence) - 4
            self.log("  🔍 Признаки: " + ", ".join(shown) + (f" + ещё {rest}" if rest > 0 else ""))

        if store in ("gog", "epic"):
            self.log(f"  ℹ  Игра установлена через {store.upper()}, но мод скачан через SteamCMD")

        return True

    def _step_read_file(self, step: dict) -> bool:
        save_as = step.get("save_as", "read_value")
        base    = self.ctx.get("game_folder", self.ctx.get("mod_folder", ""))
        value   = _pf_read_file_value(base, step, self.ctx)

        if value is not None:
            self.ctx["user_vars"][save_as] = value
            self.log(f"  📄 {save_as} = {value!r}")
            return True
        else:
            fallback = step.get("fallback")
            if fallback is not None:
                self.ctx["user_vars"][save_as] = str(fallback)
                self.log(f"  📄 {save_as} = {fallback!r} (fallback)")
                return True
            self.log(f"  ⚠ read_file: значение не найдено ({step.get('file', '?')})")
            return not step.get("required", False)

    def _step_copy(self, step: dict) -> bool:
        src = step.get("src", "{mod_folder}").format(**self._tpl())
        dst = step.get("dst", "{game_folder}").format(**self._tpl())
        if not dst:
            self.log("  ⚠ Целевая папка не задана (нет game_folder?)")
            return False
        os.makedirs(dst, exist_ok=True)
        copied = _pf_smart_copy(src, dst, step, self.log)
        return bool(copied) or not step.get("required", False)

    def _step_rename(self, step: dict) -> bool:
        base = step.get("base", "{game_folder}").format(**self._tpl())
        rules = step.get("rules", [step])
        count = _pf_rename_files(base, rules, self.log)
        self.log(f"  📝 Переименовано файлов: {count}")
        return True

    def _step_delete(self, step: dict) -> bool:
        base  = step.get("base", "{game_folder}").format(**self._tpl())
        rules = step.get("rules", [step])
        count = _pf_delete_files(base, rules, self.log)
        self.log(f"  🗑 Удалено объектов: {count}")
        return True

    def _step_backup(self, step: dict) -> bool:
        tpl    = self._tpl()
        path   = step.get("path", "").format(**tpl)
        suffix = step.get("suffix", ".bak")
        keep   = int(step.get("keep", 3))

        if not path:
            self.log("  ⚠ backup: не задан path")
            return False

        if step.get("folder") and os.path.isdir(path):
            zip_path = path.rstrip("/\\") + suffix + ".zip"
            try:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for dp, _, files in os.walk(path):
                        for f in files:
                            fp = os.path.join(dp, f)
                            zf.write(fp, os.path.relpath(fp, os.path.dirname(path)))
                self.log(f"  💾 бэкап папки: {os.path.basename(zip_path)}")
                return True
            except Exception as e:
                self.log(f"  ❌ ошибка бэкапа папки: {e}")
                return False

        if os.path.isfile(path):
            result = _pf_backup_file(path, self.log, suffix=suffix, keep=keep)
            return result is not None
        matches = glob.glob(path)
        if not matches:
            self.log(f"  ⚠ backup: файл не найден: {path}")
            return not step.get("required", False)
        for fp in matches:
            _pf_backup_file(fp, self.log, suffix=suffix, keep=keep)
        return True

    def _step_check_disk(self, step: dict) -> bool:
        tpl     = self._tpl()
        path    = step.get("path", tpl.get("game_folder") or tpl.get("mod_folder", "."))
        path    = path.format(**tpl)
        req_mb  = int(step.get("required_mb", 0))
        save_as = step.get("save_as", "")
        result  = _pf_check_disk(path or ".", req_mb)
        ok      = result["ok"]
        free_mb = result["free_mb"]
        status = "✅" if ok else "⚠"
        self.log(f"  {status} Диск {path}: свободно {free_mb} МБ, требуется {req_mb} МБ — {'OK' if ok else 'НЕДОСТАТОЧНО'}")
        if save_as:
            self.ctx["user_vars"][save_as] = "true" if ok else "false"
            self.log(f"  📌 {save_as} = {'true' if ok else 'false'}")
        if not ok and step.get("required", False):
            self.log(f"  🛑 Недостаточно места: нужно {req_mb} МБ, доступно {free_mb} МБ")
            return False
        return True

    def _step_patch_ini(self, step: dict) -> bool:
        path = step.get("file", "").format(**self._tpl())
        return _pf_patch_ini(path, step.get("patches", []), self.log)

    def _step_patch_json(self, step: dict) -> bool:
        path = step.get("file", "").format(**self._tpl())
        return _pf_patch_json(path, step.get("patches", []), self.log)

    def _step_patch_xml(self, step: dict) -> bool:
        path = step.get("file", "").format(**self._tpl())
        return _pf_patch_xml(path, step.get("patches", []), self.log)

    def _step_patch_cfg(self, step: dict) -> bool:
        path = step.get("file", "").format(**self._tpl())
        return _pf_patch_cfg(path, step.get("patches", []), self.log)

    def _step_plugin(self, step: dict) -> bool:
        plugin_file = step.get("plugin_file", "")
        plugin_url  = step.get("plugin_url", "")

        if plugin_url:
            fname = os.path.basename(plugin_url.split("?")[0]) or "plugin_temp.py"
            plugin_path = os.path.join(INSTALL_LOCAL_DIR, "plugins", fname)
            os.makedirs(os.path.dirname(plugin_path), exist_ok=True)
            try:
                r = requests.get(plugin_url, timeout=10)
                r.raise_for_status()
                with open(plugin_path, "w", encoding="utf-8") as f:
                    f.write(r.text)
            except Exception as e:
                self.log(f"  ❌ Не удалось скачать плагин: {e}")
                return False
        elif plugin_file:
            plugin_path = os.path.join(INSTALL_LOCAL_DIR, "plugins", plugin_file)
            if not os.path.isfile(plugin_path):
                self.log(f"  ❌ Плагин не найден: {plugin_path}")
                return False
        else:
            self.log("  ❌ plugin: не указан plugin_file или plugin_url")
            return False

        try:
            spec   = importlib.util.spec_from_file_location("wdl_plugin", plugin_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            mode       = self.ctx.get("_install_mode", "install")
            fn_name    = "uninstall" if mode == "uninstall" else "install"
            fn         = getattr(module, fn_name, None)
            if fn is None:
                self.log(f"  ⚠ плагин не содержит функцию {fn_name}(), пропуск")
                return True
            plugin_ctx = {**self.ctx, **step.get("params", {})}
            return bool(fn(plugin_ctx, self.log))
        except Exception as e:
            self.log(f"  ❌ Ошибка выполнения плагина: {e}")
            return False

    def _tpl(self) -> dict:
        base = {
            "USERPROFILE":    self.ctx.get("USERPROFILE",  os.path.expanduser("~")),
            "APPDATA":        self.ctx.get("APPDATA",      os.environ.get("APPDATA", "")),
            "LOCALAPPDATA":   self.ctx.get("LOCALAPPDATA", os.environ.get("LOCALAPPDATA", "")),
            "PROGRAMFILES":   self.ctx.get("PROGRAMFILES", os.environ.get("ProgramFiles", "")),
            "PROGRAMFILES86": self.ctx.get("PROGRAMFILES86", os.environ.get("ProgramFiles(x86)", "")),
            "STEAM":          self.ctx.get("STEAM",        _find_steam_path()),

            "game_id":   self.ctx.get("game_id",   ""),
            "mod_id":    self.ctx.get("mod_id",    ""),
            "game_name": self.ctx.get("game_name", ""),
            "mod_index":    self.ctx.get("mod_index",    "0"),
            "mod_number":   self.ctx.get("mod_number",   "1"),
            "mod_total":    self.ctx.get("mod_total",    "1"),
            "mod_count":    self.ctx.get("mod_count",    "1"),
            "mod_is_first": self.ctx.get("mod_is_first", "true"),
            "mod_is_last":  self.ctx.get("mod_is_last",  "true"),

            "game_folder":    self.ctx.get("game_folder",    ""),
            "mod_folder":     self.ctx.get("mod_folder",     ""),
            "content_folder": self.ctx.get("content_folder", ""),
            "steamcmd_root":  self.ctx.get("steamcmd_root",  ""),

            "store":    self.ctx.get("store",    ""),
            "version":  self.ctx.get("version",  ""),
            "platform": self.ctx.get("platform", ""),
        }
        base.update(self.ctx.get("user_vars", {}))
        return base

    def run_uninstall(self) -> bool:
        steps = self.recipe.get("uninstall", [])
        if not steps:
            self.log("  ℹ Блок uninstall в инструкции не найден")
            return False
        self.ctx["_install_mode"] = "uninstall"
        self.log("🗑 Запуск деинсталляции мода...")
        return self._exec_steps(steps)