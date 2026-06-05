from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .api_client import normalize_base_url
from .models import AppConfig
from .paths import config_path

BUILTIN_BASE_URL = normalize_base_url("https://chat.aiapi1.cc.cd")
BUILTIN_API_KEY = os.getenv("LW_IMAGE_API_KEY", "")


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_path()

    def load(self) -> AppConfig:
        payload: dict[str, Any] = {}
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}

        return AppConfig(
            base_url=BUILTIN_BASE_URL,
            default_model=str(payload.get("default_model") or "gpt-image-2"),
            default_size="1024x1024",
            output_dir=Path(payload.get("output_dir") or AppConfig().output_dir),
            api_key=BUILTIN_API_KEY,
            theme="light" if payload.get("theme") == "light" else "dark",
        )

    def save(self, config: AppConfig) -> AppConfig:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "default_model": config.default_model.strip(),
            "output_dir": str(config.output_dir),
            "theme": "light" if config.theme == "light" else "dark",
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return AppConfig(
            base_url=BUILTIN_BASE_URL,
            default_model=payload["default_model"],
            default_size="1024x1024",
            output_dir=Path(payload["output_dir"]),
            api_key=BUILTIN_API_KEY,
            theme=payload["theme"],
        )
