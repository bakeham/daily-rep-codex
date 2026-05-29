from __future__ import annotations

from typing import Any

import feedparser

from src.core.utils import clean_html, first_image_from_html, item_dedupe_key
from src.models import NewsItem
from src.sources.base import BaseSource, SourceError


def _first_media_url(entry: Any) -> str | None:
    for attr in ("media_thumbnail", "media_content"):
        values = getattr(entry, attr, None) or entry.get(attr, []) if hasattr(entry, "get") else []
        if values:
            url = values[0].get("url") if isinstance(values[0], dict) else None
            if url:
                return str(url)
    for enc in getattr(entry, "enclosures", []) or []:
        href = enc.get("href") if isinstance(enc, dict) else None
        enc_type = enc.get("type", "") if isinstance(enc, dict) else ""
        if href and (str(enc_type).startswith("image/") or href.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))):
            return str(href)
    return None


class RssSource(BaseSource):
    def fetch(self) -> list[NewsItem]:
        parsed = feedparser.parse(self.url)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise SourceError(f"RSS parse failed for {self.name}: {getattr(parsed, 'bozo_exception', 'unknown error')}")
        items: list[NewsItem] = []
        for entry in parsed.entries[: self.max_items]:
            try:
                title = clean_html(getattr(entry, "title", ""))
                url = str(getattr(entry, "link", "") or "").strip()
                if not title or not url:
                    continue
                raw_summary = getattr(entry, "summary", None) or getattr(entry, "description", "")
                raw_content = ""
                if getattr(entry, "content", None):
                    raw_content = entry.content[0].get("value", "")
                summary = clean_html(raw_summary, 500)
                content = clean_html(raw_content or raw_summary, 1200)
                image_url = _first_media_url(entry) or first_image_from_html(raw_content or raw_summary)
                published_at = getattr(entry, "published", None) or getattr(entry, "updated", None)
                items.append(
                    NewsItem(
                        id=item_dedupe_key(title, url, self.name),
                        source=self.name,
                        title=title,
                        url=url,
                        summary=summary,
                        content=content,
                        published_at=published_at,
                        image_url=image_url,
                        raw=dict(entry),
                    )
                )
            except Exception as exc:
                print(f"WARNING: skip RSS item from {self.name}: {exc}")
        return items
