from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


APP_TITLE = "LW生图工具"
NOTICE_TEXT = "本工具为公益开源项目，官方社区：https://dc.hhhl.cc。加入Q群：116231758 免费提供image-2模型接口。转发二开请注明出处。"
BUILTIN_BASE_URL = "https://chat.aiapi1.cc.cd"
BUILTIN_API_KEY = os.getenv("LW_IMAGE_API_KEY", "")

ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT_DIR / "frontend"
DATA_DIR = ROOT_DIR / "data"
IMAGE_DIR = DATA_DIR / "images"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "history.sqlite3"
SETTINGS_PATH = DATA_DIR / "settings.json"
TEMPLATES_PATH = DATA_DIR / "prompt_templates.json"

for folder in (IMAGE_DIR, UPLOAD_DIR):
    folder.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=APP_TITLE)


class ApiError(RuntimeError):
    pass


class HistoryRecord(BaseModel):
    id: int
    kind: str
    prompt: str
    model: str
    size: str
    quality: str
    image_paths: list[str]
    reference_path: str | None
    created_at: str


class ConversationRecord(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    records: list[HistoryRecord]


class AppSettings(BaseModel):
    base_url: str
    api_key: str
    model: str = "gpt-image-2"


class PromptTemplate(BaseModel):
    id: str = ""
    title: str
    prompt: str


class ModelListRequest(BaseModel):
    base_url: str | None = None
    api_key: str | None = None


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.execute("PRAGMA temp_store = MEMORY")
        con.execute("PRAGMA journal_mode = MEMORY")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT,
                kind TEXT NOT NULL,
                prompt TEXT NOT NULL,
                model TEXT NOT NULL,
                size TEXT NOT NULL,
                quality TEXT NOT NULL,
                image_paths TEXT NOT NULL,
                reference_path TEXT,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = {row[1] for row in con.execute("PRAGMA table_info(history)").fetchall()}
        if "conversation_id" not in columns:
            con.execute("ALTER TABLE history ADD COLUMN conversation_id TEXT")


def normalize_base_url(value: str) -> str:
    clean = value.strip()
    if not clean.startswith(("http://", "https://")):
        clean = f"http://{clean}"
    clean = clean.rstrip("/")
    return clean[:-3] if clean.endswith("/v1") else clean


def load_settings() -> AppSettings:
    payload: dict[str, Any] = {}
    if SETTINGS_PATH.exists():
        try:
            payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
    return AppSettings(
        base_url=normalize_base_url(str(payload.get("base_url") or BUILTIN_BASE_URL)),
        api_key=str(payload.get("api_key") or BUILTIN_API_KEY),
        model=str(payload.get("model") or "gpt-image-2"),
    )


def save_settings(settings: AppSettings) -> AppSettings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    clean = AppSettings(
        base_url=normalize_base_url(settings.base_url),
        api_key=settings.api_key.strip(),
        model=settings.model.strip() or "gpt-image-2",
    )
    SETTINGS_PATH.write_text(json.dumps(clean.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return clean


def load_templates() -> list[PromptTemplate]:
    if not TEMPLATES_PATH.exists():
        return [
            PromptTemplate(
                id="tpl_xhs_product",
                title="小红书商品图",
                prompt="小红书风格商品配图，明亮自然光，干净背景，突出产品质感，真实摄影，高级感，适合种草封面",
            ),
            PromptTemplate(
                id="tpl_ecommerce_main",
                title="电商主图",
                prompt="电商平台主图，白底，产品居中，细节清晰，商业摄影，高清质感，干净构图，适合点击转化",
            ),
        ]
    try:
        payload = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [PromptTemplate(**item) for item in payload if isinstance(item, dict)]


def save_templates(templates: list[PromptTemplate]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_PATH.write_text(json.dumps([item.model_dump() for item in templates], ensure_ascii=False, indent=2), encoding="utf-8")


class ImageApiClient:
    def __init__(self, settings: AppSettings) -> None:
        self.base_url = normalize_base_url(settings.base_url)
        self.api_key = settings.api_key.strip()

    def list_models(self) -> list[str]:
        payload = self._request_json("GET", "/v1/models")
        data = payload.get("data", [])
        models: list[str] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("id"):
                    models.append(str(item["id"]))
                elif isinstance(item, str):
                    models.append(item)
        return models

    def generate(
        self,
        *,
        prompt: str,
        model: str,
        size: str,
        count: int,
        quality: str,
        output_dir: Path,
    ) -> tuple[list[Path], dict[str, Any]]:
        payload: dict[str, Any] = {"prompt": prompt, "model": model, "size": size, "n": count}
        if quality != "auto":
            payload["quality"] = quality
        response = self._request_json("POST", "/v1/images/generations", json=payload)
        return self._save_response_images(response, output_dir), response

    def edit(
        self,
        *,
        reference_path: Path,
        prompt: str,
        model: str,
        size: str,
        quality: str,
        output_dir: Path,
    ) -> tuple[list[Path], dict[str, Any]]:
        fields = {"prompt": prompt, "model": model, "size": size}
        if quality != "auto":
            fields["quality"] = quality
        mime_type = mimetypes.guess_type(str(reference_path))[0] or "application/octet-stream"
        with reference_path.open("rb") as image_file:
            files = {"image": (reference_path.name, image_file, mime_type)}
            response = self._request_json("POST", "/v1/images/edits", data=fields, files=files)
        return self._save_response_images(response, output_dir), response

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            with httpx.Client(timeout=120, follow_redirects=True) as client:
                response = client.request(method, url, headers=headers, **kwargs)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type.lower():
                    raise ApiError(f"接口返回的不是 JSON，请稍后重试。请求地址：{url}")
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise ApiError(format_http_error(exc, url)) from exc
        except httpx.RequestError as exc:
            raise ApiError(f"无法连接接口：{exc}") from exc
        except ValueError as exc:
            raise ApiError(f"接口返回 JSON 无法解析。请求地址：{url}") from exc
        if not isinstance(payload, dict):
            raise ApiError("接口返回格式不正确。")
        return payload

    def _save_response_images(self, response: dict[str, Any], output_dir: Path) -> list[Path]:
        data = response.get("data")
        if not isinstance(data, list) or not data:
            raise ApiError("接口响应中没有图片数据。")
        output_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for index, item in enumerate(data, 1):
            if not isinstance(item, dict):
                continue
            if item.get("b64_json"):
                paths.append(save_base64(str(item["b64_json"]), output_dir, index))
            elif item.get("url"):
                paths.append(save_url(str(item["url"]), output_dir, index))
        if not paths:
            raise ApiError("接口响应中没有可识别的图片。")
        return paths


def format_http_error(exc: httpx.HTTPStatusError, url: str) -> str:
    response = exc.response
    status = response.status_code
    text = response.text[:1200]
    content_type = response.headers.get("content-type", "")
    if status == 502:
        return f"接口服务暂时不可用，服务器网关返回 502。请稍后重试。\n请求地址：{url}"
    if status in {500, 503, 504}:
        return f"接口服务器异常 {status}，请稍后重试。\n请求地址：{url}"
    if "html" in content_type.lower() or "<html" in text.lower() or "<!doctype" in text.lower():
        title = extract_html_title(text)
        suffix = f" 页面标题：{title}" if title else ""
        return f"接口返回了网页错误页，不是 API JSON 响应。状态码：{status}。{suffix}\n请求地址：{url}"
    return f"接口返回错误 {status}: {text.replace(chr(10), ' ')[:500]}\n请求地址：{url}"


def extract_html_title(text: str) -> str:
    match = re.search(r"<title>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def save_base64(value: str, output_dir: Path, index: int) -> Path:
    if "," in value and value.split(",", 1)[0].startswith("data:"):
        value = value.split(",", 1)[1]
    raw = base64.b64decode(value)
    path = output_dir / image_filename(index, ".png")
    path.write_bytes(raw)
    return path


def save_url(value: str, output_dir: Path, index: int) -> Path:
    parsed = urlparse(value)
    suffix = Path(parsed.path).suffix or ".png"
    path = output_dir / image_filename(index, suffix)
    if parsed.scheme in {"http", "https"}:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            response = client.get(value)
            response.raise_for_status()
            path.write_bytes(response.content)
    else:
        source = Path(value)
        if not source.exists():
            raise ApiError(f"无法读取图片地址：{value}")
        path.write_bytes(source.read_bytes())
    return path


def image_filename(index: int, suffix: str) -> str:
    clean_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return f"image_{time.strftime('%Y%m%d_%H%M%S')}_{index}_{uuid4().hex[:6]}{clean_suffix}"


def to_public_path(path: Path) -> str:
    return f"/files/{path.relative_to(DATA_DIR).as_posix()}"


def add_history(
    *,
    conversation_id: str,
    kind: str,
    prompt: str,
    model: str,
    size: str,
    quality: str,
    image_paths: list[Path],
    reference_path: Path | None,
    response_json: dict[str, Any],
) -> int:
    with sqlite3.connect(DB_PATH) as con:
        cursor = con.execute(
            """
            INSERT INTO history(conversation_id, kind, prompt, model, size, quality, image_paths, reference_path, response_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                kind,
                prompt,
                model,
                size,
                quality,
                json.dumps([str(path) for path in image_paths], ensure_ascii=False),
                str(reference_path) if reference_path else None,
                json.dumps(response_json, ensure_ascii=False),
            ),
        )
        return int(cursor.lastrowid)


def ensure_conversation(conversation_id: str | None, prompt: str) -> str:
    current_id = conversation_id.strip() if conversation_id else ""
    if not current_id:
        current_id = f"conv_{uuid4().hex}"
    title = prompt[:36] or "新对话"
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute("SELECT id FROM conversations WHERE id = ?", (current_id,)).fetchone()
        if row:
            con.execute(
                "UPDATE conversations SET title = CASE WHEN title = '新对话' THEN ? ELSE title END, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (title, current_id),
            )
        else:
            con.execute("INSERT INTO conversations(id, title) VALUES (?, ?)", (current_id, title))
    return current_id


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status() -> dict[str, Any]:
    settings = load_settings()
    return {
        "name": APP_TITLE,
        "models": ["gpt-image-2", "gpt-image-1"],
        "settings": settings.model_dump(),
        "notice": NOTICE_TEXT,
    }


@app.get("/api/settings")
def get_settings() -> AppSettings:
    return load_settings()


@app.post("/api/settings")
def update_settings(settings: AppSettings) -> AppSettings:
    if not settings.base_url.strip():
        raise HTTPException(status_code=400, detail="请填写 API 地址。")
    if not settings.api_key.strip():
        raise HTTPException(status_code=400, detail="请填写 API Key。")
    return save_settings(settings)


@app.post("/api/models")
def list_models(request: ModelListRequest) -> dict[str, list[str]]:
    settings = load_settings()
    if request.base_url:
        settings.base_url = request.base_url
    if request.api_key:
        settings.api_key = request.api_key
    try:
        models = ImageApiClient(settings).list_models()
    except ApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"models": models}


@app.get("/api/templates", response_model=list[PromptTemplate])
def get_templates() -> list[PromptTemplate]:
    return load_templates()


@app.post("/api/templates", response_model=PromptTemplate)
def create_template(template: PromptTemplate) -> PromptTemplate:
    if not template.title.strip():
        raise HTTPException(status_code=400, detail="请填写模板名称。")
    if not template.prompt.strip():
        raise HTTPException(status_code=400, detail="请填写提示词内容。")
    templates = load_templates()
    created = PromptTemplate(id=f"tpl_{uuid4().hex}", title=template.title.strip(), prompt=template.prompt.strip())
    templates.insert(0, created)
    save_templates(templates)
    return created


@app.put("/api/templates/{template_id}", response_model=PromptTemplate)
def update_template(template_id: str, template: PromptTemplate) -> PromptTemplate:
    templates = load_templates()
    for index, item in enumerate(templates):
        if item.id == template_id:
            updated = PromptTemplate(id=template_id, title=template.title.strip(), prompt=template.prompt.strip())
            templates[index] = updated
            save_templates(templates)
            return updated
    raise HTTPException(status_code=404, detail="模板不存在。")


@app.delete("/api/templates/{template_id}")
def delete_template(template_id: str) -> dict[str, bool]:
    templates = [item for item in load_templates() if item.id != template_id]
    save_templates(templates)
    return {"ok": True}


@app.post("/api/generate")
async def generate(
    prompt: str = Form(...),
    conversation_id: str = Form(""),
    model: str = Form("gpt-image-2"),
    width: int = Form(1024),
    height: int = Form(1024),
    count: int = Form(1),
    quality: str = Form("auto"),
    reference: UploadFile | None = File(None),
) -> dict[str, Any]:
    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="请先输入提示词。")
    size = f"{width}x{height}"
    count = max(1, min(4, count))
    reference_path: Path | None = None
    try:
        settings = load_settings()
        model = model.strip() or settings.model
        current_conversation_id = ensure_conversation(conversation_id, prompt)
        if reference and reference.filename:
            suffix = Path(reference.filename).suffix or ".png"
            reference_path = UPLOAD_DIR / f"ref_{time.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}{suffix}"
            with reference_path.open("wb") as target:
                shutil.copyfileobj(reference.file, target)

        client = ImageApiClient(settings)
        if reference_path:
            image_paths, response = client.edit(reference_path=reference_path, prompt=prompt, model=model, size=size, quality=quality, output_dir=IMAGE_DIR)
            kind = "image_to_image"
        else:
            image_paths, response = client.generate(prompt=prompt, model=model, size=size, count=count, quality=quality, output_dir=IMAGE_DIR)
            kind = "text_to_image"
        record_id = add_history(conversation_id=current_conversation_id, kind=kind, prompt=prompt, model=model, size=size, quality=quality, image_paths=image_paths, reference_path=reference_path, response_json=response)
        return {"id": record_id, "conversation_id": current_conversation_id, "kind": kind, "images": [to_public_path(path) for path in image_paths]}
    except ApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/history", response_model=list[HistoryRecord])
def history() -> list[HistoryRecord]:
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT id, kind, prompt, model, size, quality, image_paths, reference_path, created_at
            FROM history
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT 100
            """
        ).fetchall()
    records: list[HistoryRecord] = []
    for row in rows:
        image_paths = [to_public_path(Path(value)) for value in json.loads(row["image_paths"])]
        reference_path = to_public_path(Path(row["reference_path"])) if row["reference_path"] else None
        records.append(
            HistoryRecord(
                id=row["id"],
                kind=row["kind"],
                prompt=row["prompt"],
                model=row["model"],
                size=row["size"],
                quality=row["quality"],
                image_paths=image_paths,
                reference_path=reference_path,
                created_at=row["created_at"],
            )
        )
    return records


@app.get("/api/conversations", response_model=list[ConversationRecord])
def conversations() -> list[ConversationRecord]:
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        conv_rows = con.execute(
            """
            SELECT id, title, created_at, updated_at
            FROM conversations
            ORDER BY datetime(updated_at) DESC, datetime(created_at) DESC
            LIMIT 100
            """
        ).fetchall()
        if not conv_rows:
            legacy_rows = con.execute(
                """
                SELECT id, kind, prompt, model, size, quality, image_paths, reference_path, created_at
                FROM history
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 100
                """
            ).fetchall()
            return [legacy_conversation(row) for row in legacy_rows]

        result: list[ConversationRecord] = []
        for conv in conv_rows:
            rows = con.execute(
                """
                SELECT id, kind, prompt, model, size, quality, image_paths, reference_path, created_at
                FROM history
                WHERE conversation_id = ?
                ORDER BY datetime(created_at) ASC, id ASC
                """,
                (conv["id"],),
            ).fetchall()
            result.append(
                ConversationRecord(
                    id=conv["id"],
                    title=conv["title"],
                    created_at=conv["created_at"],
                    updated_at=conv["updated_at"],
                    records=[history_row_to_record(row) for row in rows],
                )
            )
        return result


def history_row_to_record(row: sqlite3.Row) -> HistoryRecord:
    image_paths = [to_public_path(Path(value)) for value in json.loads(row["image_paths"])]
    reference_path = to_public_path(Path(row["reference_path"])) if row["reference_path"] else None
    return HistoryRecord(
        id=row["id"],
        kind=row["kind"],
        prompt=row["prompt"],
        model=row["model"],
        size=row["size"],
        quality=row["quality"],
        image_paths=image_paths,
        reference_path=reference_path,
        created_at=row["created_at"],
    )


def legacy_conversation(row: sqlite3.Row) -> ConversationRecord:
    record = history_row_to_record(row)
    return ConversationRecord(
        id=f"legacy-{record.id}",
        title=record.prompt[:36] or "历史记录",
        created_at=record.created_at,
        updated_at=record.created_at,
        records=[record],
    )


def public_path_to_file(path: str) -> Path:
    clean = path.strip()
    if clean.startswith("/files/"):
        clean = clean[len("/files/") :]
    target = (DATA_DIR / clean).resolve()
    if not str(target).startswith(str(DATA_DIR.resolve())):
        raise HTTPException(status_code=400, detail="文件路径不合法。")
    return target


def unlink_quietly(path: Path) -> None:
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except OSError:
        pass


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict[str, bool]:
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT image_paths, reference_path FROM history WHERE conversation_id = ?", (conversation_id,)).fetchall()
        for row in rows:
            for value in json.loads(row["image_paths"]):
                unlink_quietly(Path(value))
            if row["reference_path"]:
                unlink_quietly(Path(row["reference_path"]))
        con.execute("DELETE FROM history WHERE conversation_id = ?", (conversation_id,))
        con.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    return {"ok": True}


@app.delete("/api/images")
def delete_image(path: str) -> dict[str, bool]:
    target = public_path_to_file(path)
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT id, image_paths FROM history").fetchall()
        for row in rows:
            paths = [Path(value) for value in json.loads(row["image_paths"])]
            remaining = [item for item in paths if item.resolve() != target]
            if len(remaining) == len(paths):
                continue
            if remaining:
                con.execute(
                    "UPDATE history SET image_paths = ? WHERE id = ?",
                    (json.dumps([str(item) for item in remaining], ensure_ascii=False), row["id"]),
                )
            else:
                con.execute("DELETE FROM history WHERE id = ?", (row["id"],))
    unlink_quietly(target)
    return {"ok": True}


@app.delete("/api/history/{record_id}")
def delete_history(record_id: int) -> dict[str, bool]:
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DELETE FROM history WHERE id = ?", (record_id,))
    return {"ok": True}


@app.delete("/api/history")
def clear_history() -> dict[str, bool]:
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DELETE FROM history")
        con.execute("DELETE FROM conversations")
    return {"ok": True}


@app.get("/files/{path:path}")
def files(path: str) -> FileResponse:
    target = (DATA_DIR / path).resolve()
    if not str(target).startswith(str(DATA_DIR.resolve())) or not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在。")
    return FileResponse(target)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
