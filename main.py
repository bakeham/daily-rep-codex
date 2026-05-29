from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.core.dedupe import dedupe_items
from src.core.llm_ranker import LlmRanker
from src.core.render_markdown import render_review
from src.core.review_parser import parse_review_articles
from src.core.state import StateStore
from src.core.utils import load_config, mask_url
from src.models import NewsItem
from src.publishers.wecom import WeComPublisher
from src.sources.rest_source import RestSource
from src.sources.rss_source import RssSource


def build_source(source_config: dict, max_items: int):
    typ = source_config.get("type")
    if typ == "rss":
        return RssSource(source_config, max_items)
    if typ == "rest":
        return RestSource(source_config, max_items)
    raise ValueError(f"Unsupported source type: {typ}")


def fetch_all(config: dict) -> tuple[list[NewsItem], list[str]]:
    app = config.get("app", {})
    max_items = int(app.get("max_items_per_source", 50))
    all_items: list[NewsItem] = []
    errors: list[str] = []
    for sc in config.get("sources", []):
        if not sc.get("enabled", True):
            continue
        try:
            source = build_source(sc, max_items)
            items = source.fetch()
            print(f"[source] {sc.get('name')} ok, items={len(items)}")
            all_items.extend(items)
        except Exception as exc:
            msg = f"[source] {sc.get('name')} failed: {type(exc).__name__}: {exc}"
            print(msg)
            errors.append(msg)
    return all_items, errors


def cmd_test_sources(config: dict) -> int:
    ok_count = 0
    for sc in config.get("sources", []):
        if not sc.get("enabled", True):
            continue
        try:
            items = build_source(sc, int(config.get("app", {}).get("max_items_per_source", 50))).fetch()
            print(f"OK   {sc.get('name')} ({sc.get('type')}) count={len(items)} url={sc.get('url')}")
            if items[:1]:
                print(f"     sample: {items[0].title} -> {items[0].url}")
            ok_count += 1
        except Exception as exc:
            print(f"FAIL {sc.get('name')} ({sc.get('type')}): {type(exc).__name__}: {exc}")
    return 0 if ok_count else 1


def cmd_generate(config: dict) -> int:
    items, errors = fetch_all(config)
    state = StateStore(config.get("app", {}).get("state_path", "data/state.json")).load()
    deduped, skipped_pushed = dedupe_items(items, state)
    state.save()
    ranker = LlmRanker(config.get("llm", {}), config.get("filters", {}).get("qa_keywords", []))
    ranked = ranker.rank_items(deduped)
    stats = {
        "source_count": sum(1 for s in config.get("sources", []) if s.get("enabled", True)),
        "raw_count": len(items),
        "deduped_count": len(deduped),
        "skipped_pushed": skipped_pushed,
        "errors": errors,
    }
    ymd, markdown = render_review(ranked, stats, config)
    review_dir = Path(config.get("app", {}).get("review_dir", "review"))
    review_dir.mkdir(parents=True, exist_ok=True)
    out = review_dir / f"{ymd}.md"
    out.write_text(markdown, encoding="utf-8")
    print(f"Generated review file: {out}")
    print("generate 阶段不会推送企业微信，请人工审核后运行 send。")
    return 0


def cmd_test_llm(config: dict) -> int:
    item = NewsItem(
        id="test-llm",
        source="builtin",
        title="LLM 自动生成测试用例的新方法",
        url="https://example.com/llm-test-generation",
        summary="一种基于需求文档和代码变更自动生成测试用例的 Agent 工作流，支持测试覆盖率分析和数据质量校验。",
        content="需求文档、代码变更、测试覆盖率分析、数据质量校验、Agent workflow。",
    )
    ranker = LlmRanker(config.get("llm", {}), config.get("filters", {}).get("qa_keywords", []))
    print(f"模型名: {ranker.model}")
    if not ranker.configured():
        print("LLM 连接是否成功: 否，OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL 未配置或仍是占位符")
        return 1
    result = ranker.rank_one(item)
    parsed = bool(result.summary_cn and result.reason)
    print(f"LLM 连接是否成功: {'是' if not ranker.last_error else '否'}")
    print("返回 JSON:")
    print(json.dumps({
        "keep": result.keep,
        "score": result.llm_score,
        "category": result.category,
        "qa_related": result.qa_related,
        "summary_cn": result.summary_cn,
        "reason": result.reason,
        "action_suggestion": result.action_suggestion,
    }, ensure_ascii=False, indent=2))
    print(f"解析是否成功: {'是' if parsed else '否'}")
    print(f"qa_related 是否为 true: {'是' if result.qa_related else '否'}")
    return 0 if parsed and result.qa_related and result.llm_score >= 8 else 2


def cmd_test_wecom(config: dict) -> int:
    publisher = WeComPublisher(config.get("wecom", {}))
    print(f"Webhook: {mask_url(publisher.webhook_url)}")
    ok, msg = publisher.send_markdown("# 企业微信机器人连通性测试\n这是一条来自 AI 早报 PoC 的测试消息。")
    print(f"企业微信连接是否成功: {'是' if ok else '否'} - {msg}")
    return 0 if ok else 1


def cmd_send(config: dict, file: str) -> int:
    markdown, articles = parse_review_articles(file)
    if not articles:
        print("未从 Markdown 的“推荐推送内容”解析到可推送文章。")
    wecom = config.get("wecom", {})
    mode = wecom.get("mode", "markdown_plus_news")
    publisher = WeComPublisher(wecom)
    markdown_ok = True
    news_ok = True
    sent_any = False
    if mode in {"markdown_only", "markdown_plus_news"} and wecom.get("send_markdown", True):
        markdown_ok, msg = publisher.send_markdown(markdown)
        print(f"markdown send: {'OK' if markdown_ok else 'FAIL'} - {msg}")
        sent_any = sent_any or markdown_ok
        if not markdown_ok:
            return 1
    if mode in {"news_only", "markdown_plus_news"} and wecom.get("send_news", True):
        news_ok, msg = publisher.send_news(articles)
        print(f"news send: {'OK' if news_ok else 'WARN/FAIL'} - {msg}")
        sent_any = sent_any or news_ok
        if mode == "news_only" and not news_ok:
            return 1
    if sent_any and (markdown_ok or mode == "news_only"):
        state = StateStore(config.get("app", {}).get("state_path", "data/state.json")).load()
        state.mark_pushed_articles(articles)
        state.save()
        print(f"已更新 pushed_at，文章数={len(articles)}")
        return 0
    print("发送失败，未更新 pushed_at。")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 早报二次汇总、审核、企业微信推送 PoC")
    parser.add_argument("command", choices=["generate", "send", "test-sources", "test-wecom", "test-llm"])
    parser.add_argument("--file", help="review markdown file for send")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.command == "test-sources":
        return cmd_test_sources(config)
    if args.command == "generate":
        return cmd_generate(config)
    if args.command == "test-llm":
        return cmd_test_llm(config)
    if args.command == "test-wecom":
        return cmd_test_wecom(config)
    if args.command == "send":
        if not args.file:
            parser.error("send requires --file")
        return cmd_send(config, args.file)
    return 1


if __name__ == "__main__":
    sys.exit(main())
