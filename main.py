from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import tz
from dotenv import load_dotenv

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - dependency may be absent before install
    OpenAI = None  # type: ignore


@dataclass
class NewsItem:
    id: str
    source: str
    title: str
    url: str
    summary: str = ""
    content: str = ""
    published_at: str | None = None
    category: str = "unknown"
    image_url: str | None = None
    raw: dict | None = None
    seen: bool = False


@dataclass
class RankedNewsItem:
    item: NewsItem
    rule_score: float
    llm_score: float
    final_score: float
    keep: bool
    category: str
    qa_related: bool
    summary_cn: str
    reason: str
    action_suggestion: str


@dataclass
class ReviewArticle:
    title: str
    url: str
    source: str = ""
    category: str = ""
    rule_score: str = ""
    llm_score: str = ""
    final_score: str = ""
    qa_related: str = ""
    reason: str = ""
    summary: str = ""
    action_suggestion: str = ""
    image_url: str = ""


def mask_secret(value: str | None) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 10:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    load_dotenv()
    text = Path(path).read_text(encoding="utf-8")

    def repl(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), "")

    text = re.sub(r"\$\{([A-Z0-9_]+)\}", repl, text)
    return yaml.safe_load(text) or {}


def now_for_config(config: dict[str, Any]) -> datetime:
    timezone = config.get("app", {}).get("timezone", "Asia/Shanghai")
    return datetime.now(tz.gettz(timezone))


