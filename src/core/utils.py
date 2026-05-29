from __future__ import annotations

import hashlib
import os
import re
from string import Template
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv


def clean_html(value: Any, max_chars: int | None = None) -> str:
    if value is None:
        return ""
    text = str(value)
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    cleaned = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    if max_chars and len(cleaned) > max_chars:
        return cleaned[: max_chars - 1].rstrip() + "…"
    return cleaned


def first_image_from_html(value: str | None) -> str | None:
    if not value:
        return None
    soup = BeautifulSoup(value, "html.parser")
    img = soup.find("img")
    if not img:
        return None
    src = img.get("src") or img.get("data-src")
    return str(src).strip() if src else None


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def canonicalize_url(url: str | None) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))
    except Exception:
        return url.strip()


def item_dedupe_key(title: str, url: str, source: str = "") -> str:
    canonical = canonicalize_url(url)
    if canonical:
        return stable_hash(canonical)
    if title and source:
        return stable_hash(f"{title.strip().lower()}::{source.strip().lower()}")
    return stable_hash((title or "untitled").strip().lower())


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    load_dotenv()
    raw = open(path, "r", encoding="utf-8").read()
    rendered = Template(raw).safe_substitute(os.environ)
    return yaml.safe_load(rendered) or {}


def mask_url(url: str | None) -> str:
    if not url:
        return "<empty>"
    try:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "key=***", ""))
    except Exception:
        return "***"


def truthy_zh(value: bool) -> str:
    return "是" if value else "否"


def clamp(value: float, low: float = 1.0, high: float = 10.0) -> float:
    return max(low, min(high, value))
