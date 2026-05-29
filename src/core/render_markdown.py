from __future__ import annotations

from pathlib import Path
from typing import Any

from src.core.utils import truthy_zh
from src.models import RankedNewsItem


def select_recommendations(ranked: list[RankedNewsItem], top_n: int, require_qa: bool) -> tuple[list[RankedNewsItem], list[RankedNewsItem], list[RankedNewsItem]]:
    sorted_items = sorted(ranked, key=lambda x: (x.qa_related, x.final_score), reverse=True)
    kept = [x for x in sorted_items if x.keep and x.final_score >= 5]
    qa_items = [x for x in sorted_items if x.qa_related]
    if require_qa and not any(x.qa_related for x in kept) and qa_items:
        kept.insert(0, qa_items[0])
    # Ensure at least one QA item remains in top_n if one exists.
    recommendations = sorted(kept, key=lambda x: x.final_score, reverse=True)[:top_n]
    if require_qa and qa_items and not any(x.qa_related for x in recommendations):
        recommendations = [qa_items[0]] + recommendations[: max(0, top_n - 1)]
    rec_ids = {id(x) for x in recommendations}
    filtered = [x for x in sorted(ranked, key=lambda x: x.final_score, reverse=True) if id(x) not in rec_ids]
    missing_candidates = [] if any(x.qa_related for x in recommendations) else sorted_items[:3]
    return recommendations, filtered, missing_candidates


def _item_block(item: RankedNewsItem, index: int | None = None, filtered: bool = False) -> str:
    title = f"### {index}. {item.item.title}" if index is not None else f"### {item.item.title}"
    label = "过滤原因" if filtered else "推荐理由"
    reason = item.reason if filtered else item.reason
    return f"""{title}

- 来源：{item.item.source}
- 分类：{item.category}
- 规则分 rule_score：{item.rule_score:.1f}
- LLM 分 llm_score：{item.llm_score:.1f}
- 最终分 final_score：{item.final_score:.2f}
- 是否测试工程师相关 qa_related：{truthy_zh(item.qa_related)}
- {label}：{reason}
- 摘要：{item.summary_cn}
- 对我的参考价值：{item.action_suggestion}
- 原文链接：{item.item.url}
- 图片链接 image_url：{item.item.image_url or ''}

---
"""


def render_review_markdown(
    date_str: str,
    ranked: list[RankedNewsItem],
    stats: dict[str, Any],
    config: dict[str, Any],
) -> tuple[str, list[RankedNewsItem]]:
    top_n = int(config.get("app", {}).get("final_top_n", 8))
    require_qa = bool(config.get("app", {}).get("require_qa_related", True))
    recommendations, filtered, missing_candidates = select_recommendations(ranked, top_n, require_qa)
    qa_count = sum(1 for x in recommendations if x.qa_related)
    lines = [
        f"# AI 早报候选内容 - {date_str}",
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
        f"- 推荐区数量：{len(recommendations)}",
        f"- qa_related 数量：{qa_count}",
        f"- LLM 是否启用：{truthy_zh(bool(config.get('llm', {}).get('enabled', True)))}",
        f"- LLM 模型：{config.get('llm', {}).get('model', '')}",
        f"- 企业微信推送模式：{config.get('wecom', {}).get('mode', 'markdown_plus_news')}",
        "",
        "## 推荐推送内容",
        "",
    ]
    if recommendations:
        for i, item in enumerate(recommendations, 1):
            lines.append(_item_block(item, i))
    else:
        lines.append("暂无推荐内容，请人工从被过滤区恢复。\n")

    if missing_candidates:
        lines.extend([
            "## 测试工程师相关内容缺失提醒",
            "",
            "今天没有找到强相关的测试工程师内容。",
            "以下是相对最接近的候选内容：",
            "",
        ])
        for item in missing_candidates:
            lines.extend([f"- {item.item.title}（final_score={item.final_score:.2f}）：{item.item.url}"])
        lines.append("")

    lines.extend(["## 被过滤但可人工恢复的内容", ""])
    for item in filtered[:30]:
        lines.append(_item_block(item, None, filtered=True))
    return "\n".join(lines).rstrip() + "\n", recommendations


def write_review(path: str, content: str) -> None:
    review_path = Path(path)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(content, encoding="utf-8")
