from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.models import RankedNewsItem


def yes_no(value: bool) -> str:
    return "是" if value else "否"


def _item_block(index: int | None, ranked: RankedNewsItem, filtered: bool = False) -> str:
    prefix = f"### {index}. {ranked.item.title}" if index is not None else f"### {ranked.item.title}"
    reason_label = "过滤原因" if filtered else "推荐理由"
    return f"""{prefix}

- 来源：{ranked.item.source}
- 分类：{ranked.category}
- 规则分 rule_score：{ranked.rule_score:.1f}
- LLM 分 llm_score：{ranked.llm_score:.1f}
- 最终分 final_score：{ranked.final_score:.1f}
- 是否测试工程师相关 qa_related：{yes_no(ranked.qa_related)}
- {reason_label}：{ranked.reason}
- 摘要：{ranked.summary_cn}
- 对我的参考价值：{ranked.action_suggestion}
- 原文链接：{ranked.item.url}

---
"""


def select_recommendations(ranked: list[RankedNewsItem], top_n: int, require_qa: bool) -> tuple[list[RankedNewsItem], list[RankedNewsItem], list[RankedNewsItem]]:
    sorted_items = sorted(ranked, key=lambda x: (x.qa_related, x.final_score), reverse=True)
    recommended = [x for x in sorted_items if x.keep and x.final_score >= 6][:top_n]
    if require_qa and not any(x.qa_related for x in recommended):
        qa_candidates = [x for x in sorted_items if x.qa_related]
        if qa_candidates:
            candidate = qa_candidates[0]
            recommended = [candidate] + [x for x in recommended if x.item.id != candidate.item.id]
            recommended = recommended[:top_n]
    rec_ids = {x.item.id for x in recommended}
    filtered = [x for x in sorted(ranked, key=lambda x: x.final_score, reverse=True) if x.item.id not in rec_ids]
    closest_qa = [x for x in sorted_items if x.qa_related][:3]
    return recommended, filtered, closest_qa


def render_review_markdown(ranked: list[RankedNewsItem], stats: dict, config: dict) -> Path:
    app = config.get("app", {})
    tz = ZoneInfo(app.get("timezone", "Asia/Shanghai"))
    today = datetime.now(tz).strftime("%Y-%m-%d")
    filename = datetime.now(tz).strftime("%Y%m%d.md")
    review_dir = Path(app.get("review_dir", "review"))
    review_dir.mkdir(parents=True, exist_ok=True)
    recommended, filtered, closest_qa = select_recommendations(
        ranked, int(app.get("final_top_n", 8)), bool(app.get("require_qa_related", True))
    )
    qa_count = sum(1 for x in recommended if x.qa_related)
    lines = [
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
        f"- qa_related 数量：{qa_count}",
        f"- LLM 是否启用：{yes_no(bool(config.get('llm', {}).get('enabled', True)))}",
        f"- LLM 模型：{config.get('llm', {}).get('model', '')}",
        f"- 企业微信推送模式：{config.get('wecom', {}).get('mode', 'markdown_plus_news')}",
        "",
        "## 推荐推送内容",
        "",
    ]
    if not recommended:
        lines.extend(["暂无推荐内容，请从下方过滤区人工恢复。", ""])
    for idx, item in enumerate(recommended, 1):
        lines.append(_item_block(idx, item))
    if not any(x.qa_related for x in recommended):
        lines.extend([
            "## 测试工程师相关内容缺失提醒",
            "",
            "今天没有找到强相关的测试工程师内容。",
            "以下是相对最接近的候选内容：",
            "",
        ])
        for item in (closest_qa or filtered[:3]):
            lines.append(f"- {item.item.title}｜final_score {item.final_score:.1f}｜{item.item.url}")
        lines.append("")
    lines.extend(["## 被过滤但可人工恢复的内容", ""])
    for item in filtered[:30]:
        lines.append(_item_block(None, item, filtered=True))
    path = review_dir / filename
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
