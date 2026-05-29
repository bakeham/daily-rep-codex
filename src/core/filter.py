from __future__ import annotations

from src.models import NewsItem

AI_CODING = ["ai coding", "codex", "claude code", "opencode", "cursor", "kiro"]
AGENT = ["agent", "mcp", "tool calling", "workflow", "memory"]
DATA = ["dbt", "dsl", "data quality", "数据质量", "大数据测试"]
TESTING = ["testing", "qa", "quality assurance", "test case", "test automation", "测试", "测试用例", "测试自动化", "需求评审"]
MODEL = ["模型发布", "benchmark", "推理模型", "多模态", "long context"]
MARKETING = ["融资", "广告", "限时", "优惠", "sponsored", "promotion"]


def has_keyword(text: str, keywords: list[str]) -> bool:
    low = text.lower()
    return any(k.lower() in low for k in keywords)


def is_qa_related(item: NewsItem, qa_keywords: list[str]) -> bool:
    return has_keyword(f"{item.title} {item.summary} {item.content}", qa_keywords or TESTING)


def rule_score(item: NewsItem, qa_keywords: list[str] | None = None) -> float:
    text = f"{item.title} {item.summary} {item.content}"
    score = 3
    if has_keyword(text, AI_CODING):
        score += 3
    if has_keyword(text, AGENT):
        score += 2
    if has_keyword(text, DATA):
        score += 2
    if has_keyword(text, TESTING) or (qa_keywords and has_keyword(text, qa_keywords)):
        score += 3
    if has_keyword(text, MODEL):
        score += 1
    if has_keyword(text, MARKETING):
        score -= 2
    if not item.url or len(item.title) < 6:
        score -= 1
    return float(max(1, min(10, score)))
