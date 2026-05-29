from __future__ import annotations

from typing import Any

import requests

from src.core.normalize import clean_text, item_id
from src.models import NewsItem

TITLE_KEYS = ("title", "name", "headline")
URL_KEYS = ("url", "link", "source_url", "original_url")
SUMMARY_KEYS = ("summary", "description", "desc", "abstract")
CONTENT_KEYS = ("content", "text", "body")
DATE_KEYS = ("published_at", "pubDate", "created_at", "updated_at", "date")
IMAGE_KEYS = ("image_url", "image", "cover", "cover_url", "thumbnail", "picurl")


def _pick(obj: dict, keys: tuple[str, ...]) -> Any:
    mapping = {str(k).lower(): v for k, v in obj.items()}
    for key in keys:
        if key.lower() in mapping and mapping[key.lower()] not in (None, ""):
            return mapping[key.lower()]
    return None


def _as_list(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "results", "list", "records"):
        if isinstance(payload.get(key), list):
            return [x for x in payload[key] if isinstance(x, dict)]
    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return _as_list(data)
    return []


def fetch_rest_source(source: dict, max_items: int) -> list[NewsItem]:
    method = str(source.get("method", "GET")).upper()
    response = requests.request(
        method,
        source["url"],
        headers=source.get("headers") or {},
        params=source.get("params") or {},
        timeout=30,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"REST 返回非 JSON: {exc}") from exc
    rows = _as_list(payload)
    if not rows:
        raise RuntimeError("REST JSON 中未找到可解析的资讯列表")
    items: list[NewsItem] = []
    mapping = source.get("mapping") or {}
    for row in rows[:max_items]:
        title = clean_text(row.get(mapping.get("title", "")) if mapping.get("title") else _pick(row, TITLE_KEYS))
        url = str(row.get(mapping.get("url", "")) if mapping.get("url") else _pick(row, URL_KEYS) or "").strip()
        if not title or not url:
            continue
        summary = row.get(mapping.get("summary", "")) if mapping.get("summary") else _pick(row, SUMMARY_KEYS)
        content = row.get(mapping.get("content", "")) if mapping.get("content") else _pick(row, CONTENT_KEYS)
        published_at = row.get(mapping.get("published_at", "")) if mapping.get("published_at") else _pick(row, DATE_KEYS)
        image_url = row.get(mapping.get("image_url", "")) if mapping.get("image_url") else _pick(row, IMAGE_KEYS)
        items.append(NewsItem(
            id=item_id(source["name"], title, url),
            source=source["name"],
            title=title,
            url=url,
            summary=clean_text(summary, 1000),
            content=clean_text(content or summary, 2000),
            published_at=str(published_at) if published_at else None,
            image_url=str(image_url) if image_url else None,
            raw=row,
        ))
    return items
