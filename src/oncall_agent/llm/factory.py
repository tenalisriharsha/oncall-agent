"""Looks up an :class:`LLMProvider` by name.

Keeping this separate from the providers themselves is what makes the LLM
backend swappable from config (``ONCALL_AGENT_LLM_PROVIDER``) without the
rest of the codebase caring which implementation it got.
"""

from __future__ import annotations

from typing import Any

from .base import LLMProvider
from .ollama import OllamaProvider
from .scripted import ScriptedPolicyProvider

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "scripted": ScriptedPolicyProvider,
    "ollama": OllamaProvider,
}

_PLANNED_PROVIDERS = {
    "local": "Local-model support (e.g. llama.cpp/Ollama) is planned for a later phase.",
}


def get_provider(name: str, **kwargs: Any) -> LLMProvider:
    """Instantiate the named provider.

    Extra ``kwargs`` are forwarded to the provider's constructor (e.g.
    ``base_url``/``model`` for ``"ollama"``); the scripted policy takes
    none. Raises ``NotImplementedError`` for providers that are on the
    roadmap but not built yet, and ``ValueError`` for anything
    unrecognized.
    """
    if name in _PLANNED_PROVIDERS:
        raise NotImplementedError(_PLANNED_PROVIDERS[name])
    try:
        provider_cls = _PROVIDERS[name]
    except KeyError as exc:
        known = ", ".join(sorted(_PROVIDERS))
        raise ValueError(f"Unknown LLM provider '{name}'. Known providers: {known}") from exc
    return provider_cls(**kwargs)


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)
