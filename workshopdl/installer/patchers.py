"""
Функции для работы с конфигами: INI, JSON, XML, CFG.
"""

import os, re, json, configparser

from workshopdl.installer.utils import _pf_backup_file


def _pf_patch_ini(filepath: str, patches: list, log_cb) -> bool:
    """Функция для работы с INI файлами."""
    if not os.path.isfile(filepath):
        log_cb(f"  ⚠ INI не найден: {filepath}")
        return False
    cfg = configparser.ConfigParser(strict=False)
    cfg.optionxform = str
    cfg.read(filepath, encoding="utf-8")
    for patch in patches:
        sec = patch.get("section", "DEFAULT")
        key = patch.get("key", "")
        val = str(patch.get("value", ""))
        create = patch.get("create_if_missing", True)
        if sec not in cfg:
            if create:
                cfg[sec] = {}
            else:
                log_cb(f"  ⚠ секция [{sec}] не найдена, пропуск")
                continue
        cfg[sec][key] = val
        log_cb(f"  ✏ INI [{sec}] {key} = {val}")
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            cfg.write(f)
        return True
    except Exception as e:
        log_cb(f"  ❌ ошибка записи INI: {e}")
        return False


def _pf_patch_json(filepath: str, patches: list, log_cb) -> bool:
    """Функция для работы с JSON конфигами."""
    if not os.path.isfile(filepath):
        log_cb(f"  ⚠ JSON не найден: {filepath}")
        return False
    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log_cb(f"  ❌ ошибка чтения JSON: {e}")
        return False

    for patch in patches:
        key_path = patch.get("path", "")
        value    = patch.get("value")
        create   = patch.get("create_if_missing", True)
        keys     = key_path.split(".")
        node     = data
        try:
            for k in keys[:-1]:
                if k not in node and create:
                    node[k] = {}
                node = node[k]
            node[keys[-1]] = value
            log_cb(f"  ✏ JSON {key_path} = {json.dumps(value, ensure_ascii=False)}")
        except Exception as e:
            log_cb(f"  ⚠ не удалось применить патч {key_path}: {e}")

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log_cb(f"  ❌ ошибка записи JSON: {e}")
        return False


def _pf_patch_xml(filepath: str, patches: list, log_cb) -> bool:
    """Функция для работы с XML конфигами."""
    try:
        import xml.etree.ElementTree as ET
    except ImportError:
        log_cb("  ❌ xml.etree.ElementTree недоступен")
        return False

    if not os.path.isfile(filepath):
        log_cb(f"  ⚠ XML не найден: {filepath}")
        return False
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
    except Exception as e:
        log_cb(f"  ❌ Ошибка парсинга XML: {e}")
        return False

    for patch in patches:
        xpath   = patch.get("xpath", "")
        attr    = patch.get("attribute", "")
        value   = str(patch.get("value", ""))
        action  = patch.get("action", "set")
        create  = patch.get("create_if_missing", False)

        elements = root.findall(xpath)
        if not elements:
            if create and action == "set":
                parts = xpath.strip("./").split("/")
                node = root
                for part in parts:
                    child = node.find(part)
                    if child is None:
                        child = ET.SubElement(node, part)
                    node = child
                elements = [node]
            else:
                log_cb(f"  ⚠ XML xpath не найден: {xpath}")
                continue

        for el in elements:
            if action == "set":
                if attr:
                    el.set(attr, value)
                    log_cb(f"  ✏ XML {xpath} @{attr} = {value}")
                else:
                    el.text = value
                    log_cb(f"  ✏ XML {xpath} text = {value}")
            elif action == "delete":
                parent = root.find(xpath + "/..")
                if parent is not None:
                    parent.remove(el)
                    log_cb(f"  🗑 XML удалён элемент {xpath}")
            elif action == "append_child":
                try:
                    child = ET.fromstring(value)
                    el.append(child)
                    log_cb(f"  ➕ XML добавлен дочерний элемент в {xpath}")
                except Exception as e:
                    log_cb(f"  ❌ XML append_child: {e}")

    try:
        ET.indent(tree, space="  ")
        tree.write(filepath, encoding="unicode", xml_declaration=True)
        return True
    except AttributeError:
        tree.write(filepath, encoding="unicode", xml_declaration=True)
        return True
    except Exception as e:
        log_cb(f"  ❌ Ошибка записи XML: {e}")
        return False


def _pf_patch_cfg(filepath: str, patches: list, log_cb) -> bool:
    """Функция для работы с CFG/простыми конфигами формата 'key = value' или 'key value'."""
    if not os.path.isfile(filepath):
        log_cb(f"  ⚠ CFG не найден: {filepath}")
        return False
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        log_cb(f"  ❌ Ошибка чтения CFG: {e}")
        return False

    for patch in patches:
        key       = patch.get("key", "")
        value     = str(patch.get("value", ""))
        sep       = patch.get("separator", " = ")
        create    = patch.get("create_if_missing", True)
        section   = patch.get("section", "")
        found     = False
        in_section = not section

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                in_section = (stripped[1:-1].strip() == section)
                continue
            if not in_section:
                continue
            if stripped.startswith(("#", "//")):
                continue
            m = re.match(rf"^({re.escape(key)})\s*[=: ]\s*(.*)$", stripped)
            if m:
                new_line = f"{key}{sep}{value}\n"
                lines[idx] = new_line
                log_cb(f"  ✏ CFG {key}{sep}{value}")
                found = True
                break

        if not found and create:
            lines.append(f"{key}{sep}{value}\n")
            log_cb(f"  ➕ CFG добавлен {key}{sep}{value}")

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception as e:
        log_cb(f"  ❌ Ошибка записи CFG: {e}")
        return False