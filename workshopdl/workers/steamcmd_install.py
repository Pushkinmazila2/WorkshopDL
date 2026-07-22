"""
Воркер скачки SteamCMD.
"""

import os, re, subprocess, urllib.request, zipfile, tarfile
from PyQt5.QtCore import QThread, pyqtSignal

from workshopdl.config import APP_DIR, STEAMCMD_BIN, STEAMCMD_DL_URL, STEAMCMD_ARCHIVE_IS_ZIP, IS_WIN
from workshopdl.localization import t


class SteamCMDInstallWorker(QThread):
    status  = pyqtSignal(str)
    percent = pyqtSignal(int)
    log_line = pyqtSignal(str)
    done    = pyqtSignal(bool, str)

    def run(self):
        try:
            self._install_steamcmd()
        except Exception as e:
            try:
                self.done.emit(False, f"Unexpected error: {str(e)}")
            except:
                pass

    def _install_steamcmd(self):
        dest_dir = os.path.join(APP_DIR, "steamcmd")
        exe_path = os.path.join(dest_dir, STEAMCMD_BIN)
        archive_name = "steamcmd.zip" if STEAMCMD_ARCHIVE_IS_ZIP else "steamcmd.tar.gz"
        archive_path = os.path.join(dest_dir, archive_name)

        try:
            os.makedirs(dest_dir, exist_ok=True)
        except Exception as e:
            self.done.emit(False, f"Cannot create directory: {str(e)}")
            return

        self.status.emit(t("steamcmd_dl_downloading"))
        self.percent.emit(0)

        try:
            req = urllib.request.Request(
                STEAMCMD_DL_URL,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                total_size = int(response.headers.get('Content-Length', 0))
                downloaded = 0
                block_size = 65536
                with open(archive_path, 'wb') as out_file:
                    while True:
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        downloaded += len(buffer)
                        out_file.write(buffer)
                        if total_size > 0:
                            pct = min(int(downloaded * 30 / total_size), 30)
                            self.percent.emit(pct)
                        else:
                            self.percent.emit(15)
        except urllib.error.URLError as e:
            self.done.emit(False, f"Download failed (network error): {str(e)}")
            return
        except Exception as e:
            self.done.emit(False, f"Download failed: {str(e)}")
            return

        self.status.emit(t("steamcmd_dl_unpacking"))
        self.percent.emit(31)

        try:
            if STEAMCMD_ARCHIVE_IS_ZIP:
                with zipfile.ZipFile(archive_path, "r") as z:
                    z.extractall(dest_dir)
            else:
                with tarfile.open(archive_path, "r:gz") as tar:
                    tar.extractall(dest_dir)
            try:
                os.remove(archive_path)
            except:
                pass
        except Exception as e:
            self.done.emit(False, f"Extraction failed: {str(e)}")
            return

        if not IS_WIN and os.path.exists(exe_path):
            try:
                os.chmod(exe_path, 0o755)
            except:
                pass

        if not os.path.exists(exe_path):
            self.done.emit(False, t("steamcmd_dl_exe_missing"))
            return

        self.status.emit(t("steamcmd_dl_init"))
        self.percent.emit(35)
        self.log_line.emit("─── SteamCMD self-update ───")

        clean_env = os.environ.copy()
        clean_env.pop("LD_LIBRARY_PATH", None)
        clean_env.pop("LD_PRELOAD", None)

        try:
            flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
            proc = subprocess.Popen(
                [exe_path, "+quit"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=flags,
                env=clean_env
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self.log_line.emit(line)
                    m = re.search(r"\[\s*(\d+)%\]", line)
                    if m:
                        try:
                            pct = int(m.group(1))
                            self.percent.emit(35 + int(pct * 0.63))
                        except:
                            pass
            proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            self.done.emit(False, "SteamCMD initialization timeout")
            return
        except Exception as e:
            self.done.emit(False, f"SteamCMD init failed: {str(e)}")
            return

        self.percent.emit(100)
        self.status.emit(t("steamcmd_dl_done"))
        self.done.emit(True, exe_path)