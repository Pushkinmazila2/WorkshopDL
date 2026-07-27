"""
Фоновый QThread для проверки обновлений программы.
"""

import os
from PyQt5.QtCore import QThread, pyqtSignal

from workshopdl import __version__
from workshopdl.config import UPDATE_TEMP_DIR, UPDATE_CHANNEL_DEFAULT
from workshopdl.updater import check_for_updates, download_update, apply_update


class AppUpdateWorker(QThread):
    """
    Проверяет наличие обновления и опционально скачивает его.

    Сигналы:
        update_available(version: str, download_url: str, body: str, prerelease: bool)
        no_update()
        check_error(error_msg: str)
        download_progress(current: int, total: int)
        download_done(archive_path: str)
        download_error(error_msg: str)
        apply_success()
        apply_error(error_msg: str)
    """

    update_available = pyqtSignal(str, str, str, bool)  # version, url, body, prerelease
    no_update = pyqtSignal()
    check_error = pyqtSignal(str)

    download_progress = pyqtSignal(int, int)  # current, total
    download_done = pyqtSignal(str)  # archive_path
    download_error = pyqtSignal(str)

    apply_success = pyqtSignal()
    apply_error = pyqtSignal(str)

    def __init__(self, channel: str = UPDATE_CHANNEL_DEFAULT, download: bool = False):
        """
        channel — "stable" или "dev"
        download — если True, после проверки сразу скачивает обновление
        """
        super().__init__()
        self.channel = channel
        self._download_mode = download
        self._update_info = None

    def run(self):
        """Проверяет обновление в фоне."""
        try:
            info = check_for_updates(
                current_version=__version__,
                channel=self.channel,
            )

            if info is None:
                self.no_update.emit()
                return

            self._update_info = info

            self.update_available.emit(
                info["version"],
                info["download_url"],
                info.get("body", ""),
                info.get("prerelease", False),
            )

            if self._download_mode:
                self._do_download(info["download_url"])

        except Exception as e:
            self.check_error.emit(str(e))

    def _do_download(self, url: str):
        """Скачивает файл обновления."""
        try:
            archive_path = download_update(
                url=url,
                dest_dir=UPDATE_TEMP_DIR,
                progress_callback=self.download_progress.emit,
            )

            if archive_path and os.path.isfile(archive_path):
                self.download_done.emit(archive_path)
            else:
                self.download_error.emit("Ошибка скачивания файла обновления")

        except Exception as e:
            self.download_error.emit(str(e))

    def start_download(self):
        """Запускает скачивание после того, как пользователь подтвердил."""
        if self._update_info and not self.isRunning():
            self._download_mode = True
            self.start()

    def apply(self, archive_path: str):
        """Применяет обновление (завершает процесс)."""
        try:
            success = apply_update(archive_path)
            if success:
                self.apply_success.emit()
            else:
                self.apply_error.emit("Ошибка применения обновления")
        except Exception as e:
            self.apply_error.emit(str(e))