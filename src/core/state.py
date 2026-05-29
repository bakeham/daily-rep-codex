from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.core.normalize import canonical_url, stable_hash
from src.models import NewsItem


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JsonState:
    def __init__(self, path: str):
        self.path = Path(path)
        self.data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"seen_items": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"seen_items": {}}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def key_for(title: str, url: str, source: str = "") -> str:
        return stable_hash(canonical_url(url) or f"{title}|{source}" or title)

    def is_pushed(self, item: NewsItem) -> bool:
        seen = self.data.get("seen_items", {})
        keys = {item.id, self.key_for("", item.url, ""), self.key_for(item.title, item.url, item.source)}
        return any(bool(seen.get(key, {}).get("pushed_at")) for key in keys)

    def mark_seen(self, item: NewsItem) -> None:
        seen = self.data.setdefault("seen_items", {})
        record = seen.setdefault(item.id, {"first_seen_at": now_iso()})
        record.update({"title": item.title, "url": item.url, "source": item.source})

    def mark_pushed(self, title: str, url: str, source: str = "review") -> None:
        seen = self.data.setdefault("seen_items", {})
        for key in {self.key_for(title, url, source), self.key_for("", url, "")}:
            record = seen.setdefault(key, {"first_seen_at": now_iso()})
            record.update({"title": title, "url": url, "source": source, "pushed_at": now_iso()})
