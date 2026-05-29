from __future__ import annotations

from typing import Any

import feedparser

from src.core.utils import clean_text, extract_first_image, sha256_text
from src.models import NewsItem
from src.sources.base import Source


class RssSource(Source):
    def fetch(self) -> list[NewsItem]:
        feed = feedparser.parse(self.config["url"])
        if getattr(feed, "bozo", False) and getattr(feed, "bozo_exception", None):
            raise RuntimeError(f"RSS 解析警告: {feed.bozo_exception}")
        items: list[NewsItem] = []
        for entry in feed.entries[: self.max_items]:
            title = clean_text(getattr(entry, "title", ""))
            url = getattr(entry, "link", "") or ""
            if not title or not url:
                continue
            summary_html = getattr(entry, "summary", None) or getattr(entry, "description", "")
            content_html = ""
            if getattr(entry, "content", None):
                content_html = entry.content[0].get("value", "")
            image_url = self._image_from_entry(entry) or extract_first_image(content_html) or extract_first_image(summary_html)
            items.append(
                NewsItem(
                    id=sha256_text(f"{self.name}:{url or title}"),
                    source=self.name,
                    title=title,
                    url=url,
                    summary=clean_text(summary_html, 500),
                    content=clean_text(content_html or summary_html, 1200),
                    published_at=getattr(entry, "published", None) or getattr(entry, "updated", None),
                    image_url=image_url,
                    raw={"entry": dict(entry)},
                )
            )
        return items

    def _image_from_entry(self, entry: Any) -> str | None:
        for attr in ("media_thumbnail", "media_content"):
            values = getattr(entry, attr, None)
            if values and isinstance(values, list) and values[0].get("url"):
                return values[0]["url"]
        for link in getattr(entry, "links", []) or []:
            if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image"):
                return link.get("href")
        return None
