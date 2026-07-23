"""
Точка входа WorkshopDL.
"""

import sys, os
from PyQt5.QtWidgets import QApplication

from workshopdl.config import MODULES_PATH
from workshopdl.localization import lang_load
from workshopdl.ui.main_window import MainWindow


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