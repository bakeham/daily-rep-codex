from __future__ import annotations

from src.core.utils import clamp
from src.models import NewsItem, RankedNewsItem


def text_blob(item: NewsItem) -> str:
    return f"{item.title}\n{item.summary}\n{item.content}".lower()


def contains_any(blob: str, keywords: list[str]) -> bool:
    return any(k.lower() in blob for k in keywords)


def is_qa_related(item: NewsItem, qa_keywords: list[str]) -> bool:
    return contains_any(text_blob(item), qa_keywords)


def rule_score_item(item: NewsItem, qa_keywords: list[str]) -> float:
    blob = text_blob(item)
    score = 3.0
    groups = [
        (["ai coding", "codex", "claude code", "opencode", "cursor", "kiro"], 3),
        (["agent", "mcp", "tool calling", "workflow", "memory"], 2),
        (["dbt", "dsl", "data quality", "数据质量", "大数据测试"], 2),
        (["testing", "qa", "测试", "测试用例", "测试自动化", "需求评审"], 3),
        (["模型发布", "benchmark", "推理模型", "多模态"], 1),
    ]
    for keywords, points in groups:
        if contains_any(blob, keywords):
            score += points
    if contains_any(blob, ["融资", "广告", "赞助", "限时优惠", "营销", "推广"]):
        score -= 2
    if not item.url or len(item.title) < 5:
        score -= 1
    return round(clamp(score), 1)


def fallback_rank(item: NewsItem, rule_score: float, qa_keywords: list[str], reason: str = "LLM 不可用，使用规则评分兜底") -> RankedNewsItem:
    qa = is_qa_related(item, qa_keywords)
    summary = item.summary or item.content or item.title
    return RankedNewsItem(
        item=item,
        rule_score=rule_score,
        llm_score=rule_score,
        final_score=rule_score,
        keep=rule_score >= 6 or qa,
        category="Testing" if qa else "Other",
        qa_related=qa,
        summary_cn=summary[:100],
        reason=reason,
        action_suggestion="可结合原文判断是否纳入 AI Coding、测试工程或数据质量实践。",
    )
