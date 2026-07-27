"""
Точка входа WorkshopDL.
"""

import sys
import os
import traceback
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import qInstallMessageHandler

from workshopdl.config import MODULES_PATH
from workshopdl.localization import lang_load
from workshopdl.ui.main_window import MainWindow


# =====================================================================
# 1. СИСТЕМНЫЙ ЛОВЕЦ ДЛЯ PYTHON (Ловит исключения, синтаксис, потоки)
# =====================================================================
def global_exception_handler(ex_cls, ex, tb):
    error_msg = "".join(traceback.format_exception(ex_cls, ex, tb))
    
    # Записываем ошибку в файл crash.log
    with open("crash.log", "w", encoding="utf-8") as f:
        f.write("=== КРИТИЧЕСКИЙ СБОЙ PYTHON ===\n")
        f.write(error_msg)
        
    print(error_msg) # Дублируем в консоль
    
    # Показываем красивое окно пользователю, если QApplication жив
    if QApplication.instance():
        QMessageBox.critical(
            None, 
            "Критическая ошибка", 
            f"Программа завершила работу из-за ошибки.\n\nЛог сохранен в crash.log\n\n{ex}"
        )
    sys.exit(1)

sys.excepthook = global_exception_handler


# =====================================================================
# 2. СИСТЕМНЫЙ ЛОВЕЦ ДЛЯ QT (Перехватывает BEX64 / 0xc0000409 в Qt5Core)
# =====================================================================
# Отключаем фатальную реакцию Qt на системные предупреждения Windows
os.environ["QT_FATAL_WARNINGS"] = "0"

# Принудительно отключаем аппаратное ускорение, так как в логах падал видеодрайвер
os.environ["QT_OPENGL"] = "software"
os.environ["QT_QUICK_BACKEND"] = "software"

def qt_message_handler(mode, context, message):
    # Пишем все скрытые внутренние предупреждения Qt в файл
    with open("qt_internal.log", "a", encoding="utf-8") as f:
        f.write(f"[{mode}] Context: {context.file}:{context.line} -> {message}\n")

qInstallMessageHandler(qt_message_handler)
# =====================================================================


def main():
    os.makedirs(MODULES_PATH, exist_ok=True)
    lang_load()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
