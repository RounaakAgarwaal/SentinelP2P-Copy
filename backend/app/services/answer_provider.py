"""Provider boundary for grounded natural-language answer generation."""

from __future__ import annotations

from typing import Any, Protocol


class AnswerProvider(Protocol):
    """Contract for providers; providers must cite only supplied source IDs."""

    @property
    def configured(self) -> bool: ...

    def generate(self, *, question: str, conversation_history: list[dict[str, str]],
                 sources: list[dict[str, Any]]) -> dict[str, Any]: ...


class UnconfiguredAnswerProvider:
    """Explicitly disabled implementation; no network or fallback provider."""

    configured = False

    def generate(self, *, question: str, conversation_history: list[dict[str, str]],
                 sources: list[dict[str, Any]]) -> dict[str, Any]:
        del question, conversation_history, sources
        raise RuntimeError("No Sentinel AI answer provider is configured.")
