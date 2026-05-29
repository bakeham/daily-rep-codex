from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.core.utils import bool_cn
from src.models import RankedNewsItem


def select_recommendations(ranked: list[RankedNewsItem], top_n: int, require_qa: bool) -> tuple[list[RankedNewsItem], list[RankedNewsItem], list[RankedNewsItem]]:
    candidates = sorted(ranked, key=lambda x: (x.qa_related, x.final_score), reverse=True)
    recommended = [x for x in candidates if x.keep and x.final_score >= 6][:top_n]
    if require_qa and not any(x.qa_related for x in recommended):
        qa_candidates = [x for x in candidates if x.qa_related]
        if qa_candidates:
            best = qa_candidates[0]
            recommended = [best] + [x for x in recommended if x.item.id != best.item.id]
            recommended = recommended[:top_n]
    recommended_ids = {x.item.id for x in recommended}
    filtered = [x for x in sorted(ranked, key=lambda x: x.final_score, reverse=True) if x.item.id not in recommended_ids]
    qa_missing_closest = [] if any(x.qa_related for x in recommended) else sorted(ranked, key=lambda x: x.rule_score, reverse=True)[:3]
    return recommended, filtered, qa_missing_closest


def render_review(ranked: list[RankedNewsItem], stats: dict[str, Any], config: dict[str, Any]) -> tuple[str, str]:
    tz = ZoneInfo(config.get("app", {}).get("timezone", "Asia/Shanghai"))
    today = datetime.now(tz).strftime("%Y-%m-%d")
    app = config.get("app", {})
    recommended, filtered, qa_missing = select_recommendations(ranked, int(app.get("final_top_n", 8)), bool(app.get("require_qa_related", True)))
    lines: list[str] = [
        f"# AI 早报候选内容 - {today}",
        "",
        "> 人工审核说明：",
        "> 1. 删除不想推送的条目。",
        "> 2. 可以修改标题、摘要、推荐理由。",
        "> 3. 保留的内容会在 send 阶段推送到企业微信。",
        "> 4. 建议至少保留 1 条“测试工程师 / QA / 测试自动化”相关内容。",
        "",
        "## 本次筛选概览",
        "",
        f"- 采集来源数：{stats.get('source_count', 0)}",
        f"- 原始资讯数：{stats.get('raw_count', 0)}",
        f"- 去重后资讯数：{stats.get('deduped_count', 0)}",
        f"- 推荐区数量：{len(recommended)}",
        f"- qa_related 数量：{sum(1 for x in recommended if x.qa_related)}",
        f"- LLM 是否启用：{bool_cn(bool(config.get('llm', {}).get('enabled', True)))}",
        f"- LLM 模型：{config.get('llm', {}).get('model', '')}",
        f"- 企业微信推送模式：{config.get('wecom', {}).get('mode', '')}",
        "",
        "## 推荐推送内容",
        "",
    ]
    if recommended:
        for i, item in enumerate(recommended, 1):
            lines.extend(_render_ranked(item, prefix=f"### {i}. ", filtered=False))
    else:
        lines.append("暂无推荐内容，可从下方被过滤内容中人工恢复。")
        lines.append("")
    if qa_missing:
        lines.extend([
            "## 测试工程师相关内容缺失提醒",
            "",
            "今天没有找到强相关的测试工程师内容。以下是相对最接近的候选内容：",
            "",
        ])
        for item in qa_missing:
            lines.extend([f"- {item.item.title}（规则分 {item.rule_score}，最终分 {item.final_score}）：{item.item.url}"])
        lines.append("")
    lines.extend(["## 被过滤但可人工恢复的内容", ""])
    for item in filtered[:30]:
        lines.extend(_render_ranked(item, prefix="### ", filtered=True))
    return today.replace("-", ""), "\n".join(lines).rstrip() + "\n"


def _render_ranked(r: RankedNewsItem, prefix: str, filtered: bool) -> list[str]:
    title = r.item.title.replace("\n", " ")
    score_label = "规则分：" if filtered else "规则分 rule_score："
    llm_label = "LLM 分：" if filtered else "LLM 分 llm_score："
    final_label = "最终分：" if filtered else "最终分 final_score："
    qa_label = "是否测试工程师相关：" if filtered else "是否测试工程师相关 qa_related："
    reason_label = "过滤原因：" if filtered else "推荐理由："
    return [
        f"{prefix}{title}",
        "",
        f"- 来源：{r.item.source}",
        f"- 分类：{r.category}",
        f"- {score_label}{r.rule_score:.1f}",
        f"- {llm_label}{r.llm_score:.1f}",
        f"- {final_label}{r.final_score:.2f}",
        f"- {qa_label}{bool_cn(r.qa_related)}",
        f"- {reason_label}{r.reason}",
        f"- 摘要：{r.summary_cn}",
        f"- 对我的参考价值：{r.action_suggestion}",
        f"- 原文链接：{r.item.url}",
        f"- 图片链接：{r.item.image_url or ''}",
        "",
        "---",
        "",
    ]
