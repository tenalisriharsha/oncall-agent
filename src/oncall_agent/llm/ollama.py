"""An optional local-model provider backed by Ollama.

This satisfies the exact same :class:`~oncall_agent.llm.base.LLMProvider`
contract as :class:`~oncall_agent.llm.scripted.ScriptedPolicyProvider` —
nothing above the provider interface needs to know or care which one is
deciding. It is not the default: the scripted policy stays the
network-free provider tests and CI run against. This one talks to a
local Ollama server (``POST /api/generate``) and asks the model to
return its decision as JSON matching :class:`LLMResponse`.
"""

from __future__ import annotations

import json
from typing import Any

import requests
from pydantic import ValidationError

from ..models import Diagnosis, Hypothesis
from .base import LLMAction, LLMProvider, LLMRequest, LLMResponse

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1"

SYSTEM_PROMPT = """You are an on-call SRE investigating a production alert.
You will be given the alert, the tool results gathered so far, and any
hypotheses already formed. Decide the single next step.

Respond with ONLY a JSON object, no other text, matching one of these
three shapes:

1. Call a tool:
   {"action": "call_tool", "rationale": "...", "tool_name": "...", "tool_arguments": {...}}
2. Form (or revise) a hypothesis:
   {"action": "form_hypothesis", "rationale": "...",
    "hypothesis": {"statement": "...", "confidence": 0.0-1.0, "evidence": ["..."]}}
3. Conclude with a diagnosis:
   {"action": "diagnose", "rationale": "...",
    "diagnosis": {"root_cause": "...", "confidence": 0.0-1.0, "evidence": ["..."],
                   "proposed_fix": "...", "requires_approval": true}}
"""


class OllamaProviderError(RuntimeError):
    """Raised when Ollama is unreachable or returns an unparseable decision."""


class OllamaProvider(LLMProvider):
    """Decides the next step by asking a local Ollama model for JSON."""

    name = "ollama"

    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_OLLAMA_MODEL,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def decide(self, request: LLMRequest) -> LLMResponse:
        raw = self._generate(self._build_prompt(request))
        return self._parse_response(raw)

    def _build_prompt(self, request: LLMRequest) -> str:
        return (
            f"Alert: {request.alert.model_dump_json()}\n"
            f"Available tools: {request.available_tools}\n"
            f"Tool results so far: "
            f"{[r.model_dump(mode='json') for r in request.tool_results]}\n"
            f"Hypotheses so far: {[h.model_dump(mode='json') for h in request.hypotheses]}\n"
        )

    def _generate(self, prompt: str) -> str:
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "system": SYSTEM_PROMPT,
                    "stream": False,
                    "format": "json",
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise OllamaProviderError(f"Could not reach Ollama at {self.base_url}: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise OllamaProviderError(f"Ollama returned a non-JSON response: {response.text}") from exc

        if response.status_code != 200:
            error = payload.get("error", response.text)
            raise OllamaProviderError(f"Ollama request failed ({response.status_code}): {error}")

        return payload.get("response", "")

    def _parse_response(self, raw: str) -> LLMResponse:
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OllamaProviderError(f"Could not parse model output as JSON: {raw!r}") from exc

        try:
            action = LLMAction(data["action"])
        except (KeyError, ValueError) as exc:
            raise OllamaProviderError(f"Model returned an unknown action: {data!r}") from exc

        try:
            hypothesis = Hypothesis(**data["hypothesis"]) if data.get("hypothesis") else None
            diagnosis = Diagnosis(**data["diagnosis"]) if data.get("diagnosis") else None
        except (TypeError, ValidationError) as exc:
            raise OllamaProviderError(f"Model returned a malformed hypothesis/diagnosis: {data!r}") from exc

        return LLMResponse(
            action=action,
            rationale=data.get("rationale", ""),
            tool_name=data.get("tool_name"),
            tool_arguments=data.get("tool_arguments") or {},
            hypothesis=hypothesis,
            diagnosis=diagnosis,
        )
