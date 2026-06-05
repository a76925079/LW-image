from __future__ import annotations

import base64
import re
import mimetypes
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .models import ImageResult


class ApiError(RuntimeError):
    pass


def normalize_base_url(value: str) -> str:
    clean = value.strip()
    if not clean:
        return ""
    if not clean.startswith(("http://", "https://")):
        clean = f"http://{clean}"
    clean = clean.rstrip("/")
    if clean.endswith("/v1"):
        clean = clean[:-3]
    return clean.rstrip("/")


class ChatGPT2ApiClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0) -> None:
        self.base_url = normalize_base_url(base_url)
        self.api_key = api_key.strip()
        self.timeout = timeout

    def list_models(self) -> list[str]:
        payload = self._request_json("GET", "/v1/models")
        data = payload.get("data", [])
        names: list[str] = []
        for item in data:
            if isinstance(item, dict) and item.get("id"):
                names.append(str(item["id"]))
            elif isinstance(item, str):
                names.append(item)
        return names

    def generate_image(
        self,
        *,
        prompt: str,
        model: str,
        size: str,
        n: int,
        output_dir: Path,
        quality: str = "auto",
    ) -> tuple[list[ImageResult], dict[str, Any]]:
        payload: dict[str, Any] = {"prompt": prompt, "size": size, "n": n}
        if model:
            payload["model"] = model
        if quality and quality != "auto":
            payload["quality"] = quality
        response = self._request_json("POST", "/v1/images/generations", json=payload)
        return self._save_response_images(response, output_dir), response

    def edit_image(
        self,
        *,
        image_path: Path,
        prompt: str,
        model: str,
        size: str,
        output_dir: Path,
        quality: str = "auto",
    ) -> tuple[list[ImageResult], dict[str, Any]]:
        fields = {"prompt": prompt, "size": size}
        if model:
            fields["model"] = model
        if quality and quality != "auto":
            fields["quality"] = quality
        mime_type = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
        with image_path.open("rb") as image_file:
            files = {"image": (image_path.name, image_file, mime_type)}
            response = self._request_json("POST", "/v1/images/edits", data=fields, files=files)
        return self._save_response_images(response, output_dir), response

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.base_url:
            raise ApiError("请先填写 API 地址。")
        if not self.api_key:
            raise ApiError("请先填写 API Key。")

        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                response = client.request(method, url, headers=headers, **kwargs)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type.lower():
                    preview = response.text[:300].replace("\n", " ").strip()
                    raise ApiError(
                        "接口返回的不是 JSON。请检查 API 地址是否填成服务根地址，"
                        "例如 http://localhost:3000；不要填前端页面地址或重复的 /v1。"
                        f" 当前请求: {url}，返回类型: {content_type or '未知'}，内容预览: {preview}"
                    )
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise ApiError(self._format_http_error(exc, url)) from exc
        except httpx.RequestError as exc:
            raise ApiError(f"无法连接接口: {exc}") from exc
        except ValueError as exc:
            raise ApiError(f"接口返回的 JSON 无法解析。当前请求: {url}") from exc

        if not isinstance(payload, dict):
            raise ApiError("接口返回格式不正确。")
        return payload

    @staticmethod
    def _format_http_error(exc: httpx.HTTPStatusError, url: str) -> str:
        response = exc.response
        status_code = response.status_code
        content_type = response.headers.get("content-type", "")
        text = response.text[:1200] if response is not None else str(exc)

        if status_code == 502:
            return (
                "接口服务暂时不可用，服务器网关返回 502。"
                "这通常是接口域名的上游服务宕机、反向代理异常或服务维护导致的，"
                "不是本地程序错误。请稍后重试，或联系接口服务管理员。"
                f"\n请求地址：{url}"
            )
        if status_code in {500, 503, 504}:
            return f"接口服务器异常 {status_code}，请稍后重试。\n请求地址：{url}"

        if "html" in content_type.lower() or "<html" in text.lower() or "<!doctype" in text.lower():
            title = ChatGPT2ApiClient._extract_html_title(text)
            suffix = f" 页面标题：{title}" if title else ""
            return f"接口返回了网页错误页，不是 API JSON 响应。状态码：{status_code}。{suffix}\n请求地址：{url}"

        preview = text.replace("\n", " ").strip()[:500]
        return f"接口返回错误 {status_code}: {preview}\n请求地址：{url}"

    @staticmethod
    def _extract_html_title(text: str) -> str:
        match = re.search(r"<title>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        return re.sub(r"\s+", " ", match.group(1)).strip()

    def _save_response_images(self, response: dict[str, Any], output_dir: Path) -> list[ImageResult]:
        output_dir.mkdir(parents=True, exist_ok=True)
        data = response.get("data")
        if not isinstance(data, list) or not data:
            raise ApiError("接口响应中没有图片数据。")

        results: list[ImageResult] = []
        for index, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                continue
            if item.get("b64_json"):
                saved = self._save_base64(str(item["b64_json"]), output_dir, index)
                results.append(ImageResult(saved, "b64_json"))
            elif item.get("url"):
                saved = self._save_url(str(item["url"]), output_dir, index)
                results.append(ImageResult(saved, "url"))

        if not results:
            raise ApiError("接口响应中没有可识别的 url 或 b64_json 图片。")
        return results

    def _save_base64(self, value: str, output_dir: Path, index: int) -> Path:
        if "," in value and value.split(",", 1)[0].startswith("data:"):
            value = value.split(",", 1)[1]
        raw = base64.b64decode(value)
        path = output_dir / self._filename(index, ".png")
        path.write_bytes(raw)
        return path

    def _save_url(self, value: str, output_dir: Path, index: int) -> Path:
        parsed = urlparse(value)
        suffix = Path(parsed.path).suffix or ".png"
        path = output_dir / self._filename(index, suffix)
        if parsed.scheme in {"http", "https"}:
            try:
                with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                    response = client.get(value)
                    response.raise_for_status()
                    path.write_bytes(response.content)
            except httpx.HTTPError as exc:
                raise ApiError(f"下载图片失败: {exc}") from exc
        elif parsed.scheme == "file":
            path.write_bytes(Path(parsed.path).read_bytes())
        else:
            source = Path(value)
            if not source.exists():
                raise ApiError(f"无法读取图片地址: {value}")
            path.write_bytes(source.read_bytes())
        return path

    @staticmethod
    def _filename(index: int, suffix: str) -> str:
        clean_suffix = suffix if suffix.startswith(".") else f".{suffix}"
        return f"image_{time.strftime('%Y%m%d_%H%M%S')}_{index}{clean_suffix}"
