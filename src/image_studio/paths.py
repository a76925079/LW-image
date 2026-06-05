from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "chatgpt2api-image-studio"


def app_data_dir() -> Path:
    root = os.getenv("APPDATA")
    if root:
        base = Path(root)
    else:
        base = Path.home() / ".config"
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return app_data_dir() / "config.json"


def database_path() -> Path:
    return app_data_dir() / "history.sqlite3"
