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


def clean_text(value: Any, max_chars: int | None = None) -> str:
    if value is None:
        return ""
    text = BeautifulSoup(str(value), "html.parser").get_text(" ")
    text = re.sub(r"\s+", " ", text).strip()
    if max_chars and len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def extract_first_image(html: str | None) -> str | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    img = soup.find("img")
    if img and img.get("src"):
        return str(img.get("src"))
    return None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonicalize_url(url: str | None) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))
    except Exception:
        return url.strip()


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    load_dotenv()
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    expanded = Template(raw).safe_substitute(os.environ)
    return yaml.safe_load(expanded) or {}


def bool_cn(value: bool) -> str:
    return "是" if value else "否"


def clamp(value: float, low: float = 1, high: float = 10) -> float:
    return max(low, min(high, value))


def truncate(value: str, max_chars: int) -> str:
    value = value or ""
    return value if len(value) <= max_chars else value[: max_chars - 1].rstrip() + "…"


def mask_url(url: str) -> str:
    if not url:
        return "<empty>"
    if "${" in url:
        return "<env placeholder>"
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return "<invalid or placeholder>"
    return f"{parts.scheme}://{parts.netloc}{parts.path}?key=***" if parts.query else f"{parts.scheme}://{parts.netloc}{parts.path}"
