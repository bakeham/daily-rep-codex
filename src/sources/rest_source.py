from __future__ import annotations

from typing import Any

import requests

from src.core.utils import clean_text, extract_first_image, sha256_text
from src.models import NewsItem
from src.sources.base import Source


FIELD_ALIASES = {
    "title": ["title", "name", "headline"],
    "url": ["url", "link", "source_url", "original_url"],
    "summary": ["summary", "description", "desc", "abstract"],
    "content": ["content", "text", "body"],
    "published_at": ["published_at", "pubDate", "created_at", "updated_at", "date"],
    "image_url": ["image_url", "image", "cover", "cover_url", "thumbnail", "picurl"],
}


class RestSource(Source):
    def fetch(self) -> list[NewsItem]:
        method = self.config.get("method", "GET").upper()
        resp = requests.request(
            method,
            self.config["url"],
            headers=self.config.get("headers") or {},
            params=self.config.get("params") or {},
            timeout=30,
        )
        resp.raise_for_status()
        try:
            payload = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"REST 返回不是 JSON: {exc}") from exc
        rows = self._find_list(payload)
        if rows is None:
            raise RuntimeError("REST JSON 未找到可解析的列表结构，支持 list/items/data/data.items")
        items: list[NewsItem] = []
        mapping = self.config.get("mapping") or {}
        for row in rows[: self.max_items]:
            if not isinstance(row, dict):
                continue
            title = clean_text(self._pick(row, "title", mapping))
            url = str(self._pick(row, "url", mapping) or "").strip()
            if not title or not url:
                continue
            summary_raw = self._pick(row, "summary", mapping)
            content_raw = self._pick(row, "content", mapping) or summary_raw
            image = self._pick(row, "image_url", mapping) or extract_first_image(str(content_raw or summary_raw or ""))
            items.append(
                NewsItem(
                    id=sha256_text(f"{self.name}:{url or title}"),
                    source=self.name,
                    title=title,
                    url=url,
                    summary=clean_text(summary_raw, 500),
                    content=clean_text(content_raw, 1200),
                    published_at=self._pick(row, "published_at", mapping),
                    image_url=str(image) if image else None,
                    raw=row,
                )
            )
        return items

    def _find_list(self, payload: Any) -> list[Any] | None:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return None
        for key in ("items", "results", "list"):
            if isinstance(payload.get(key), list):
                return payload[key]
        data = payload.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "results", "list"):
                if isinstance(data.get(key), list):
                    return data[key]
        return None

    def _pick(self, row: dict[str, Any], target: str, mapping: dict[str, str]) -> Any:
        if target in mapping:
            return self._get_path(row, mapping[target])
        for key in FIELD_ALIASES[target]:
            value = self._get_path(row, key)
            if value not in (None, ""):
                return value
        return None

    def _get_path(self, row: dict[str, Any], path: str) -> Any:
        cur: Any = row
        for part in path.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur
