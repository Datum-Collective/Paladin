"""Entry point for the desktop app: run the API on loopback only. Used by PyInstaller and by `npm start` in dev."""
import os

import uvicorn

from app.main import app

if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")),
                log_level="warning", access_log=False)
