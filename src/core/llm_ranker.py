from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from src.core.filter import is_qa_related, rule_score
from src.core.normalize import clean_text
from src.models import NewsItem, RankedNewsItem

PROMPT = """你是一个面向“大数据测试工程师 + AI Coding 工具使用者”的资讯编辑。

请判断下面这条资讯是否值得进入企业微信 AI 早报候选区。

我的重点关注方向：
1. AI Coding：Codex、Claude Code、opencode、Cursor、Kiro、Trellis、Devin、Windsurf
2. Agent 工程：multi-agent、workflow、tool calling、MCP、skill、memory
3. 数据工程：DBT、DSL、Hive、Trino、ClickHouse、数据质量、Profiling
4. 测试工程：自动生成测试用例、需求评审、Bug 验证、QA workflow、测试自动化
5. 大模型能力：长上下文、推理模型、代码模型、多模态文档解析

请只返回 JSON，不要返回 Markdown，不要返回解释文字。

返回格式：
{
  "keep": true/false,
  "score": 1-10,
  "category": "AI Coding / Agent / Model / Data Engineering / Testing / Product / Other",
  "qa_related": true/false,
  "summary_cn": "不超过100字中文摘要",
  "reason": "推荐或不推荐的原因",
  "action_suggestion": "这条资讯对测试工程师/大数据/AI Coding 使用者有什么参考价值"
}

资讯内容：
标题：{title}
来源：{source}
原始摘要：{summary}
正文片段：{content}
链接：{url}
"""


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.S)
    if fenced:
        stripped = fenced.group(1)
    else:
        match = re.search(r"\{.*\}", stripped, re.S)
        if match:
            stripped = match.group(0)
    return json.loads(stripped)


def fallback_rank(item: NewsItem, rule: float, weights: dict, qa_keywords: list[str], reason: str) -> RankedNewsItem:
    qa = is_qa_related(item, qa_keywords)
    return RankedNewsItem(
        item=item,
        rule_score=rule,
        llm_score=rule,
        final_score=round(rule, 2),
        keep=rule >= 6,
        category="Testing" if qa else "Other",
        qa_related=qa,
        summary_cn=clean_text(item.summary or item.title, 100),
        reason=reason,
        action_suggestion="LLM 不可用，建议人工结合标题、摘要和原文判断参考价值。",
    )


def rank_one_with_llm(item: NewsItem, llm_cfg: dict, weights: dict, qa_keywords: list[str]) -> tuple[RankedNewsItem, dict | None, str | None]:
    rule = rule_score(item, qa_keywords)
    if not llm_cfg.get("enabled", True):
        return fallback_rank(item, rule, weights, qa_keywords, "LLM 未启用，使用规则评分兜底"), None, None
    api_key = llm_cfg.get("api_key")
    base_url = llm_cfg.get("base_url")
    model = llm_cfg.get("model")
    if not api_key or "${" in str(api_key) or not model:
        return fallback_rank(item, rule, weights, qa_keywords, "LLM 配置缺失，使用规则评分兜底"), None, None
    try:
        client = OpenAI(api_key=api_key, base_url=base_url or None, timeout=llm_cfg.get("timeout_seconds", 60))
        kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": PROMPT.format(
                title=item.title, source=item.source, summary=item.summary[:1000], content=item.content[:1500], url=item.url
            )}],
            "temperature": llm_cfg.get("temperature", 0.2),
        }
        try:
            response = client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
        except Exception:
            response = client.chat.completions.create(**kwargs)
        raw = response.choices[0].message.content or "{}"
        parsed = extract_json(raw)
        llm_score = float(max(1, min(10, parsed.get("score", rule))))
        final = round(rule * weights["rule"] + llm_score * weights["llm"], 2)
        qa = bool(parsed.get("qa_related")) or is_qa_related(item, qa_keywords)
        ranked = RankedNewsItem(
            item=item,
            rule_score=rule,
            llm_score=llm_score,
            final_score=final,
            keep=bool(parsed.get("keep", final >= 7)),
            category=str(parsed.get("category") or ("Testing" if qa else "Other")),
            qa_related=qa,
            summary_cn=clean_text(parsed.get("summary_cn") or item.summary or item.title, 100),
            reason=clean_text(parsed.get("reason") or "LLM 未给出原因", 300),
            action_suggestion=clean_text(parsed.get("action_suggestion") or "建议人工阅读原文判断可操作价值。", 300),
        )
        return ranked, parsed, None
    except Exception as exc:
        return fallback_rank(item, rule, weights, qa_keywords, f"LLM 调用或 JSON 解析失败，使用规则评分兜底：{type(exc).__name__}"), None, str(exc)


def rank_items_with_llm(items: list[NewsItem], llm_cfg: dict, filters_cfg: dict) -> list[RankedNewsItem]:
    weights = {"rule": float(llm_cfg.get("rule_score_weight", 0.4)), "llm": float(llm_cfg.get("llm_score_weight", 0.6))}
    qa_keywords = filters_cfg.get("qa_keywords") or []
    return [rank_one_with_llm(item, llm_cfg, weights, qa_keywords)[0] for item in items]
