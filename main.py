from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.core.dedupe import dedupe_items
from src.core.llm_ranker import LlmRanker
from src.core.render_markdown import render_review_markdown, write_review
from src.core.review_parser import parse_review_articles
from src.core.state import StateStore
from src.core.utils import load_config, mask_url
from src.models import NewsItem
from src.publishers.wecom import WeComPublisher
from src.sources.base import BaseSource
from src.sources.rest_source import RestSource
from src.sources.rss_source import RssSource


def enabled_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in config.get("sources", []) if s.get("enabled", True)]


def build_source(source_config: dict[str, Any], max_items: int) -> BaseSource:
    source_type = str(source_config.get("type", "")).lower()
    if source_type == "rss":
        return RssSource(source_config, max_items)
    if source_type == "rest":
        return RestSource(source_config, max_items)
    raise ValueError(f"unsupported source type: {source_type}")


def fetch_all(config: dict[str, Any]) -> tuple[list[NewsItem], list[str]]:
    max_items = int(config.get("app", {}).get("max_items_per_source", 50))
    items: list[NewsItem] = []
    errors: list[str] = []
    for source_config in enabled_sources(config):
        try:
            source = build_source(source_config, max_items)
            fetched = source.fetch()
            items.extend(fetched)
            print(f"OK source={source.name} type={source_config.get('type')} items={len(fetched)}")
        except Exception as exc:
            error = f"ERROR source={source_config.get('name')} type={source_config.get('type')}: {exc}"
            print(error)
            errors.append(error)
    return items, errors


def cmd_test_sources(config: dict[str, Any]) -> int:
    items, errors = fetch_all(config)
    print(f"Total fetched items: {len(items)}")
    return 1 if errors and not items else 0


def cmd_generate(config: dict[str, Any]) -> int:
    app = config.get("app", {})
    state = StateStore(app.get("state_path", "data/state.json")).load()
    raw_items, _ = fetch_all(config)
    deduped = dedupe_items(raw_items)
    candidates: list[NewsItem] = []
    for item in deduped:
        item.seen = item.id in state.data.get("seen_items", {})
        if state.is_pushed(item):
            continue
        state.mark_seen(item)
        candidates.append(item)
    ranker = LlmRanker(config.get("llm", {}), config.get("filters", {}).get("qa_keywords", []))
    ranked = ranker.rank_items_with_llm(candidates)
    tz = ZoneInfo(app.get("timezone", "Asia/Shanghai"))
    date_str = datetime.now(tz).strftime("%Y-%m-%d")
    date_file = datetime.now(tz).strftime("%Y%m%d")
    stats = {
        "source_count": len(enabled_sources(config)),
        "raw_count": len(raw_items),
        "deduped_count": len(deduped),
        "llm_available": ranker.available,
        "llm_model": ranker.model if ranker.available else "未配置",
    }
    markdown, recommendations = render_review_markdown(date_str, ranked, stats, config)
    review_path = Path(app.get("review_dir", "review")) / f"{date_file}.md"
    write_review(str(review_path), markdown)
    state.save()
    print(f"Generated review draft: {review_path}")
    print(f"Recommended items: {len(recommendations)}; qa_related: {sum(1 for x in recommendations if x.qa_related)}")
    print("Generate stage does not send anything to WeCom.")
    return 0


def cmd_test_llm(config: dict[str, Any]) -> int:
    item = NewsItem(
        id="test-llm",
        source="builtin_test",
        title="LLM 自动生成测试用例的新方法",
        url="https://example.com/llm-test-generation",
        summary="一种基于需求文档和代码变更自动生成测试用例的 Agent 工作流，支持测试覆盖率分析和数据质量校验。",
        content="一种基于需求文档和代码变更自动生成测试用例的 Agent 工作流，支持测试覆盖率分析和数据质量校验。",
    )
    ranker = LlmRanker(config.get("llm", {}), config.get("filters", {}).get("qa_keywords", []))
    ranked = ranker.rank_one(item)
    parsed_ok = bool(ranked.summary_cn and ranked.reason)
    success = ranker.available and parsed_ok and ranked.qa_related and ranked.llm_score >= 8
    print(f"LLM 连接是否成功：{'是' if ranker.available and parsed_ok else '否'}")
    print(f"模型名：{ranker.model}")
    print("返回 JSON：")
    print(json.dumps({
        "keep": ranked.keep,
        "score": ranked.llm_score,
        "category": ranked.category,
        "qa_related": ranked.qa_related,
        "summary_cn": ranked.summary_cn,
        "reason": ranked.reason,
        "action_suggestion": ranked.action_suggestion,
    }, ensure_ascii=False, indent=2))
    print(f"解析是否成功：{'是' if parsed_ok else '否'}")
    print(f"qa_related 是否为 true：{'是' if ranked.qa_related else '否'}")
    return 0 if success else 1


def cmd_test_wecom(config: dict[str, Any]) -> int:
    publisher = WeComPublisher(config.get("wecom", {}))
    ok, msg = publisher.send_markdown("# AI 早报 PoC 测试\n企业微信机器人 Markdown 连通性测试。")
    print(f"Webhook：{mask_url(publisher.webhook_url)}")
    print(f"企业微信 Markdown 测试：{'成功' if ok else '失败'} - {msg}")
    return 0 if ok else 1


def cmd_send(config: dict[str, Any], file_path: str) -> int:
    path = Path(file_path)
    if not path.exists():
        print(f"ERROR: review file not found: {file_path}")
        return 1
    markdown = path.read_text(encoding="utf-8")
    articles = parse_review_articles(markdown)
    print(f"Parsed recommended articles for news cards: {len(articles)}")
    publisher = WeComPublisher(config.get("wecom", {}))
    overall_ok, news_ok, messages = publisher.send(markdown, articles)
    for msg in messages:
        print(msg)
    if not overall_ok:
        print("ERROR: send failed; state will not be updated.")
        return 1
    state = StateStore(config.get("app", {}).get("state_path", "data/state.json")).load()
    for article in articles:
        state.mark_pushed_url(article.title, article.url, article.source or "review")
    state.save()
    if not news_ok:
        print("WARNING: markdown sent but news card failed; pushed_at was updated for successfully accepted markdown send.")
    print("Send completed; pushed_at state updated.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 早报采集、LLM 评分、人工审核、企业微信推送 PoC")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate")
    send = sub.add_parser("send")
    send.add_argument("--file", required=True)
    sub.add_parser("test-sources")
    sub.add_parser("test-wecom")
    sub.add_parser("test-llm")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.command == "generate":
        return cmd_generate(config)
    if args.command == "send":
        return cmd_send(config, args.file)
    if args.command == "test-sources":
        return cmd_test_sources(config)
    if args.command == "test-wecom":
        return cmd_test_wecom(config)
    if args.command == "test-llm":
        return cmd_test_llm(config)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
