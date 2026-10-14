"""The provider-agnostic contract between the agent loop and whatever is
making decisions: a deterministic scripted policy today, a local model
later, a hosted API if someone wants to pay for one. Nothing above this
interface should need to know which.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ..models import Alert, Diagnosis, Hypothesis, ToolCallRecord


class DecisionPhase(str, Enum):
    """Where the investigation currently stands."""

    INVESTIGATE = "investigate"
    CONCLUDE = "conclude"


class LLMAction(str, Enum):
    """What kind of move a provider's decision represents."""

    CALL_TOOL = "call_tool"
    FORM_HYPOTHESIS = "form_hypothesis"
    DIAGNOSE = "diagnose"


class LLMRequest(BaseModel):
    """Everything a provider needs to decide the next step."""

    alert: Alert
    tool_results: list[ToolCallRecord] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    phase: DecisionPhase = DecisionPhase.INVESTIGATE


class LLMResponse(BaseModel):
    """One decision: call a tool, record a hypothesis, or diagnose."""

    action: LLMAction
    rationale: str = ""
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    hypothesis: Hypothesis | None = None
    diagnosis: Diagnosis | None = None


class LLMProvider(ABC):
    """Base class every decision-making backend implements."""

    name: str = "base"

    @abstractmethod
    def decide(self, request: LLMRequest) -> LLMResponse:
        """Given the investigation so far, decide what to do next."""
        raise NotImplementedError
