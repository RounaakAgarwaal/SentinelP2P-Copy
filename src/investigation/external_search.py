"""Provider-isolated Tavily Search API adapter."""

from __future__ import annotations

import os
from typing import Any, Protocol, TypedDict

import requests


class SearchResult(TypedDict, total=False):
    title: str
    url: str
    content: str
    score: float


class SearchProvider(Protocol):
    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]: ...


class MissingSearchCredentials(RuntimeError):
    """Raised when a search is requested without the configured API credential."""


class TavilySearchProvider:
    """Tavily REST adapter; other search providers can implement the same protocol."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        endpoint: str | None = None,
        session: Any = requests,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("TAVILY_API_KEY")
        self.endpoint = endpoint or os.getenv("TAVILY_API_URL", "https://api.tavily.com/search")
        self.session = session
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            raise MissingSearchCredentials("TAVILY_API_KEY is not configured")
        response = self.session.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "query": query,
                "search_depth": "basic",
                "max_results": max(1, min(int(max_results), 20)),
                "include_answer": False,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        results = body.get("results", []) if isinstance(body, dict) else []
        if not isinstance(results, list):
            raise ValueError("Search provider returned an invalid results field")
        normalized: list[SearchResult] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                continue
            normalized.append({
                "title": str(item.get("title") or ""),
                "url": url,
                "content": str(item.get("content") or ""),
                "score": item.get("score") if isinstance(item.get("score"), (float, int)) else None,
            })
        return normalized
