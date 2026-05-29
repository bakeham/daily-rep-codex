from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ReviewArticle:
    title: str
    url: str
    source: str = ""
    category: str = ""
    rule_score: float = 0.0
    llm_score: float = 0.0
    final_score: float = 0.0
    qa_related: bool = False
    reason: str = ""
    summary: str = ""
    action_suggestion: str = ""


def _section(text: str, name: str) -> str:
    pattern = rf"^## {re.escape(name)}\s*$"
    match = re.search(pattern, text, re.M)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"^## .+?$", text[start:], re.M)
    end = start + next_match.start() if next_match else len(text)
    return text[start:end]


def _value(block: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}：\s*(.*)$", block, re.M)
    return match.group(1).strip() if match else ""


def _float(value: str) -> float:
    match = re.search(r"\d+(?:\.\d+)?", value or "")
    return float(match.group(0)) if match else 0.0


def parse_recommended_articles(markdown: str) -> list[ReviewArticle]:
    section = _section(markdown, "推荐推送内容")
    articles: list[ReviewArticle] = []
    for match in re.finditer(r"^###\s+(?:\d+\.\s*)?(.*?)\s*$", section, re.M):
        start = match.end()
        next_match = re.search(r"^###\s+", section[start:], re.M)
        end = start + next_match.start() if next_match else len(section)
        block = section[start:end]
        title = match.group(1).strip()
        url = _value(block, "原文链接")
        if not title or not url:
            continue
        qa_text = _value(block, "是否测试工程师相关 qa_related") or _value(block, "是否测试工程师相关")
        articles.append(ReviewArticle(
            title=title,
            url=url,
            source=_value(block, "来源"),
            category=_value(block, "分类"),
            rule_score=_float(_value(block, "规则分 rule_score") or _value(block, "规则分")),
            llm_score=_float(_value(block, "LLM 分 llm_score") or _value(block, "LLM 分")),
            final_score=_float(_value(block, "最终分 final_score") or _value(block, "最终分")),
            qa_related=("是" in qa_text or "true" in qa_text.lower()),
            reason=_value(block, "推荐理由"),
            summary=_value(block, "摘要"),
            action_suggestion=_value(block, "对我的参考价值"),
        ))
    return articles
