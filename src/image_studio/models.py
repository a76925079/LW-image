from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


GenerationKind = Literal["text_to_image", "image_to_image"]
ThemeMode = Literal["dark", "light"]


@dataclass(slots=True)
class AppConfig:
    base_url: str = "https://chat.aiapi1.cc.cd"
    default_model: str = "gpt-image-2"
    default_size: str = "1024x1024"
    output_dir: Path = Path.home() / "Pictures" / "ImageStudio"
    api_key: str = ""
    theme: ThemeMode = "dark"


@dataclass(slots=True)
class ImageResult:
    path: Path
    source: str


@dataclass(slots=True)
class HistoryRecord:
    id: int
    kind: GenerationKind
    prompt: str
    model: str
    size: str
    image_paths: list[Path]
    response_json: dict[str, Any]
    created_at: str
