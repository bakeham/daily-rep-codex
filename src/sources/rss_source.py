from __future__ import annotations

import feedparser

from src.core.normalize import clean_text, first_image_from_html, item_id
from src.models import NewsItem


def _rss_image(entry: object) -> str | None:
    for attr in ("media_thumbnail", "media_content"):
        values = getattr(entry, attr, None) or entry.get(attr, []) if hasattr(entry, "get") else []
        if values and isinstance(values, list) and values[0].get("url"):
            return values[0]["url"]
    for enc in getattr(entry, "enclosures", []) or []:
        if enc.get("href") and str(enc.get("type", "")).startswith("image"):
            return enc["href"]
    html = ""
    if getattr(entry, "summary", None):
        html += entry.summary
    for c in getattr(entry, "content", []) or []:
        html += c.get("value", "")
    return first_image_from_html(html)


def fetch_rss_source(source: dict, max_items: int) -> list[NewsItem]:
    feed = feedparser.parse(source["url"])
    if getattr(feed, "bozo", False) and not feed.entries:
        raise RuntimeError(f"RSS 解析失败: {getattr(feed, 'bozo_exception', 'unknown')}")
    items: list[NewsItem] = []
    for entry in feed.entries[:max_items]:
        title = clean_text(getattr(entry, "title", ""))
        url = (getattr(entry, "link", "") or "").strip()
        if not title or not url:
            continue
        summary_raw = getattr(entry, "summary", None) or getattr(entry, "description", "")
        content_raw = summary_raw
        if getattr(entry, "content", None):
            content_raw = entry.content[0].get("value", summary_raw)
        item = NewsItem(
            id=item_id(source["name"], title, url),
            source=source["name"],
            title=title,
            url=url,
            summary=clean_text(summary_raw, 1000),
            content=clean_text(content_raw, 2000),
            published_at=getattr(entry, "published", None) or getattr(entry, "updated", None),
            image_url=_rss_image(entry),
            raw=dict(entry),
        )
        items.append(item)
    return items
