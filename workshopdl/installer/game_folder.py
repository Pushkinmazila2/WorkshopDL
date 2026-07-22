"""
Параметрическая функция автоматического поиска папки игры.
"""

import os, glob

from workshopdl.config import IS_WIN


def _find_steam_path() -> str:
    """Находит корень Steam на текущей платформе."""
    if IS_WIN:
        candidates = [
            os.path.expandvars(r"%ProgramFiles(x86)%\Steam"),
            os.path.expandvars(r"%ProgramFiles%\Steam"),
            r"C:\Steam",
        ]
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\WOW6432Node\Valve\Steam") as k:
                val, _ = winreg.QueryValueEx(k, "InstallPath")
                candidates.insert(0, str(val))
        except Exception:
            pass
    elif IS_MAC:
        candidates = [os.path.expanduser("~/Library/Application Support/Steam")]
    else:
        candidates = [
            os.path.expanduser("~/.steam/steam"),
            os.path.expanduser("~/.local/share/Steam"),
        ]
    for p in candidates:
        if os.path.isdir(p):
            return p
    return ""


def _pf_find_game_folder(params: dict, ctx: dict) -> str | None:
    """
    Параметрическая функция автоматического поиска папки игры.
    params:
      candidates  — список возможных путей (поддерживает {STEAM}, {USERPROFILE}, glob-паттерны)
      registry    — список ключей реестра Windows (только Windows)
      env_hints   — список переменных окружения
    Возвращает найденный путь или None.
    """
    tpl_vars = {
        "STEAM":        _find_steam_path(),
        "USERPROFILE":  os.path.expanduser("~"),
        "APPDATA":      os.environ.get("APPDATA", ""),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
        "PROGRAMFILES": os.environ.get("ProgramFiles", "C:\\Program Files"),
        "PROGRAMFILES86": os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
    }
    tpl_vars.update(ctx.get("user_vars", {}))

    candidates = params.get("candidates", [])
    for pattern in candidates:
        try:
            expanded = pattern.format(**tpl_vars)
        except KeyError:
            expanded = pattern
        matches = glob.glob(expanded, recursive=True)
        if matches:
            return matches[0]
        if os.path.isdir(expanded):
            return expanded

    if IS_WIN and params.get("registry"):
        import winreg
        for reg_path in params["registry"]:
            try:
                parts = reg_path.split("\\")
                root_map = {
                    "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
                    "HKEY_CURRENT_USER":  winreg.HKEY_CURRENT_USER,
                }
                root = root_map.get(parts[0], winreg.HKEY_LOCAL_MACHINE)
                key_path = "\\".join(parts[1:-1])
                value_name = parts[-1]
                with winreg.OpenKey(root, key_path) as k:
                    val, _ = winreg.QueryValueEx(k, value_name)
                    if os.path.isdir(str(val)):
                        return str(val)
            except Exception:
                pass

    for env in params.get("env_hints", []):
        val = os.environ.get(env, "")
        if val and os.path.isdir(val):
            return val

    return None