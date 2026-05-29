from __future__ import annotations

from src.core.state import StateStore, item_key
from src.models import NewsItem


def dedupe_items(items: list[NewsItem], state: StateStore) -> tuple[list[NewsItem], int]:
    result: list[NewsItem] = []
    seen_run: set[str] = set()
    skipped_pushed = 0
    for item in items:
        key = item_key(item)
        item.dedupe_key = key
        if key in seen_run:
            continue
        seen_run.add(key)
        if state.is_pushed(key):
            skipped_pushed += 1
            continue
        item.seen = state.is_seen(key)
        result.append(item)
        state.mark_seen(item, key)
    return result, skipped_pushed
