"""
Расширенный вычислитель условий (when) для шагов установки.
"""

import os, re, shutil

from workshopdl.config import IS_WIN, IS_MAC, IS_LINUX


def _pf_safe_eval_condition(condition: str, ctx: dict) -> bool:
    """
    Расширенный вычислитель условий (when).

    Поддерживает логические выражения с &&, ||, !, скобки:
      "(store == 'steam' || store == 'gog') && version != ''"
      "file_exists('{game_folder}/game.exe') && platform == 'win'"
      "!file_exists('{game_folder}/mod_list.xml')"

    Атомарные выражения:
      store == 'steam'              — сравнение переменной ctx
      version != ''                 — неравенство
      version >= '1.5'              — лексикографическое сравнение
      platform == 'win'|'linux'|'mac'
      file_exists('path')           — файл существует
      dir_exists('path')            — папка существует
      file_contains('path','regex') — файл содержит паттерн
      disk_free('path') > 1000      — свободное место в МБ
      env_set('VAR')                — переменная окружения задана
      env('VAR') == 'value'         — значение переменной окружения
      var_set('name')               — переменная ctx задана и не пуста
      True / False                  — литералы
    """
    if not condition:
        return True

    cond = condition.strip()

    tpl = _build_tpl(ctx)
    try:
        cond = cond.format(**tpl)
    except (KeyError, ValueError):
        pass

    return _eval_expr(cond, ctx)


def _build_tpl(ctx: dict) -> dict:
    """Собирает словарь для подстановки {var} в when-условиях из ctx."""
    tpl = {
        "USERPROFILE":    ctx.get("USERPROFILE",  os.path.expanduser("~")),
        "APPDATA":        ctx.get("APPDATA",      os.environ.get("APPDATA", "")),
        "LOCALAPPDATA":   ctx.get("LOCALAPPDATA", os.environ.get("LOCALAPPDATA", "")),
        "PROGRAMFILES":   ctx.get("PROGRAMFILES", os.environ.get("ProgramFiles", "")),
        "PROGRAMFILES86": ctx.get("PROGRAMFILES86", os.environ.get("ProgramFiles(x86)", "")),
        "STEAM":          ctx.get("STEAM", ""),

        "game_id":   ctx.get("game_id",   ""),
        "mod_id":    ctx.get("mod_id",    ""),
        "game_name": ctx.get("game_name", ""),
        "mod_index":    ctx.get("mod_index",    "0"),
        "mod_number":   ctx.get("mod_number",   "1"),
        "mod_total":    ctx.get("mod_total",    "1"),
        "mod_count":    ctx.get("mod_count",    "1"),
        "mod_is_first": ctx.get("mod_is_first", "true"),
        "mod_is_last":  ctx.get("mod_is_last",  "true"),

        "game_folder":    ctx.get("game_folder",    ""),
        "mod_folder":     ctx.get("mod_folder",     ""),
        "content_folder": ctx.get("content_folder", ""),
        "steamcmd_root":  ctx.get("steamcmd_root",  ""),

        "store":    ctx.get("store",    ""),
        "version":  ctx.get("version",  ""),
        "platform": ctx.get("platform", ""),

        "is_win":   ctx.get("is_win",   str(IS_WIN).lower()),
        "is_linux": ctx.get("is_linux", str(IS_LINUX).lower()),
        "is_mac":   ctx.get("is_mac",   str(IS_MAC).lower()),
    }
    tpl.update(ctx.get("user_vars", {}))
    return tpl


