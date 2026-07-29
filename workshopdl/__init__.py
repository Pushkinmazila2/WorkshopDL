"""
WorkshopDL — Python Edition v4
Пакетная структура модулей.
"""

# Версия: приоритет у сгенерированного CI файла, иначе fallback
try:
    from workshopdl._version_generated import __version__  # type: ignore
except ImportError:
    __version__ = "4.0"

__app_name__ = "WorkshopDL"
