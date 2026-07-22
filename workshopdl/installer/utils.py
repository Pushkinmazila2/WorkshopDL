"""
Параметрические утилиты-функции (строительные блоки декларативного DSL).
"""

import os, re, json, configparser, glob, fnmatch, shutil, zipfile


def _pf_read_file_value(base_folder: str, params: dict, ctx: dict) -> str | None:
    """
    Универсальная параметрическая функция чтения значения из файла.
    """
    tpl_vars = {
        "game_folder":  ctx.get("game_folder", base_folder),
        "mod_folder":   ctx.get("mod_folder", ""),
        "APPDATA":      os.environ.get("APPDATA", ""),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
        "USERPROFILE":  os.path.expanduser("~"),
        **ctx.get("user_vars", {}),
    }
    fallback = params.get("fallback")

    raw_file = params.get("file", "")
    try:
        raw_file = raw_file.format(**tpl_vars)
    except KeyError:
        pass

    if not os.path.isabs(raw_file):
        raw_file = os.path.join(base_folder, raw_file)

    matches = glob.glob(raw_file, recursive=True)
    filepath = matches[0] if matches else raw_file

    if not os.path.isfile(filepath):
        return fallback

    fmt = params.get("format", "auto")
    if fmt == "auto":
        ext = os.path.splitext(filepath)[1].lower()
        if ext in (".json",):                              fmt = "json"
        elif ext in (".ini", ".cfg", ".conf", ".toml"):    fmt = "ini"
        elif ext in (".exe", ".dll", ".bin", ".pak"):      fmt = "binary"
        else:                                              fmt = "text"

    extract = params.get("extract", {})
    result  = None

    if fmt == "text":
        try:
            enc  = extract.get("encoding", "utf-8")
            text = open(filepath, encoding=enc, errors="replace").read()
        except Exception:
            return fallback

        regex = extract.get("regex")
        if regex:
            m = re.search(regex, text, re.MULTILINE)
            result = m.group(1) if m and m.lastindex else (m.group(0) if m else None)
        else:
            lines = text.splitlines()
            line_no = extract.get("line", 0)
            if lines:
                result = lines[line_no] if abs(line_no) < len(lines) else lines[-1]
            else:
                result = text

    elif fmt == "json":
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return fallback

        path_keys = extract.get("path", "").split(".")
        node = data
        for k in path_keys:
            if not k:
                continue
            if isinstance(node, dict):
                node = node.get(k)
            elif isinstance(node, list):
                try:
                    node = node[int(k)]
                except (ValueError, IndexError):
                    node = None
            else:
                node = None
            if node is None:
                return fallback

        result = str(node) if node is not None else None
        regex = extract.get("regex")
        if result and regex:
            m = re.search(regex, result)
            result = m.group(1) if m and m.lastindex else (m.group(0) if m else result)

    elif fmt == "ini":
        try:
            cfg = configparser.ConfigParser(strict=False)
            cfg.optionxform = str
            cfg.read(filepath, encoding="utf-8")
        except Exception:
            return fallback

        section = extract.get("section", "DEFAULT")
        key     = extract.get("key", "")
        try:
            result = cfg.get(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

        regex = extract.get("regex")
        if result and regex:
            m = re.search(regex, result)
            result = m.group(1) if m and m.lastindex else (m.group(0) if m else result)

    elif fmt == "binary":
        try:
            offset_raw = extract.get("offset", 0)
            offset = int(offset_raw, 16) if isinstance(offset_raw, str) and offset_raw.startswith("0x") \
                     else int(offset_raw)
            length   = int(extract.get("length", 256))
            encoding = extract.get("encoding", "utf-8")

            with open(filepath, "rb") as f:
                f.seek(offset)
                raw_bytes = f.read(length)

            text = raw_bytes.split(b"\x00")[0].decode(encoding, errors="replace")
            regex = extract.get("regex")
            if regex:
                m = re.search(regex, text)
                result = m.group(1) if m and m.lastindex else (m.group(0) if m else None)
            else:
                result = text.strip()
        except Exception:
            return fallback

    if result is None:
        return fallback
    result = str(result)
    if extract.get("strip", True):
        result = result.strip()

    transform = params.get("transform", "")
    if transform == "strip":
        result = result.strip()
    elif transform == "lower":
        result = result.lower()
    elif transform == "upper":
        result = result.upper()
    elif transform.startswith("split_first:"):
        sep = transform[12:] or "."
        result = result.split(sep)[0]
    elif transform.startswith("split_last:"):
        sep = transform[11:] or "."
        result = result.split(sep)[-1]

    return result or fallback


def _pf_smart_copy(src_root: str, dst_root: str, params: dict, log_cb) -> list[str]:
    """
    Функция умного копирования и распаковки (основной Action).
    """
    copied = []
    flatten = params.get("flatten", False)

    for rule in params.get("files", []):
        pattern  = rule.get("from", "**")
        rel_dst  = rule.get("to", ".")
        overwrite = rule.get("overwrite", True)
        do_extract = rule.get("extract", False)

        full_pattern = os.path.join(src_root, pattern)
        matches = glob.glob(full_pattern, recursive=True)
        if not matches:
            matches = [
                os.path.join(dp, f)
                for dp, _, files in os.walk(src_root)
                for f in files
                if fnmatch.fnmatch(f, os.path.basename(pattern))
            ]

        abs_dst = os.path.join(dst_root, rel_dst)
        os.makedirs(abs_dst, exist_ok=True)

        for src_file in matches:
            if os.path.isdir(src_file):
                continue
            if flatten:
                dst_file = os.path.join(abs_dst, os.path.basename(src_file))
            else:
                rel = os.path.relpath(src_file, src_root)
                dst_file = os.path.join(abs_dst, rel)
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)

            if os.path.exists(dst_file) and not overwrite:
                log_cb(f"  ⏭ пропуск (уже есть): {os.path.basename(dst_file)}")
                continue

            if do_extract and src_file.lower().endswith(".zip"):
                log_cb(f"  📦 распаковка: {os.path.basename(src_file)} → {rel_dst}")
                try:
                    with zipfile.ZipFile(src_file, "r") as z:
                        z.extractall(abs_dst)
                    copied.append(abs_dst)
                except Exception as e:
                    log_cb(f"  ❌ ошибка распаковки: {e}")
            else:
                try:
                    shutil.copy2(src_file, dst_file)
                    copied.append(dst_file)
                    log_cb(f"  ✅ скопировано: {os.path.relpath(dst_file, dst_root)}")
                except Exception as e:
                    log_cb(f"  ❌ ошибка копирования {os.path.basename(src_file)}: {e}")
    return copied


