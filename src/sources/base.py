from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.models import NewsItem


class Source(ABC):
    def __init__(self, config: dict[str, Any], max_items: int = 50):
        self.config = config
        self.max_items = max_items
        self.name = config.get("name", "unknown")

    @abstractmethod
    def fetch(self) -> list[NewsItem]:
        raise NotImplementedError
