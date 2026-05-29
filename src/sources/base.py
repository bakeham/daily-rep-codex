from __future__ import annotations

from src.sources.rest_source import fetch_rest_source
from src.sources.rss_source import fetch_rss_source
from src.models import NewsItem


def fetch_source(source: dict, max_items: int) -> list[NewsItem]:
    if not source.get("enabled", True):
        return []
    source_type = str(source.get("type", "")).lower()
    if source_type == "rss":
        return fetch_rss_source(source, max_items)
    if source_type == "rest":
        return fetch_rest_source(source, max_items)
    raise ValueError(f"不支持的 source type: {source_type}")
