from __future__ import annotations

from dataclasses import dataclass, field
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
    canonical_url: str | None = None
    dedupe_key: str | None = None
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


@dataclass
class ReviewArticle:
    title: str
    url: str
    source: str = ""
    category: str = ""
    rule_score: float | None = None
    llm_score: float | None = None
    final_score: float | None = None
    qa_related: bool = False
    reason: str = ""
    summary: str = ""
    action_suggestion: str = ""
    image_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
