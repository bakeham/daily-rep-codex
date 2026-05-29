from __future__ import annotations

from typing import Any

import requests

from src.core.review_parser import ReviewArticle
from src.core.utils import mask_url


def truncate(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


class WeComPublisher:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.webhook_url = str(config.get("webhook_url") or "")
        self.mode = str(config.get("mode") or "markdown_plus_news")
        self.chunk_max = int(config.get("markdown_chunk_max_chars", 1800))
        self.news_top_n = int(config.get("news_top_n", 3))
        self.default_picurl = str(config.get("default_picurl") or "")
        self.news_desc_max = int(config.get("news_description_max_chars", 120))

    def _ensure_webhook(self) -> None:
        if not self.webhook_url or self.webhook_url.startswith("${"):
            raise RuntimeError("WECOM_WEBHOOK_URL is not configured")

    def _post(self, payload: dict[str, Any]) -> tuple[bool, str]:
        try:
            self._ensure_webhook()
            resp = requests.post(self.webhook_url, json=payload, timeout=20)
            data = resp.json() if resp.content else {}
            ok = resp.ok and data.get("errcode") == 0
            return ok, data.get("errmsg") or resp.text[:200]
        except Exception as exc:
            return False, str(exc)

    def split_markdown(self, markdown: str) -> list[str]:
        if len(markdown) <= self.chunk_max:
            return [markdown]
        chunks: list[str] = []
        current = ""
        for part in markdown.split("\n---\n"):
            sep_part = part if not current else "\n---\n" + part
            if len(current) + len(sep_part) <= self.chunk_max:
                current += sep_part
            else:
                if current:
                    chunks.append(current)
                if len(part) <= self.chunk_max:
                    current = part
                else:
                    current = ""
                    for i in range(0, len(part), self.chunk_max):
                        chunks.append(part[i : i + self.chunk_max])
        if current:
            chunks.append(current)
        return chunks

    def send_markdown(self, markdown: str) -> tuple[bool, str]:
        chunks = self.split_markdown(markdown)
        for idx, chunk in enumerate(chunks, 1):
            prefix = f"（{idx}/{len(chunks)}）\n" if len(chunks) > 1 else ""
            ok, msg = self._post({"msgtype": "markdown", "markdown": {"content": prefix + chunk}})
            if not ok:
                return False, f"markdown chunk {idx}/{len(chunks)} failed via {mask_url(self.webhook_url)}: {msg}"
        return True, f"markdown sent in {len(chunks)} chunk(s)"

    def build_news_articles(self, articles: list[ReviewArticle]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for article in articles[: self.news_top_n]:
            qa_label = "测试相关" if article.qa_related else "非测试相关"
            reference = article.action_suggestion or article.summary or article.reason
            description = truncate(f"评分 {article.final_score:.1f}｜{qa_label}｜{reference}", self.news_desc_max)
            payload = {
                "title": truncate(article.title, 60),
                "description": description,
                "url": article.url,
            }
            picurl = article.image_url or self.default_picurl
            if picurl:
                payload["picurl"] = picurl
            result.append(payload)
        return result

    def send_news(self, articles: list[ReviewArticle]) -> tuple[bool, str]:
        news_articles = self.build_news_articles(articles)
        if not news_articles:
            return False, "no valid articles parsed from review markdown"
        ok, msg = self._post({"msgtype": "news", "news": {"articles": news_articles}})
        return ok, msg

    def send(self, markdown: str, articles: list[ReviewArticle]) -> tuple[bool, bool, list[str]]:
        messages: list[str] = []
        send_markdown = self.mode in {"markdown_only", "markdown_plus_news"} and bool(self.config.get("send_markdown", True))
        send_news = self.mode in {"news_only", "markdown_plus_news"} and bool(self.config.get("send_news", True))
        markdown_ok = True
        news_ok = True
        if send_markdown:
            markdown_ok, msg = self.send_markdown(markdown)
            messages.append(msg)
            if not markdown_ok:
                return False, False, messages
        if send_news:
            news_ok, msg = self.send_news(articles)
            messages.append(("WARNING: " if not news_ok and markdown_ok else "") + msg)
        if self.mode not in {"markdown_only", "news_only", "markdown_plus_news"}:
            return False, False, messages + [f"unsupported wecom mode: {self.mode}"]
        overall = (markdown_ok and news_ok) if self.mode == "news_only" else markdown_ok
        if self.mode == "markdown_plus_news":
            overall = markdown_ok
        return overall, news_ok, messages