def ensure_parent(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def clean_html(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    soup = BeautifulSoup(text, "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def first_image_from_html(value: str) -> str | None:
    if not value:
        return None
    soup = BeautifulSoup(value, "html.parser")
    img = soup.find("img")
    if img and img.get("src"):
        return str(img.get("src"))
    return None


def canonical_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = "&".join(
        p for p in parts.query.split("&") if p and not p.lower().startswith(("utm_", "spm=", "fbclid=", "gclid="))
    )
    path = parts.path.rstrip("/") or parts.path
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def stable_hash(*parts: str) -> str:
    raw = "|".join(p.strip() for p in parts if p is not None)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def dedupe_key(item: NewsItem) -> str:
    can = canonical_url(item.url)
    if can:
        return stable_hash(can)
    if item.url:
        return stable_hash(item.url)
    if item.title and item.source:
        return stable_hash(item.title, item.source)
    return stable_hash(item.title)


def load_state(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"seen_items": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"WARNING: 状态文件解析失败，将使用空状态: {exc}")
        return {"seen_items": {}}


def save_state(path: str, state: dict[str, Any]) -> None:
    ensure_parent(path)
    Path(path).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_seen(state: dict[str, Any], item: NewsItem, when: str) -> None:
    key = dedupe_key(item)
    seen_items = state.setdefault("seen_items", {})
    seen_items.setdefault(
        key,
        {"title": item.title, "url": item.url, "source": item.source, "first_seen_at": when, "pushed_at": None},
    )


def mark_pushed(state: dict[str, Any], article: ReviewArticle, when: str) -> None:
    key = stable_hash(canonical_url(article.url) or article.url or article.title)
    state.setdefault("seen_items", {}).setdefault(
        key,
        {"title": article.title, "url": article.url, "source": article.source, "first_seen_at": when, "pushed_at": None},
    )["pushed_at"] = when


def is_pushed(state: dict[str, Any], item: NewsItem) -> bool:
    record = state.get("seen_items", {}).get(dedupe_key(item))
    return bool(record and record.get("pushed_at"))


def get_any(data: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def extract_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("items", "results", "articles", "list"):
        if isinstance(payload.get(key), list):
            return payload[key]
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "results", "articles", "list"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def normalize_rest_item(source_name: str, obj: dict[str, Any]) -> NewsItem | None:
    title = clean_html(get_any(obj, ["title", "name", "headline"]))
    url = str(get_any(obj, ["url", "link", "source_url", "original_url"]) or "").strip()
    if not title or not url:
        return None
    summary_raw = get_any(obj, ["summary", "description", "desc", "abstract"])
    content_raw = get_any(obj, ["content", "text", "body"])
    summary = clean_html(summary_raw)
    content = clean_html(content_raw) or summary
    image = get_any(obj, ["image_url", "image", "cover", "cover_url", "thumbnail", "picurl"])
    if isinstance(image, dict):
        image = get_any(image, ["url", "src"])
    published = get_any(obj, ["published_at", "pubDate", "created_at", "updated_at", "date"])
    return NewsItem(
        id=stable_hash(canonical_url(url) or url, title),
        source=source_name,
        title=title,
        url=url,
        summary=summary,
        content=content,
        published_at=str(published) if published else None,
        image_url=str(image) if image else first_image_from_html(str(content_raw or summary_raw or "")),
        raw=obj,
    )


def fetch_rest_source(source: dict[str, Any], max_items: int) -> list[NewsItem]:
    method = str(source.get("method", "GET")).upper()
    response = requests.request(
        method,
        source["url"],
        headers=source.get("headers") or {},
        params=source.get("params") or {},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    rows = extract_list(payload)
    if not rows:
        raise ValueError("REST 响应中未找到可解析的资讯列表，支持 list/items/data/data.items 等结构")
    items: list[NewsItem] = []
    for row in rows[:max_items]:
        if isinstance(row, dict):
            item = normalize_rest_item(source["name"], row)
            if item:
                items.append(item)
    return items


def extract_rss_image(entry: Any) -> str | None:
    for attr in ("media_thumbnail", "media_content"):
        values = getattr(entry, attr, None) or entry.get(attr, []) if hasattr(entry, "get") else []
        if values and isinstance(values, list) and values[0].get("url"):
            return values[0]["url"]
    for link in entry.get("links", []) if hasattr(entry, "get") else []:
        if str(link.get("type", "")).startswith("image") and link.get("href"):
            return link["href"]
    content = ""
    if entry.get("content"):
        content = entry.content[0].get("value", "")
    content = content or entry.get("summary", "") or entry.get("description", "")
    return first_image_from_html(content)


def fetch_rss_source(source: dict[str, Any], max_items: int) -> list[NewsItem]:
    feed = feedparser.parse(source["url"])
    if getattr(feed, "bozo", False) and not feed.entries:
        raise ValueError(f"RSS 解析失败: {getattr(feed, 'bozo_exception', '')}")
    items: list[NewsItem] = []
    for entry in feed.entries[:max_items]:
        title = clean_html(entry.get("title", ""))
        url = str(entry.get("link", "")).strip()
        if not title or not url:
            continue
        summary_raw = entry.get("summary") or entry.get("description") or ""
        content_raw = entry.content[0].get("value", "") if entry.get("content") else summary_raw
        summary = clean_html(summary_raw)
        content = clean_html(content_raw) or summary
        published = entry.get("published") or entry.get("updated")
        items.append(
            NewsItem(
                id=stable_hash(canonical_url(url) or url, title),
                source=source["name"],
                title=title,
                url=url,
                summary=summary,
                content=content,
                published_at=published,
                image_url=extract_rss_image(entry),
                raw=dict(entry),
            )
        )
    return items


def fetch_source(source: dict[str, Any], max_items: int) -> list[NewsItem]:
    if not source.get("enabled", True):
        return []
    stype = source.get("type")
    if stype == "rss":
        return fetch_rss_source(source, max_items)
    if stype == "rest":
        return fetch_rest_source(source, max_items)
    raise ValueError(f"不支持的 source type: {stype}")


def fetch_all(config: dict[str, Any]) -> tuple[list[NewsItem], list[tuple[str, str]]]:
    max_items = int(config.get("app", {}).get("max_items_per_source", 50))
    all_items: list[NewsItem] = []
    errors: list[tuple[str, str]] = []
    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue
        try:
            items = fetch_source(source, max_items)
            print(f"OK source={source.get('name')} type={source.get('type')} items={len(items)}")
            all_items.extend(items)
        except Exception as exc:
            msg = str(exc)
            print(f"ERROR source={source.get('name')} type={source.get('type')} reason={msg}")
            errors.append((source.get("name", "unknown"), msg))
    return all_items, errors


def unique_unpushed(items: list[NewsItem], state: dict[str, Any]) -> list[NewsItem]:
    result: list[NewsItem] = []
    seen: set[str] = set()
    for item in items:
        key = dedupe_key(item)
        if key in seen or is_pushed(state, item):
            continue
        if key in state.get("seen_items", {}):
            item.seen = True
        seen.add(key)
        result.append(item)
    return result


def contains_any(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(k.lower() in lower for k in keywords)


def rule_score_item(item: NewsItem, config: dict[str, Any]) -> tuple[float, bool]:
    text = f"{item.title} {item.summary} {item.content}".lower()
    score = 3.0
    groups = [
        (["ai coding", "codex", "claude code", "opencode", "cursor", "kiro"], 3),
        (["agent", "mcp", "tool calling", "workflow", "memory"], 2),
        (["dbt", "dsl", "data quality", "数据质量", "大数据测试"], 2),
        (["testing", "qa", "测试", "测试用例", "测试自动化", "需求评审"], 3),
        (["模型发布", "benchmark", "推理模型", "多模态"], 1),
    ]
    for keywords, points in groups:
        if any(k in text for k in keywords):
            score += points
    if any(k in text for k in ["融资", "广告", "赞助", "限时优惠", "marketing", "sponsored"]):
        score -= 2
    if not item.url or len(item.title) < 6:
        score -= 1
    qa_keywords = config.get("filters", {}).get("qa_keywords", [])
    qa_related = contains_any(text, qa_keywords)
    return max(1.0, min(10.0, score)), qa_related


def fallback_rank(item: NewsItem, rule_score: float, qa_related: bool, reason: str) -> RankedNewsItem:
    summary = clean_html(item.summary or item.content or item.title)[:100]
    return RankedNewsItem(
        item=item,
        rule_score=round(rule_score, 1),
        llm_score=round(rule_score, 1),
        final_score=round(rule_score, 1),
        keep=rule_score >= 6,
        category="Testing" if qa_related else "Other",
        qa_related=qa_related,
        summary_cn=summary,
        reason=reason,
        action_suggestion="可人工判断其对测试工程、大数据或 AI Coding 工作流的参考价值。",
    )


def llm_prompt(item: NewsItem) -> str:
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
  "score": 8,
  "category": "AI Coding / Agent / Model / Data Engineering / Testing / Product / Other",
  "qa_related": true,
  "summary_cn": "不超过100字中文摘要",
  "reason": "推荐或不推荐的原因",
  "action_suggestion": "这条资讯对测试工程师/大数据/AI Coding 使用者有什么参考价值"
}}

资讯内容：
标题：{item.title}
来源：{item.source}
原始摘要：{item.summary[:1200]}
正文片段：{item.content[:1800]}
链接：{item.url}
"""


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.S)
    if fence:
        cleaned = fence.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def call_llm(item: NewsItem, config: dict[str, Any]) -> dict[str, Any]:
    llm = config.get("llm", {})
    if OpenAI is None:
        raise RuntimeError("openai 依赖不可用，请先 pip install -r requirements.txt")
    client = OpenAI(api_key=llm.get("api_key"), base_url=llm.get("base_url"), timeout=float(llm.get("timeout_seconds", 60)))
    kwargs = {
        "model": llm.get("model"),
        "messages": [{"role": "user", "content": llm_prompt(item)}],
        "temperature": float(llm.get("temperature", 0.2)),
    }
    try:
        response = client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
    except Exception:
        response = client.chat.completions.create(**kwargs)
    text = response.choices[0].message.content or ""
    return extract_json_object(text)


def rank_items_with_llm(items: list[NewsItem], config: dict[str, Any]) -> list[RankedNewsItem]:
    llm = config.get("llm", {})
    enabled = bool(llm.get("enabled", True) and llm.get("api_key") and llm.get("base_url") and llm.get("model"))
    rw = float(llm.get("rule_score_weight", 0.4))
    lw = float(llm.get("llm_score_weight", 0.6))
    ranked: list[RankedNewsItem] = []
    for item in items:
        rule_score, rule_qa = rule_score_item(item, config)
        if not enabled:
            ranked.append(fallback_rank(item, rule_score, rule_qa, "LLM 不可用或未配置，使用规则评分兜底。"))
            continue
        try:
            data = call_llm(item, config)
            llm_score = max(1.0, min(10.0, float(data.get("score", rule_score))))
            final = rule_score * rw + llm_score * lw
            qa_related = bool(data.get("qa_related", rule_qa)) or rule_qa
            ranked.append(
                RankedNewsItem(
                    item=item,
                    rule_score=round(rule_score, 1),
                    llm_score=round(llm_score, 1),
                    final_score=round(final, 1),
                    keep=bool(data.get("keep", llm_score >= 6)) and final >= 5.5,
                    category=str(data.get("category") or ("Testing" if qa_related else "Other")),
                    qa_related=qa_related,
                    summary_cn=clean_html(data.get("summary_cn") or item.summary or item.title)[:100],
                    reason=clean_html(data.get("reason") or "LLM 未返回 reason，使用默认推荐理由。"),
                    action_suggestion=clean_html(data.get("action_suggestion") or "可人工判断其参考价值。"),
                )
            )
        except Exception as exc:
            print(f"WARNING: LLM 评分失败 item={item.title[:40]!r} reason={exc}; 使用规则评分兜底")
            ranked.append(fallback_rank(item, rule_score, rule_qa, "LLM 调用或 JSON 解析失败，使用规则评分兜底。"))
    return ranked


def select_recommendations(ranked: list[RankedNewsItem], config: dict[str, Any]) -> tuple[list[RankedNewsItem], list[RankedNewsItem], list[RankedNewsItem]]:
    top_n = int(config.get("app", {}).get("final_top_n", 8))
    sorted_items = sorted(ranked, key=lambda x: (x.qa_related, x.keep, x.final_score), reverse=True)
    recommended = [x for x in sorted_items if x.keep][:top_n]
    if config.get("app", {}).get("require_qa_related", True) and not any(x.qa_related for x in recommended):
        qa_candidates = [x for x in sorted_items if x.qa_related]
        if qa_candidates:
            candidate = qa_candidates[0]
            recommended = [candidate] + [x for x in recommended if x.item.id != candidate.item.id]
            recommended = recommended[:top_n]
    rec_ids = {x.item.id for x in recommended}
    filtered = [x for x in sorted(ranked, key=lambda x: x.final_score, reverse=True) if x.item.id not in rec_ids]
    closest_qa = [x for x in sorted_items if x.qa_related][:3]
    if not closest_qa:
        closest_qa = sorted(ranked, key=lambda x: x.rule_score, reverse=True)[:3]
    return recommended, filtered, closest_qa


def yn(value: bool | str) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    return "是" if str(value).strip().lower() in {"true", "yes", "是", "1"} else "否"


def render_item_md(item: RankedNewsItem, index: int | None, filtered: bool = False) -> str:
    title = f"### {index}. {item.item.title}" if index is not None else f"### {item.item.title}"
    lines = [title, ""]
    lines.extend(
        [
            f"- 来源：{item.item.source}",
            f"- 分类：{item.category}",
            f"- 规则分 rule_score：{item.rule_score}",
            f"- LLM 分 llm_score：{item.llm_score}",
            f"- 最终分 final_score：{item.final_score}",
            f"- 是否测试工程师相关 qa_related：{yn(item.qa_related)}",
        ]
    )
    if filtered:
        lines.append(f"- 过滤原因：keep={item.keep}，最终分 {item.final_score}")
    else:
        lines.append(f"- 推荐理由：{item.reason}")
    lines.extend(
        [
            f"- 摘要：{item.summary_cn}",
            f"- 对我的参考价值：{item.action_suggestion}",
            f"- 原文链接：{item.item.url}",
        ]
    )
    if item.item.image_url:
        lines.append(f"- 图片链接 image_url：{item.item.image_url}")
    lines.append("\n---\n")
    return "\n".join(lines)


def render_review(config: dict[str, Any], ranked: list[RankedNewsItem], raw_count: int, dedup_count: int, errors: list[tuple[str, str]]) -> Path:
    recommended, filtered, closest_qa = select_recommendations(ranked, config)
    today = now_for_config(config).strftime("%Y-%m-%d")
    review_dir = Path(config.get("app", {}).get("review_dir", "review"))
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / f"{today.replace('-', '')}.md"
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
        f"- 采集来源数：{len([s for s in config.get('sources', []) if s.get('enabled', True)])}",
        f"- 原始资讯数：{raw_count}",
        f"- 去重后资讯数：{dedup_count}",
        f"- 推荐区数量：{len(recommended)}",
        f"- qa_related 数量：{qa_count}",
        f"- LLM 是否启用：{yn(bool(config.get('llm', {}).get('enabled', True)))}",
        f"- LLM 模型：{config.get('llm', {}).get('model', '')}",
        f"- 企业微信推送模式：{config.get('wecom', {}).get('mode', 'markdown_plus_news')}",
    ]
    if errors:
        lines.extend(["", "### Source 警告", ""] + [f"- {name}: {msg}" for name, msg in errors])
    lines.extend(["", "## 推荐推送内容", ""])
    for i, item in enumerate(recommended, 1):
        lines.append(render_item_md(item, i))
    if qa_count == 0:
        lines.extend([
            "## 测试工程师相关内容缺失提醒",
            "",
            "今天没有找到强相关的测试工程师内容。",
            "以下是相对最接近的候选内容：",
            "",
        ])
        for item in closest_qa:
            lines.extend([f"- {item.item.title}（final_score={item.final_score}，url={item.item.url}）"])
        lines.append("")
    lines.extend(["## 被过滤但可人工恢复的内容", ""])
    for item in filtered[: max(20, len(filtered))]:
        lines.append(render_item_md(item, None, filtered=True))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def split_markdown(content: str, max_chars: int) -> list[str]:
    if len(content) <= max_chars:
        return [content]
    chunks: list[str] = []
    current = ""
    for part in re.split(r"(\n---\n|\n## )", content):
        if not part:
            continue
        if len(current) + len(part) <= max_chars:
            current += part
        else:
            if current:
                chunks.append(current.strip())
            current = part
            while len(current) > max_chars:
                chunks.append(current[:max_chars].strip())
                current = current[max_chars:]
    if current.strip():
        chunks.append(current.strip())
    return chunks


def wecom_post(webhook: str, payload: dict[str, Any]) -> tuple[bool, str]:
    if not webhook:
        return False, "WECOM_WEBHOOK_URL 未配置"
    response = requests.post(webhook, json=payload, timeout=20)
    try:
        data = response.json()
    except Exception:
        return False, f"HTTP {response.status_code}: {response.text[:200]}"
    ok = response.ok and data.get("errcode") == 0
    return ok, json.dumps(data, ensure_ascii=False)


def send_markdown(webhook: str, content: str, max_chars: int) -> bool:
    chunks = split_markdown(content, max_chars)
    for i, chunk in enumerate(chunks, 1):
        prefix = f"（分片 {i}/{len(chunks)}）\n" if len(chunks) > 1 else ""
        ok, msg = wecom_post(webhook, {"msgtype": "markdown", "markdown": {"content": prefix + chunk}})
        if not ok:
            print(f"ERROR: 企业微信 Markdown 分片 {i}/{len(chunks)} 发送失败: {msg}")
            return False
        print(f"OK: 企业微信 Markdown 分片 {i}/{len(chunks)} 发送成功")
    return True


def truncate(text: str, max_chars: int) -> str:
    text = clean_html(text)
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def build_news_articles(articles: list[ReviewArticle], config: dict[str, Any]) -> list[dict[str, str]]:
    wecom = config.get("wecom", {})
    top_n = int(wecom.get("news_top_n", 3))
    max_desc = int(wecom.get("news_description_max_chars", 120))
    default_picurl = wecom.get("default_picurl", "")
    result: list[dict[str, str]] = []
    for article in articles:
        if not article.title or not article.url:
            continue
        qa = "测试相关" if yn(article.qa_related) == "是" else "非测试相关"
        desc_source = article.action_suggestion or article.summary or article.reason
        desc = truncate(f"评分 {article.final_score or '-'}｜{qa}｜{desc_source}", max_desc)
        payload = {"title": truncate(article.title, 64), "description": desc, "url": article.url}
        picurl = article.image_url or default_picurl
        if picurl:
            payload["picurl"] = picurl
        result.append(payload)
        if len(result) >= top_n:
            break
    return result


def send_news(webhook: str, articles: list[ReviewArticle], config: dict[str, Any]) -> bool:
    news_articles = build_news_articles(articles, config)
    if not news_articles:
        print("WARNING: 未解析到可用于 News 图文卡片的文章")
        return False
    ok, msg = wecom_post(webhook, {"msgtype": "news", "news": {"articles": news_articles}})
    if ok:
        print(f"OK: 企业微信 News 图文卡片发送成功 articles={len(news_articles)}")
        return True
    print(f"WARNING: 企业微信 News 图文卡片发送失败: {msg}")
    return False


def parse_field(block: str, names: list[str]) -> str:
    for name in names:
        m = re.search(rf"^-\s*{re.escape(name)}\s*[：:]\s*(.*)$", block, flags=re.M)
        if m:
            return m.group(1).strip()
    return ""


def parse_review_articles(markdown: str) -> list[ReviewArticle]:
    start = markdown.find("## 推荐推送内容")
    if start < 0:
        return []
    end_candidates = [i for marker in ["## 测试工程师相关内容缺失提醒", "## 被过滤但可人工恢复的内容"] if (i := markdown.find(marker, start + 1)) >= 0]
    end = min(end_candidates) if end_candidates else len(markdown)
    section = markdown[start:end]
    blocks = re.split(r"(?m)^###\s+", section)
    articles: list[ReviewArticle] = []
    for block in blocks[1:]:
        lines = block.strip().splitlines()
        if not lines:
            continue
        title = re.sub(r"^\d+\.\s*", "", lines[0]).strip()
        body = "\n".join(lines[1:])
        url = parse_field(body, ["原文链接"])
        if not title or not url:
            continue
        articles.append(
            ReviewArticle(
                title=title,
                url=url,
                source=parse_field(body, ["来源"]),
                category=parse_field(body, ["分类"]),
                rule_score=parse_field(body, ["规则分 rule_score", "规则分"]),
                llm_score=parse_field(body, ["LLM 分 llm_score", "LLM 分"]),
                final_score=parse_field(body, ["最终分 final_score", "最终分"]),
                qa_related=parse_field(body, ["是否测试工程师相关 qa_related", "是否测试工程师相关"]),
                reason=parse_field(body, ["推荐理由", "过滤原因"]),
                summary=parse_field(body, ["摘要"]),
                action_suggestion=parse_field(body, ["对我的参考价值"]),
                image_url=parse_field(body, ["图片链接 image_url", "图片链接"]),
            )
        )
    return articles


def command_test_sources(config: dict[str, Any]) -> int:
    ok = True
    max_items = int(config.get("app", {}).get("max_items_per_source", 50))
    for source in config.get("sources", []):
        if not source.get("enabled", True):
            print(f"SKIP source={source.get('name')} disabled")
            continue
        try:
            items = fetch_source(source, max_items)
            print(f"OK source={source.get('name')} type={source.get('type')} url={source.get('url')} items={len(items)}")
            if items[:1]:
                print(f"  sample: {items[0].title[:80]} -> {items[0].url}")
        except Exception as exc:
            ok = False
            print(f"ERROR source={source.get('name')} type={source.get('type')} url={source.get('url')} reason={exc}")
    return 0 if ok else 1


def command_test_llm(config: dict[str, Any]) -> int:
    model = config.get("llm", {}).get("model", "")
    print(f"模型名: {model}")
    print("API key: <hidden>")
    item = NewsItem(
        id="test-llm",
        source="builtin",
        title="LLM 自动生成测试用例的新方法",
        url="https://example.com/llm-test-generation",
        summary="一种基于需求文档和代码变更自动生成测试用例的 Agent 工作流，支持测试覆盖率分析和数据质量校验。",
        content="一种基于需求文档和代码变更自动生成测试用例的 Agent 工作流，支持测试覆盖率分析和数据质量校验。",
    )
    try:
        data = call_llm(item, config)
        parsed = isinstance(data, dict)
        print("LLM 连接是否成功: 是")
        print(f"返回 JSON: {json.dumps(data, ensure_ascii=False, indent=2)}")
        print(f"解析是否成功: {yn(parsed)}")
        print(f"qa_related 是否为 true: {yn(bool(data.get('qa_related')))}")
        expected = bool(data.get("qa_related")) and float(data.get("score", 0)) >= 8
        return 0 if expected else 1
    except Exception as exc:
        print("LLM 连接是否成功: 否")
        print(f"解析是否成功: 否，原因: {exc}")
        return 1


def command_generate(config: dict[str, Any]) -> int:
    state_path = config.get("app", {}).get("state_path", "data/state.json")
    state = load_state(state_path)
    items, errors = fetch_all(config)
    raw_count = len(items)
    unique_items = unique_unpushed(items, state)
    ranked = rank_items_with_llm(unique_items, config)
    path = render_review(config, ranked, raw_count, len(unique_items), errors)
    when = now_for_config(config).isoformat()
    for item in unique_items:
        mark_seen(state, item, when)
    save_state(state_path, state)
    print(f"OK: 已生成 Markdown 人工审核稿，不会自动推送: {path}")
    return 0


def command_send(config: dict[str, Any], file_path: str) -> int:
    content = Path(file_path).read_text(encoding="utf-8")
    articles = parse_review_articles(content)
    wecom = config.get("wecom", {})
    webhook = wecom.get("webhook_url", "")
    print(f"企业微信 webhook: {mask_secret(webhook)}")
    mode = wecom.get("mode", "markdown_plus_news")
    send_md = mode in {"markdown_only", "markdown_plus_news"} and bool(wecom.get("send_markdown", True))
    send_n = mode in {"news_only", "markdown_plus_news"} and bool(wecom.get("send_news", True))
    md_ok = True
    news_ok = True
    if send_md:
        md_ok = send_markdown(webhook, content, int(wecom.get("markdown_chunk_max_chars", 1800)))
        if not md_ok:
            return 1
    if send_n:
        news_ok = send_news(webhook, articles, config)
        if not news_ok and mode == "news_only":
            return 1
    if md_ok and (news_ok or mode == "markdown_plus_news"):
        state_path = config.get("app", {}).get("state_path", "data/state.json")
        state = load_state(state_path)
        when = now_for_config(config).isoformat()
        for article in articles:
            mark_pushed(state, article, when)
        save_state(state_path, state)
        print(f"OK: 推送流程完成，已更新 pushed_at，文章数={len(articles)}")
    return 0


def command_test_wecom(config: dict[str, Any]) -> int:
    wecom = config.get("wecom", {})
    webhook = wecom.get("webhook_url", "")
    print(f"企业微信 webhook: {mask_secret(webhook)}")
    content = f"# AI 早报机器人连通性测试\n\n时间：{now_for_config(config).strftime('%Y-%m-%d %H:%M:%S')}\n\n这是一条测试消息。"
    ok = send_markdown(webhook, content, int(wecom.get("markdown_chunk_max_chars", 1800)))
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 早报二次汇总、LLM 评分、人工审核、企业微信推送 PoC")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate")
    send_parser = sub.add_parser("send")
    send_parser.add_argument("--file", required=True)
    sub.add_parser("test-sources")
    sub.add_parser("test-wecom")
    sub.add_parser("test-llm")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.command == "test-sources":
        return command_test_sources(config)
    if args.command == "test-llm":
        return command_test_llm(config)
    if args.command == "generate":
        return command_generate(config)
    if args.command == "send":
        return command_send(config, args.file)
    if args.command == "test-wecom":
        return command_test_wecom(config)
    return 2


if __name__ == "__main__":
    sys.exit(main())
