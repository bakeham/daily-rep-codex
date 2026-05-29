from __future__ import annotations

from src.core.utils import clamp
from src.models import NewsItem

AI_CODING = ("ai coding", "codex", "claude code", "opencode", "cursor", "kiro")
AGENT = ("agent", "mcp", "tool calling", "workflow", "memory", "multi-agent")
DATA = ("dbt", "dsl", "data quality", "数据质量", "大数据测试", "data validation", "profiling")
TESTING = ("testing", "qa", "quality assurance", "test case", "test generation", "test automation", "unit test", "integration test", "测试", "测试工程师", "测试用例", "测试自动化", "需求评审", "数据校验", "llm 辅助测试")
MODEL = ("模型发布", "benchmark", "推理模型", "多模态", "long context", "reasoning model")
MARKETING = ("融资", "广告", "赞助", "限时优惠", "coupon", "sponsored", "funding")


def item_text(item: NewsItem) -> str:
    return f"{item.title}\n{item.summary}\n{item.content}".lower()


def contains_any(text: str, keywords: list[str] | tuple[str, ...]) -> bool:
    low = text.lower()
    return any(k.lower() in low for k in keywords)


def is_qa_related(item: NewsItem, qa_keywords: list[str] | None = None) -> bool:
    return contains_any(item_text(item), qa_keywords or list(TESTING))


def rule_score_item(item: NewsItem, duplicate: bool = False) -> float:
    text = item_text(item)
    score = 3.0
    if contains_any(text, AI_CODING):
        score += 3
    if contains_any(text, AGENT):
        score += 2
    if contains_any(text, DATA):
        score += 2
    if contains_any(text, TESTING):
        score += 3
    if contains_any(text, MODEL):
        score += 1
    if contains_any(text, MARKETING):
        score -= 2
    if not item.url or len(item.title.strip()) < 6:
        score -= 1
    if duplicate:
        score -= 3
    return round(clamp(score), 1)
