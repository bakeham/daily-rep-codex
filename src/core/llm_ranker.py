from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from src.core.filter import is_qa_related, rule_score_item
from src.core.utils import clean_html, clamp
from src.models import NewsItem, RankedNewsItem

CATEGORIES = "AI Coding / Agent / Model / Data Engineering / Testing / Product / Other"


def build_prompt(item: NewsItem) -> str:
    return f"""你是一个面向“大数据测试工程师 + AI Coding 工具使用者”的资讯编辑。

请判断下面这条资讯是否值得进入企业微信 AI 早报候选区。

我的重点关注方向：
1. AI Coding：Codex、Claude Code、opencode、Cursor、Kiro、Trellis、Devin、Windsurf
2. Agent 工程：multi-agent、workflow、tool calling、MCP、skill、memory
3. 数据工程：DBT、DSL、Hive、Trino、ClickHouse、数据质量、Profiling
4. 测试工程：自动生成测试用例、需求评审、Bug 验证、QA workflow、测试自动化
5. 大模型能力：长上下文、推理模型、代码模型、多模态文档解析

请只返回 JSON，不要返回 Markdown，不要返回解释文字。

返回格式：
{{
  "keep": true,
  "score": 1,
  "category": "AI Coding / Agent / Model / Data Engineering / Testing / Product / Other",
  "qa_related": true,
  "summary_cn": "不超过100字中文摘要",
  "reason": "推荐或不推荐的原因",
  "action_suggestion": "这条资讯对测试工程师/大数据/AI Coding 使用者有什么参考价值"
}}

资讯内容：
标题：{item.title}
来源：{item.source}
原始摘要：{item.summary[:800]}
正文片段：{item.content[:1200]}
链接：{item.url}
"""


def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.S | re.I)
    if fence:
        cleaned = fence.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("LLM JSON is not an object")
    return data


def fallback_rank(item: NewsItem, rule_score: float, reason: str, weights: tuple[float, float]) -> RankedNewsItem:
    qa = is_qa_related(item)
    summary = clean_html(item.summary or item.content or item.title, 100)
    return RankedNewsItem(
        item=item,
        rule_score=rule_score,
        llm_score=rule_score,
        final_score=round(rule_score * weights[0] + rule_score * weights[1], 2),
        keep=rule_score >= 6 or qa,
        category="Testing" if qa else "Other",
        qa_related=qa,
        summary_cn=summary,
        reason=reason,
        action_suggestion="LLM 不可用，建议人工根据标题、摘要和规则分判断参考价值。",
    )


class LlmRanker:
    def __init__(self, config: dict[str, Any], qa_keywords: list[str] | None = None) -> None:
        self.config = config
        self.enabled = bool(config.get("enabled", True))
        self.base_url = str(config.get("base_url") or "")
        self.api_key = str(config.get("api_key") or "")
        self.model = str(config.get("model") or "")
        self.temperature = float(config.get("temperature", 0.2))
        self.timeout = float(config.get("timeout_seconds", 60))
        self.rule_weight = float(config.get("rule_score_weight", 0.4))
        self.llm_weight = float(config.get("llm_score_weight", 0.6))
        self.qa_keywords = qa_keywords or []

    @property
    def available(self) -> bool:
        return self.enabled and bool(self.base_url and self.api_key and self.model and not self.api_key.startswith("${"))

    def _client(self) -> OpenAI:
        return OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=self.timeout)

    def rank_one(self, item: NewsItem) -> RankedNewsItem:
        rule_score = rule_score_item(item)
        weights = (self.rule_weight, self.llm_weight)
        if not self.available:
            return fallback_rank(item, rule_score, "LLM 不可用，使用规则评分兜底。", weights)
        try:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [{"role": "user", "content": build_prompt(item)}],
                "temperature": self.temperature,
            }
            try:
                response = self._client().chat.completions.create(response_format={"type": "json_object"}, **kwargs)
            except Exception:
                response = self._client().chat.completions.create(**kwargs)
            content = response.choices[0].message.content or "{}"
            data = extract_json(content)
            llm_score = float(clamp(float(data.get("score", rule_score))))
            qa = bool(data.get("qa_related", False)) or is_qa_related(item, self.qa_keywords)
            final = round(rule_score * self.rule_weight + llm_score * self.llm_weight, 2)
            return RankedNewsItem(
                item=item,
                rule_score=rule_score,
                llm_score=round(llm_score, 1),
                final_score=final,
                keep=bool(data.get("keep", llm_score >= 7)) or qa and final >= 5,
                category=str(data.get("category") or ("Testing" if qa else "Other")),
                qa_related=qa,
                summary_cn=clean_html(data.get("summary_cn") or item.summary or item.title, 100),
                reason=clean_html(data.get("reason") or "LLM 未返回推荐理由。", 200),
                action_suggestion=clean_html(data.get("action_suggestion") or "请人工判断参考价值。", 200),
            )
        except Exception as exc:
            return fallback_rank(item, rule_score, f"LLM 调用或 JSON 解析失败，使用规则评分兜底：{exc}", weights)

    def rank_items_with_llm(self, items: list[NewsItem]) -> list[RankedNewsItem]:
        return [self.rank_one(item) for item in items]
