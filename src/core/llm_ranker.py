from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from src.core.filter import fallback_rank, is_qa_related, rule_score_item
from src.core.utils import clamp
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
  "keep": true,
  "score": 8,
  "category": "AI Coding / Agent / Model / Data Engineering / Testing / Product / Other",
  "qa_related": true,
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
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


class LlmRanker:
    def __init__(self, config: dict[str, Any], qa_keywords: list[str]):
        self.config = config
        self.qa_keywords = qa_keywords
        self.enabled = bool(config.get("enabled", True))
        self.model = config.get("model") or ""
        self.rule_weight = float(config.get("rule_score_weight", 0.4))
        self.llm_weight = float(config.get("llm_score_weight", 0.6))
        self.last_error: str | None = None

    def configured(self) -> bool:
        return bool(self.config.get("base_url") and self.config.get("api_key") and self.model and "${" not in str(self.config.get("api_key")))

    def rank_items(self, items: list[NewsItem]) -> list[RankedNewsItem]:
        ranked: list[RankedNewsItem] = []
        for item in items:
            rule_score = rule_score_item(item, self.qa_keywords)
            if not self.enabled or not self.configured():
                ranked.append(fallback_rank(item, rule_score, self.qa_keywords))
                continue
            ranked.append(self.rank_one(item, rule_score))
        return ranked

    def rank_one(self, item: NewsItem, rule_score: float | None = None) -> RankedNewsItem:
        rule_score = rule_score if rule_score is not None else rule_score_item(item, self.qa_keywords)
        try:
            client = OpenAI(
                base_url=self.config.get("base_url"),
                api_key=self.config.get("api_key"),
                timeout=float(self.config.get("timeout_seconds", 60)),
            )
            prompt = PROMPT.format(
                title=item.title,
                source=item.source,
                summary=(item.summary or "")[:1000],
                content=(item.content or "")[:1500],
                url=item.url,
            )
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": float(self.config.get("temperature", 0.2)),
            }
            try:
                resp = client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
            except Exception:
                resp = client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content or "{}"
            data = extract_json(content)
            llm_score = float(clamp(float(data.get("score", rule_score))))
            final = round(rule_score * self.rule_weight + llm_score * self.llm_weight, 2)
            qa = bool(data.get("qa_related")) or is_qa_related(item, self.qa_keywords)
            return RankedNewsItem(
                item=item,
                rule_score=rule_score,
                llm_score=llm_score,
                final_score=final,
                keep=bool(data.get("keep", llm_score >= 7)),
                category=str(data.get("category") or ("Testing" if qa else "Other")),
                qa_related=qa,
                summary_cn=str(data.get("summary_cn") or item.summary or item.title)[:120],
                reason=str(data.get("reason") or "LLM 未给出原因"),
                action_suggestion=str(data.get("action_suggestion") or "结合原文评估实践价值"),
            )
        except Exception as exc:
            self.last_error = str(exc)
            return fallback_rank(item, rule_score, self.qa_keywords, f"LLM 调用或 JSON 解析失败，使用规则评分兜底：{type(exc).__name__}")
