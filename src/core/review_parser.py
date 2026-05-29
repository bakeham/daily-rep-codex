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
    image_url: str = ""


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^##\s+{re.escape(heading)}\s*$", text, flags=re.M)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"^##\s+", text[start:], flags=re.M)
    end = start + next_match.start() if next_match else len(text)
    return text[start:end]


def _field(block: str, name: str) -> str:
    match = re.search(rf"^-\s*{re.escape(name)}：\s*(.*)$", block, flags=re.M)
    return match.group(1).strip() if match else ""


def _float(value: str) -> float:
    try:
        return float(re.search(r"-?\d+(?:\.\d+)?", value).group(0))  # type: ignore[union-attr]
    except Exception:
        return 0.0


def parse_review_articles(markdown: str) -> list[ReviewArticle]:
    rec = _section(markdown, "推荐推送内容")
    blocks = re.split(r"(?=^###\s+)", rec, flags=re.M)
    articles: list[ReviewArticle] = []
    for block in blocks:
        if not block.strip().startswith("###"):
            continue
        first = block.strip().splitlines()[0]
        title = re.sub(r"^###\s+(?:\d+\.\s*)?", "", first).strip()
        url = _field(block, "原文链接")
        if not title or not url:
            continue
        qa_text = _field(block, "是否测试工程师相关 qa_related")
        articles.append(
            ReviewArticle(
                title=title,
                url=url,
                source=_field(block, "来源"),
                category=_field(block, "分类"),
                rule_score=_float(_field(block, "规则分 rule_score")),
                llm_score=_float(_field(block, "LLM 分 llm_score")),
                final_score=_float(_field(block, "最终分 final_score")),
                qa_related=qa_text.lower() in {"是", "true", "yes", "y", "1"},
                reason=_field(block, "推荐理由"),
                summary=_field(block, "摘要"),
                action_suggestion=_field(block, "对我的参考价值"),
                image_url=_field(block, "图片链接 image_url"),
            )
        )
    return articles
