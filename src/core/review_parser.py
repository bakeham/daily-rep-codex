from __future__ import annotations

import re
from pathlib import Path

from src.models import ReviewArticle


def parse_review_articles(path: str) -> tuple[str, list[ReviewArticle]]:
    text = Path(path).read_text(encoding="utf-8")
    section = _between(text, "## 推荐推送内容", ["## 测试工程师相关内容缺失提醒", "## 被过滤但可人工恢复的内容"])
    articles: list[ReviewArticle] = []
    blocks = re.split(r"\n(?=###\s+)", section)
    for block in blocks:
        block = block.strip()
        if not block.startswith("###"):
            continue
        title = re.sub(r"^###\s+(?:\d+\.\s*)?", "", block.splitlines()[0]).strip()
        fields = _fields(block)
        url = fields.get("原文链接", "").strip()
        if not title or not url:
            continue
        articles.append(
            ReviewArticle(
                title=title,
                url=url,
                source=fields.get("来源", ""),
                category=fields.get("分类", ""),
                rule_score=_float(fields.get("规则分 rule_score") or fields.get("规则分")),
                llm_score=_float(fields.get("LLM 分 llm_score") or fields.get("LLM 分")),
                final_score=_float(fields.get("最终分 final_score") or fields.get("最终分")),
                qa_related=_bool(fields.get("是否测试工程师相关 qa_related") or fields.get("是否测试工程师相关")),
                reason=fields.get("推荐理由", ""),
                summary=fields.get("摘要", ""),
                action_suggestion=fields.get("对我的参考价值", ""),
                image_url=fields.get("图片链接") or None,
            )
        )
    return text, articles


def _between(text: str, start_header: str, end_headers: list[str]) -> str:
    start = text.find(start_header)
    if start < 0:
        return ""
    start += len(start_header)
    ends = [text.find(h, start) for h in end_headers if text.find(h, start) >= 0]
    end = min(ends) if ends else len(text)
    return text[start:end]


def _fields(block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in block.splitlines():
        m = re.match(r"^-\s*([^：:]+)：\s*(.*)$", line.strip())
        if m:
            fields[m.group(1).strip()] = m.group(2).strip()
    return fields


def _float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(re.search(r"-?\d+(?:\.\d+)?", value).group(0))  # type: ignore[union-attr]
    except Exception:
        return None


def _bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"是", "true", "yes", "1", "测试相关"}
