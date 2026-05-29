from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.core.dedupe import dedupe_items
from src.core.llm_ranker import rank_items_with_llm, rank_one_with_llm
from src.core.normalize import load_config, mask_secret
from src.core.render_markdown import render_review_markdown
from src.core.review_parser import parse_recommended_articles
from src.core.state import JsonState
from src.models import NewsItem
from src.publishers.wecom import WeComPublisher, safe_webhook_label
from src.sources.base import fetch_source


def enabled_sources(config: dict) -> list[dict]:
    return [s for s in config.get("sources", []) if s.get("enabled", True)]


def collect_items(config: dict) -> tuple[list[NewsItem], list[str]]:
    max_items = int(config.get("app", {}).get("max_items_per_source", 50))
    items: list[NewsItem] = []
    errors: list[str] = []
    for source in enabled_sources(config):
        try:
            got = fetch_source(source, max_items)
            print(f"OK source={source.get('name')} type={source.get('type')} items={len(got)}")
            items.extend(got)
        except Exception as exc:
            msg = f"ERROR source={source.get('name')} type={source.get('type')}: {type(exc).__name__}: {exc}"
            print(msg)
            errors.append(msg)
    return items, errors


def cmd_test_sources(config: dict) -> int:
    items, errors = collect_items(config)
    print(f"采集完成：items={len(items)} errors={len(errors)}")
    return 0 if items else 1


def cmd_generate(config: dict) -> int:
    state = JsonState(config.get("app", {}).get("state_path", "data/state.json"))
    raw_items, _ = collect_items(config)
    deduped = dedupe_items(raw_items)
    candidates: list[NewsItem] = []
    for item in deduped:
        item.seen = item.id in state.data.get("seen_items", {})
        if state.is_pushed(item):
            continue
        state.mark_seen(item)
        candidates.append(item)
    state.save()
    ranked = rank_items_with_llm(candidates, config.get("llm", {}), config.get("filters", {}))
    stats = {"source_count": len(enabled_sources(config)), "raw_count": len(raw_items), "deduped_count": len(deduped)}
    path = render_review_markdown(ranked, stats, config)
    print(f"已生成 Markdown 人工审核稿：{path}")
    print("generate 阶段不会推送企业微信。请人工审核后运行 send 命令。")
    return 0


def cmd_test_llm(config: dict) -> int:
    item = NewsItem(
        id="test-llm",
        source="builtin_test",
        title="LLM 自动生成测试用例的新方法",
        url="https://example.com/llm-test-generation",
        summary="一种基于需求文档和代码变更自动生成测试用例的 Agent 工作流，支持测试覆盖率分析和数据质量校验。",
        content="一种基于需求文档和代码变更自动生成测试用例的 Agent 工作流，支持测试覆盖率分析和数据质量校验。",
    )
    ranked, parsed, error = rank_one_with_llm(
        item,
        config.get("llm", {}),
        {"rule": float(config.get("llm", {}).get("rule_score_weight", 0.4)), "llm": float(config.get("llm", {}).get("llm_score_weight", 0.6))},
        config.get("filters", {}).get("qa_keywords") or [],
    )
    success = parsed is not None and error is None
    print(f"LLM 连接是否成功：{'是' if success else '否'}")
    print(f"模型名：{config.get('llm', {}).get('model', '')}")
    print(f"返回 JSON：{json.dumps(parsed, ensure_ascii=False) if parsed else '{}'}")
    print(f"解析是否成功：{'是' if parsed else '否'}")
    print(f"qa_related 是否为 true：{'是' if ranked.qa_related else '否'}")
    if error:
        print(f"错误（不含 API key）：{type(error).__name__ if not isinstance(error, str) else error[:200]}")
    return 0 if success and ranked.qa_related and ranked.llm_score >= 8 else 1


def cmd_test_wecom(config: dict) -> int:
    cfg = config.get("wecom", {})
    print(f"Webhook：{safe_webhook_label(cfg.get('webhook_url'))}")
    publisher = WeComPublisher(cfg.get("webhook_url", ""))
    ok, messages = publisher.send_markdown("# AI 早报机器人测试\n这是一条企业微信 Markdown 测试消息。", int(cfg.get("markdown_chunk_max_chars", 1800)))
    print("\n".join(messages))
    return 0 if ok else 1


def cmd_send(config: dict, file_path: str) -> int:
    path = Path(file_path)
    if not path.exists():
        print(f"审核稿不存在：{path}")
        return 1
    markdown = path.read_text(encoding="utf-8")
    articles = parse_recommended_articles(markdown)
    cfg = config.get("wecom", {})
    mode = cfg.get("mode", "markdown_plus_news")
    send_markdown = bool(cfg.get("send_markdown", True)) and mode in ("markdown_only", "markdown_plus_news")
    send_news = bool(cfg.get("send_news", True)) and mode in ("news_only", "markdown_plus_news")
    publisher = WeComPublisher(cfg.get("webhook_url", ""))
    print(f"推送模式：{mode}，Webhook：{mask_secret(cfg.get('webhook_url'), 12)}")
    markdown_ok = True
    news_ok = True
    if send_markdown:
        markdown_ok, messages = publisher.send_markdown(markdown, int(cfg.get("markdown_chunk_max_chars", 1800)))
        print("\n".join(messages))
        if not markdown_ok:
            print("Markdown 推送失败，不更新 pushed_at。")
            return 1
    if send_news:
        news_ok, msg = publisher.send_news(articles, cfg)
        print(f"news: {msg}")
        if not news_ok and mode == "news_only":
            print("news_only 模式推送失败，不更新 pushed_at。")
            return 1
        if not news_ok:
            print("WARNING: News 推送失败；Markdown 如已发送不会重复发送。")
    if markdown_ok and (news_ok or mode == "markdown_plus_news"):
        state = JsonState(config.get("app", {}).get("state_path", "data/state.json"))
        for article in articles:
            state.mark_pushed(article.title, article.url, article.source or "review")
        state.save()
        print(f"已更新 pushed_at：{len(articles)} 篇")
    return 0 if markdown_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 早报二次汇总、审核、企业微信推送 PoC")
    parser.add_argument("command", choices=["generate", "send", "test-sources", "test-wecom", "test-llm"])
    parser.add_argument("--file", help="send 命令读取的 review Markdown 文件")
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
            print("send 命令必须指定 --file review/YYYYMMDD.md")
            return 1
        return cmd_send(config, args.file)
    return 1


if __name__ == "__main__":
    sys.exit(main())
