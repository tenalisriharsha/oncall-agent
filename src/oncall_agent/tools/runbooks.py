"""Keyword search over a local runbook corpus.

This is deliberately not a vector-embedding RAG pipeline: a fixed,
dependency-free term-overlap score keeps the tool deterministic (no
model calls, no index to build or go stale) while still surfacing the
right runbook for a query built from an alert's title and service. The
corpus is plain markdown under ``runbooks/`` so on-call engineers can
read, review, and edit it like any other document.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import Tool

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "on", "in",
    "for", "and", "or", "at", "by", "with", "this", "that", "it", "its",
}


def _terms(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS and len(w) > 2]


def _excerpt(text: str, terms: list[str], radius: int = 120) -> str:
    lowered = text.lower()
    for term in terms:
        idx = lowered.find(term)
        if idx != -1:
            start = max(0, idx - radius // 2)
            end = min(len(text), idx + radius // 2)
            snippet = text[start:end].strip().replace("\n", " ")
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(text) else ""
            return f"{prefix}{snippet}{suffix}"
    return text[:radius].strip().replace("\n", " ")


class RunbookSearchTool(Tool):
    """Scores each runbook in a directory against a query and returns the top matches."""

    name = "search_runbooks"
    description = "Keyword-search the local runbook corpus for relevant guidance."
    read_only = True

    def __init__(self, runbook_dir: str | Path, top_k: int = 3) -> None:
        self.runbook_dir = Path(runbook_dir)
        self.top_k = top_k

    def _documents(self) -> list[tuple[str, str]]:
        if not self.runbook_dir.is_dir():
            return []
        return [
            (path.stem, path.read_text(encoding="utf-8"))
            for path in sorted(self.runbook_dir.glob("*.md"))
        ]

    def run(self, query: str, **kwargs: Any) -> dict[str, Any]:
        query_terms = _terms(query)
        scored: list[tuple[int, str, str]] = []
        for name, text in self._documents():
            lowered = text.lower()
            score = sum(lowered.count(term) for term in query_terms)
            if score > 0:
                scored.append((score, name, text))

        scored.sort(key=lambda t: t[0], reverse=True)
        matches = [
            {"runbook": name, "score": score, "excerpt": _excerpt(text, query_terms)}
            for score, name, text in scored[: self.top_k]
        ]
        return {"query": query, "matches": matches}
