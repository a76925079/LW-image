from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import GenerationKind, HistoryRecord
from .paths import database_path


class HistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def add(
        self,
        *,
        kind: GenerationKind,
        prompt: str,
        model: str,
        size: str,
        image_paths: list[Path],
        response_json: dict[str, Any],
    ) -> int:
        with self._connect() as con:
            cursor = con.execute(
                """
                INSERT INTO history(kind, prompt, model, size, image_paths, response_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    prompt,
                    model,
                    size,
                    json.dumps([str(path) for path in image_paths], ensure_ascii=False),
                    json.dumps(response_json, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def list_recent(self, limit: int = 100) -> list[HistoryRecord]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT id, kind, prompt, model, size, image_paths, response_json, created_at
                FROM history
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get(self, record_id: int) -> HistoryRecord | None:
        with self._connect() as con:
            row = con.execute(
                """
                SELECT id, kind, prompt, model, size, image_paths, response_json, created_at
                FROM history
                WHERE id = ?
                """,
                (record_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def delete(self, record_id: int) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM history WHERE id = ?", (record_id,))

    def clear(self) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM history")

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.execute("PRAGMA temp_store = MEMORY")
        con.execute("PRAGMA journal_mode = MEMORY")
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    model TEXT NOT NULL,
                    size TEXT NOT NULL,
                    image_paths TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> HistoryRecord:
        return HistoryRecord(
            id=int(row["id"]),
            kind=row["kind"],
            prompt=row["prompt"],
            model=row["model"],
            size=row["size"],
            image_paths=[Path(value) for value in json.loads(row["image_paths"])],
            response_json=json.loads(row["response_json"]),
            created_at=row["created_at"],
        )
