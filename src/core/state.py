from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.utils import item_dedupe_key
from src.models import NewsItem


class StateStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = {"seen_items": {}}

    def load(self) -> "StateStore":
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
                self.data.setdefault("seen_items", {})
            except Exception:
                self.data = {"seen_items": {}}
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_pushed(self, item: NewsItem) -> bool:
        record = self.data.get("seen_items", {}).get(item.id)
        return bool(record and record.get("pushed_at"))

    def mark_seen(self, item: NewsItem) -> None:
        now = datetime.now(timezone.utc).isoformat()
        seen = self.data.setdefault("seen_items", {})
        record = seen.setdefault(item.id, {"first_seen_at": now})
        record.update({"title": item.title, "url": item.url, "source": item.source})
        record.setdefault("first_seen_at", now)

    def mark_pushed_url(self, title: str, url: str, source: str = "review") -> None:
        now = datetime.now(timezone.utc).isoformat()
        key = item_dedupe_key(title, url, source if not url else "")
        seen = self.data.setdefault("seen_items", {})
        record = seen.setdefault(key, {"first_seen_at": now})
        record.update({"title": title, "url": url, "source": source, "pushed_at": now})
