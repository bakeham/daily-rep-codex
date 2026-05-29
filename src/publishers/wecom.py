from __future__ import annotations

from typing import Iterable

import requests

from src.core.normalize import mask_secret
from src.core.review_parser import ReviewArticle


def chunk_markdown(markdown: str, max_chars: int) -> list[str]:
    if len(markdown) <= max_chars:
        return [markdown]
    chunks: list[str] = []
    current = ""
    for part in markdown.split("\n---\n"):
        candidate = f"{current}\n---\n{part}" if current else part
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(part) <= max_chars:
                current = part
            else:
                chunks.extend(part[i:i + max_chars] for i in range(0, len(part), max_chars))
                current = ""
    if current:
        chunks.append(current)
    return chunks


class WeComPublisher:
    def __init__(self, webhook_url: str, timeout: int = 20):
        self.webhook_url = webhook_url
        self.timeout = timeout

    def _post(self, payload: dict) -> tuple[bool, str]:
        if not self.webhook_url or "${" in self.webhook_url:
            return False, "WECOM_WEBHOOK_URL 未配置"
        response = requests.post(self.webhook_url, json=payload, timeout=self.timeout)
        try:
            data = response.json()
        except ValueError:
            return False, f"企业微信返回非 JSON，HTTP {response.status_code}"
        ok = response.ok and data.get("errcode") == 0
        return ok, data.get("errmsg") or str(data)

    def send_markdown(self, markdown: str, max_chars: int = 1800) -> tuple[bool, list[str]]:
        messages: list[str] = []
        for idx, chunk in enumerate(chunk_markdown(markdown, max_chars), 1):
            ok, msg = self._post({"msgtype": "markdown", "markdown": {"content": chunk}})
            messages.append(f"markdown 分片 {idx}: {msg}")
            if not ok:
                return False, messages
        return True, messages

    def send_news(self, articles: Iterable[ReviewArticle], cfg: dict) -> tuple[bool, str]:
        max_n = int(cfg.get("news_top_n", 3))
        max_desc = int(cfg.get("news_description_max_chars", 120))
        default_picurl = cfg.get("default_picurl", "")
        cards = []
        for article in list(articles)[:max_n]:
            desc_source = article.action_suggestion or article.summary or article.reason
            desc = f"评分 {article.final_score:.1f}｜{'测试相关' if article.qa_related else '非测试相关'}｜{desc_source}"
            card = {"title": article.title[:60], "description": desc[:max_desc], "url": article.url}
            if default_picurl:
                card["picurl"] = default_picurl
            cards.append(card)
        if not cards:
            return False, "没有可发送的 news article（标题和 URL 必须存在）"
        return self._post({"msgtype": "news", "news": {"articles": cards}})


def safe_webhook_label(webhook_url: str | None) -> str:
    return mask_secret(webhook_url, 12)
