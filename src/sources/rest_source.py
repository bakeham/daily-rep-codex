from __future__ import annotations

from typing import Any

import requests

from src.core.utils import clean_html, first_image_from_html, item_dedupe_key
from src.models import NewsItem
from src.sources.base import BaseSource, SourceError

TITLE_KEYS = ("title", "name", "headline")
URL_KEYS = ("url", "link", "source_url", "original_url")
SUMMARY_KEYS = ("summary", "description", "desc", "abstract")
CONTENT_KEYS = ("content", "text", "body")
DATE_KEYS = ("published_at", "pubDate", "created_at", "updated_at", "date")
IMAGE_KEYS = ("image_url", "image", "cover", "cover_url", "thumbnail", "picurl")


def _get_first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    mapping = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        if key.lower() in mapping and mapping[key.lower()] not in (None, ""):
            return mapping[key.lower()]
    return None


def _extract_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "data", "results", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            nested = _extract_list(value)
            if nested:
                return nested
    # Last resort: find the longest list of dicts one level down.
    candidates: list[list[dict[str, Any]]] = []
    for value in payload.values():
        if isinstance(value, list):
            rows = [x for x in value if isinstance(x, dict)]
            if rows:
                candidates.append(rows)
    return max(candidates, key=len) if candidates else []


class RestSource(BaseSource):
    def fetch(self) -> list[NewsItem]:
        method = str(self.config.get("method", "GET")).upper()
        try:
            response = requests.request(
                method,
                self.url,
                headers=self.config.get("headers") or {},
                params=self.config.get("params") or {},
                json=self.config.get("json") if method not in {"GET", "HEAD"} else None,
                timeout=float(self.config.get("timeout_seconds", 20)),
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise SourceError(f"REST fetch failed for {self.name}: {exc}") from exc

        rows = _extract_list(payload)
        if not rows:
            raise SourceError(f"REST parse failed for {self.name}: no JSON list found")

        items: list[NewsItem] = []
        mapping = self.config.get("mapping") or {}
        for row in rows[: self.max_items]:
            try:
                title = clean_html(row.get(mapping.get("title", "")) if mapping.get("title") else _get_first(row, TITLE_KEYS))
                url = str(row.get(mapping.get("url", "")) if mapping.get("url") else _get_first(row, URL_KEYS) or "").strip()
                if not title or not url:
                    continue
                raw_summary = row.get(mapping.get("summary", "")) if mapping.get("summary") else _get_first(row, SUMMARY_KEYS)
                raw_content = row.get(mapping.get("content", "")) if mapping.get("content") else _get_first(row, CONTENT_KEYS)
                image = row.get(mapping.get("image_url", "")) if mapping.get("image_url") else _get_first(row, IMAGE_KEYS)
                if isinstance(image, dict):
                    image = image.get("url") or image.get("src")
                image_url = str(image).strip() if image else first_image_from_html(str(raw_content or raw_summary or ""))
                published_at = row.get(mapping.get("published_at", "")) if mapping.get("published_at") else _get_first(row, DATE_KEYS)
                items.append(
                    NewsItem(
                        id=item_dedupe_key(title, url, self.name),
                        source=self.name,
                        title=title,
                        url=url,
                        summary=clean_html(raw_summary, 500),
                        content=clean_html(raw_content or raw_summary, 1200),
                        published_at=str(published_at) if published_at else None,
                        image_url=image_url,
                        raw=row,
                    )
                )
            except Exception as exc:
                print(f"WARNING: skip REST item from {self.name}: {exc}")
        return items
