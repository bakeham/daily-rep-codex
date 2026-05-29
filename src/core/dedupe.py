from __future__ import annotations

from src.core.normalize import canonical_url, stable_hash
from src.models import NewsItem


def dedupe_items(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    output: list[NewsItem] = []
    for item in items:
        keys = [canonical_url(item.url), item.url, f"{item.title}|{item.source}", item.title]
        key = next((k for k in keys if k), "")
        digest = stable_hash(key)
        if digest in seen:
            continue
        seen.add(digest)
        output.append(item)
    return output
