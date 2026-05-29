from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class NewsItem:
    id: str
    source: str
    title: str
    url: str
    summary: str = ""
    content: str = ""
    published_at: str | None = None
    category: str = "unknown"
    image_url: str | None = None
    raw: dict[str, Any] | None = None
    seen: bool = False


@dataclass
class RankedNewsItem:
    item: NewsItem
    rule_score: float
    llm_score: float
    final_score: float
    keep: bool
    category: str
    qa_related: bool
    summary_cn: str
    reason: str
    action_suggestion: str