def _pf_backup_file(filepath: str, log_cb, suffix: str = ".bak", keep: int = 3) -> str | None:
    """
    Создаёт резервную копию файла.
    """
    if not os.path.isfile(filepath):
        log_cb(f"  ⚠ backup: файл не найден: {filepath}")
        return None

    base = filepath + suffix
    for i in range(keep - 1, 0, -1):
        old = f"{base}.{i}"
        new = f"{base}.{i+1}" if i + 1 < keep else None
        if os.path.exists(old):
            if new:
                try:
                    shutil.copy2(old, new)
                except Exception:
                    pass
            try:
                os.remove(old)
            except Exception:
                pass
    if os.path.exists(base):
        try:
            shutil.copy2(base, base + ".1")
            os.remove(base)
        except Exception:
            pass

    try:
        shutil.copy2(filepath, base)
        log_cb(f"  💾 бэкап создан: {os.path.basename(base)}")
        return base
    except Exception as e:
        log_cb(f"  ❌ ошибка создания бэкапа: {e}")
        return None


def _pf_check_disk(path: str, required_mb: int) -> dict:
    """
    Проверка свободного места на диске.
    """
    try:
        usage   = shutil.disk_usage(path)
        free_mb = usage.free // (1024 * 1024)
        return {"ok": free_mb >= required_mb, "free_mb": free_mb, "required_mb": required_mb, "path": path}
    except Exception as e:
        return {"ok": False, "free_mb": 0, "required_mb": required_mb, "path": path, "error": str(e)}


def _pf_rename_files(base_folder: str, rules: list, log_cb) -> int:
    """
    Функция переименования файлов по regex.
    """
    renamed = 0
    for rule in rules:
        file_glob   = rule.get("glob", "**/*")
        pattern     = rule.get("pattern", "")
        replacement = rule.get("replacement", "")
        recursive   = rule.get("recursive", True)
        dry_run     = rule.get("dry_run", False)

        if not pattern:
            log_cb("  ⚠ rename: не задан pattern")
            continue

        matches = glob.glob(os.path.join(base_folder, file_glob), recursive=recursive)
        for fpath in matches:
            if os.path.isdir(fpath):
                continue
            dirname  = os.path.dirname(fpath)
            basename = os.path.basename(fpath)
            new_name = re.sub(pattern, replacement, basename)
            if new_name == basename:
                continue
            new_path = os.path.join(dirname, new_name)
            if dry_run:
                log_cb(f"  🔍 [dry_run] переименую: {basename} → {new_name}")
            else:
                try:
                    os.rename(fpath, new_path)
                    log_cb(f"  📝 переименован: {basename} → {new_name}")
                    renamed += 1
                except Exception as e:
                    log_cb(f"  ❌ ошибка переименования {basename}: {e}")
    return renamed


def _pf_delete_files(base_folder: str, rules: list, log_cb) -> int:
    """
    Функция удаления файлов и папок.
    """
    deleted = 0
    for rule in rules:
        pattern    = rule.get("glob", "")
        recursive  = rule.get("recursive", False)
        missing_ok = rule.get("missing_ok", True)
        dry_run    = rule.get("dry_run", False)

        if not pattern:
            log_cb("  ⚠ delete: не задан glob")
            continue

        matches = glob.glob(os.path.join(base_folder, pattern), recursive=True)
        if not matches and not missing_ok:
            log_cb(f"  ⚠ delete: не найдено файлов по паттерну {pattern}")
            continue

        for fpath in matches:
            if dry_run:
                log_cb(f"  🔍 [dry_run] удалю: {os.path.relpath(fpath, base_folder)}")
                continue
            try:
                if os.path.isdir(fpath):
                    if recursive:
                        shutil.rmtree(fpath)
                        log_cb(f"  🗑 удалена папка: {os.path.relpath(fpath, base_folder)}")
                        deleted += 1
                    else:
                        log_cb(f"  ⚠ {fpath} — папка, укажите recursive=true")
                else:
                    os.remove(fpath)
                    log_cb(f"  🗑 удалён файл: {os.path.relpath(fpath, base_folder)}")
                    deleted += 1
            except Exception as e:
                log_cb(f"  ❌ ошибка удаления {os.path.basename(fpath)}: {e}")
    return deleted