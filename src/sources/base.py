from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.models import NewsItem


class SourceError(RuntimeError):
    pass


class BaseSource(ABC):
    def __init__(self, config: dict[str, Any], max_items: int = 50) -> None:
        self.config = config
        self.name = str(config.get("name", "unknown"))
        self.url = str(config.get("url", ""))
        self.max_items = max_items

    @abstractmethod
    def fetch(self) -> list[NewsItem]:
        raise NotImplementedError
