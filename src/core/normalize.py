from __future__ import annotations

import hashlib
import os
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv


def clean_text(value: object, max_chars: int | None = None) -> str:
    if value is None:
        return ""
    text = BeautifulSoup(str(value), "html.parser").get_text(" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars].strip() if max_chars else text


def first_image_from_html(value: str | None) -> str | None:
    if not value:
        return None
    soup = BeautifulSoup(value, "html.parser")
    img = soup.find("img")
    if img and img.get("src"):
        return str(img["src"])
    return None


def canonical_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    drop = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "from", "spm"}
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in drop])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def item_id(source: str, title: str, url: str) -> str:
    key = canonical_url(url) or f"{title}|{source}" or title
    return stable_hash(key)


def load_config(path: str = "config.yaml") -> dict:
    load_dotenv()
    raw = open(path, "r", encoding="utf-8").read()
    expanded = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: os.environ.get(m.group(1), ""), raw)
    return yaml.safe_load(expanded) or {}


def mask_secret(value: str | None, keep: int = 6) -> str:
    if not value:
        return "<empty>"
    if len(value) <= keep * 2:
        return "***"
    return f"{value[:keep]}...{value[-keep:]}"
