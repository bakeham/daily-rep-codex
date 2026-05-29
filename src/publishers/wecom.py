from __future__ import annotations

from typing import Any

import requests

from src.core.utils import truncate
from src.models import ReviewArticle


class WeComPublisher:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.webhook_url = config.get("webhook_url") or ""
        self.timeout = 20

    def configured(self) -> bool:
        return bool(self.webhook_url and "${" not in self.webhook_url and "your_key_here" not in self.webhook_url)

    def send_markdown(self, markdown: str) -> tuple[bool, str]:
        chunks = split_markdown(markdown, int(self.config.get("markdown_chunk_max_chars", 1800)))
        for i, chunk in enumerate(chunks, 1):
            ok, msg = self._post({"msgtype": "markdown", "markdown": {"content": chunk}})
            if not ok:
                return False, f"markdown 分片 {i}/{len(chunks)} 发送失败: {msg}"
        return True, f"markdown 已发送 {len(chunks)} 个分片"

    def send_news(self, articles: list[ReviewArticle]) -> tuple[bool, str]:
        top_n = int(self.config.get("news_top_n", 3))
        max_desc = int(self.config.get("news_description_max_chars", 120))
        default_pic = self.config.get("default_picurl", "")
        cards = []
        for article in articles[:top_n]:
            desc_seed = article.action_suggestion or article.summary or article.reason
            qa_text = "测试相关" if article.qa_related else "非测试相关"
            score = f"{article.final_score:.1f}" if article.final_score is not None else "-"
            card = {
                "title": truncate(article.title, 64),
                "description": truncate(f"评分 {score}｜{qa_text}｜{desc_seed}", max_desc),
                "url": article.url,
            }
            pic = article.image_url or default_pic
            if pic:
                card["picurl"] = pic
            cards.append(card)
        if not cards:
            return False, "没有可发送的 news articles"
        return self._post({"msgtype": "news", "news": {"articles": cards}})

    def _post(self, payload: dict[str, Any]) -> tuple[bool, str]:
        if not self.configured():
            return False, "企业微信 webhook 未配置或仍是占位符"
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=self.timeout)
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            if resp.ok and data.get("errcode") == 0:
                return True, "ok"
            return False, f"HTTP {resp.status_code}, errcode={data.get('errcode')}, errmsg={data.get('errmsg')}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"


def split_markdown(markdown: str, max_chars: int) -> list[str]:
    if len(markdown) <= max_chars:
        return [markdown]
    chunks: list[str] = []
    current = ""
    for part in markdown.split("\n---\n"):
        candidate = part if not current else current + "\n---\n" + part
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(part) <= max_chars:
            current = part
        else:
            current = ""
            for i in range(0, len(part), max_chars):
                chunks.append(part[i : i + max_chars])
    if current:
        chunks.append(current)
    return chunks
