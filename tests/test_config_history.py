from __future__ import annotations

from pathlib import Path

from image_studio.api_client import normalize_base_url
from image_studio.config import ConfigStore
from image_studio.history import HistoryStore
from image_studio.models import AppConfig


def test_normalize_base_url_accepts_common_inputs() -> None:
    assert normalize_base_url("localhost:3000") == "http://localhost:3000"
    assert normalize_base_url("http://localhost:3000/") == "http://localhost:3000"
    assert normalize_base_url("http://localhost:3000/v1") == "http://localhost:3000"
    assert normalize_base_url("https://example.com/api/v1/") == "https://example.com/api"


def test_config_roundtrip_with_local_fallback(monkeypatch, tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.json")
    saved = store.save(
        AppConfig(
            base_url="http://ignored.example/",
            default_model="gpt-image-1",
            default_size="2048x2048",
            output_dir=tmp_path / "out",
            theme="light",
        ),
    )

    loaded = store.load()
    assert saved.base_url == "https://chat.aiapi1.cc.cd"
    assert loaded.base_url == "https://chat.aiapi1.cc.cd"
    assert loaded.api_key == ""
    assert loaded.default_model == "gpt-image-1"
    assert loaded.default_size == "1024x1024"
    assert loaded.output_dir == tmp_path / "out"
    assert loaded.theme == "light"


def test_history_roundtrip(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"png")

    record_id = store.add(
        kind="text_to_image",
        prompt="a calm lake",
        model="gpt-image-1",
        size="1024x1024",
        image_paths=[image_path],
        response_json={"data": [{"url": "file"}]},
    )

    record = store.get(record_id)
    assert record is not None
    assert record.prompt == "a calm lake"
    assert record.image_paths == [image_path]
    assert store.list_recent()[0].id == record_id
