from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.core.utils import canonicalize_url, sha256_text
from src.models import NewsItem, ReviewArticle


def item_key(item: NewsItem) -> str:
    base = canonicalize_url(item.canonical_url or item.url)
    if base:
        return sha256_text(base)
    if item.title and item.source:
        return sha256_text(f"{item.title}|{item.source}")
    return sha256_text(item.title)


def url_key(url: str, title: str = "") -> str:
    canonical = canonicalize_url(url)
    return sha256_text(canonical or title)


class StateStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.data = {"seen_items": {}}

    def load(self) -> "StateStore":
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.data = {"seen_items": {}}
        self.data.setdefault("seen_items", {})
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_pushed(self, key: str) -> bool:
        return bool(self.data["seen_items"].get(key, {}).get("pushed_at"))

    def is_seen(self, key: str) -> bool:
        return key in self.data["seen_items"]

    def mark_seen(self, item: NewsItem, key: str | None = None) -> None:
        key = key or item_key(item)
        now = datetime.now(timezone.utc).isoformat()
        record = self.data["seen_items"].setdefault(key, {"first_seen_at": now})
        record.update({"title": item.title, "url": item.url, "source": item.source})

    def mark_pushed_articles(self, articles: list[ReviewArticle]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for article in articles:
            key = url_key(article.url, article.title)
            record = self.data["seen_items"].setdefault(key, {"first_seen_at": now})
            record.update({"title": article.title, "url": article.url, "source": article.source, "pushed_at": now})
