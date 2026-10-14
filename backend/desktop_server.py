"""Entry point for the desktop app: run the API on loopback only. Used by PyInstaller and by `npm start` in dev.

The engine belongs to the app that started it: if that app exits or is killed without a chance to stop us, we exit
too, so a crash never leaves an orphaned server holding a port and a database."""
import os
import sys
import threading
import time

import uvicorn

from app.main import app


def _parent_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x00100000, False, pid)           # SYNCHRONIZE
        if not h:
            return False
        try:
            return k.WaitForSingleObject(h, 0) == 0x102     # WAIT_TIMEOUT: still running
        finally:
            k.CloseHandle(h)
    return os.getppid() == pid


def _watch_parent() -> None:
    raw = os.environ.get("APC_PARENT_PID", "")
    if not raw.isdigit():
        return
    pid = int(raw)

    def loop() -> None:
        while True:
            time.sleep(2)
            if not _parent_alive(pid):
                os._exit(0)

    threading.Thread(target=loop, daemon=True).start()


if __name__ == "__main__":
    _watch_parent()
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")),
                log_level="warning", access_log=False)