def _eval_expr(expr: str, ctx: dict) -> bool:
    """Рекурсивный парсер логических выражений."""
    expr = expr.strip()
    if not expr:
        return True

    if expr.startswith("("):
        depth = 0
        for i, ch in enumerate(expr):
            if ch == "(": depth += 1
            elif ch == ")": depth -= 1
            if depth == 0:
                inner  = expr[1:i]
                rest   = expr[i+1:].strip()
                result = _eval_expr(inner, ctx)
                if not rest:
                    return result
                if rest.startswith("&&"):
                    return result and _eval_expr(rest[2:].strip(), ctx)
                if rest.startswith("||"):
                    return result or  _eval_expr(rest[2:].strip(), ctx)
                return result

    if expr.startswith("!") and not expr.startswith("!="):
        return not _eval_expr(expr[1:].strip(), ctx)

    idx = _find_operator(expr, "||")
    if idx >= 0:
        return _eval_expr(expr[:idx], ctx) or _eval_expr(expr[idx+2:], ctx)

    idx = _find_operator(expr, "&&")
    if idx >= 0:
        return _eval_expr(expr[:idx], ctx) and _eval_expr(expr[idx+2:], ctx)

    return _eval_atom(expr.strip(), ctx)


def _find_operator(expr: str, op: str) -> int:
    """Ищет оператор op вне скобок и строковых литералов."""
    depth = 0
    in_str = None
    i = 0
    while i < len(expr):
        ch = expr[i]
        if in_str:
            if ch == in_str:
                in_str = None
        elif ch in ('"', "'"):
            in_str = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and expr[i:i+len(op)] == op:
            return i
        i += 1
    return -1


def _eval_atom(atom: str, ctx: dict) -> bool:
    """Вычисляет одно атомарное условие."""
    atom = atom.strip()
    vars_ = ctx.get("user_vars", {})

    m = re.match(r"^file_exists\(['\"](.*?)['\"]\)$", atom)
    if m:
        return os.path.isfile(m.group(1))

    m = re.match(r"^dir_exists\(['\"](.*?)['\"]\)$", atom)
    if m:
        return os.path.isdir(m.group(1))

    m = re.match(r"^file_contains\(['\"](.*?)['\"],\s*['\"](.*?)['\"]\)$", atom)
    if m:
        fpath, pattern = m.group(1), m.group(2)
        try:
            content = open(fpath, encoding="utf-8", errors="replace").read()
            return bool(re.search(pattern, content))
        except Exception:
            return False

    m = re.match(r"^disk_free\(['\"](.*?)['\"]\)\s*(>=|>|==|<|<=)\s*(\d+)$", atom)
    if m:
        path_, op_, mb_ = m.group(1), m.group(2), int(m.group(3))
        try:
            free_mb = shutil.disk_usage(path_).free // (1024 * 1024)
            return _compare(free_mb, op_, mb_)
        except Exception:
            return False

    m = re.match(r"^env_set\(['\"](.*?)['\"]\)$", atom)
    if m:
        return bool(os.environ.get(m.group(1), ""))

    m = re.match(r"^env\(['\"](.*?)['\"]\)\s*(==|!=)\s*['\"]?(.*?)['\"]?$", atom)
    if m:
        env_val = os.environ.get(m.group(1), "")
        return _compare_str(env_val, m.group(2), m.group(3))

    m = re.match(r"^var_set\(['\"](.*?)['\"]\)$", atom)
    if m:
        return bool(vars_.get(m.group(1), ""))

    m = re.match(r"^platform\s*(==|!=)\s*['\"](\w+)['\"]$", atom)
    if m:
        op_, plat = m.group(1), m.group(2).lower()
        current = "win" if IS_WIN else ("mac" if IS_MAC else "linux")
        return _compare_str(current, op_, plat)

    m = re.match(r"^(\w+)\s*(==|!=|>=|<=|>|<)\s*['\"]?(.*?)['\"]?$", atom)
    if m:
        var_name, op_, rhs = m.group(1), m.group(2), m.group(3)
        lhs = str(vars_.get(var_name, ctx.get(var_name, "")))
        return _compare_str(lhs, op_, rhs)

    if atom.lower() in ("true", "1", "yes"):  return True
    if atom.lower() in ("false", "0", "no"):  return False

    return bool(atom)


def _compare(a, op: str, b) -> bool:
    if op == "==": return a == b
    if op == "!=": return a != b
    if op == ">":  return a > b
    if op == ">=": return a >= b
    if op == "<":  return a < b
    if op == "<=": return a <= b
    return False

def _compare_str(a: str, op: str, b: str) -> bool:
    return _compare(a, op, b)