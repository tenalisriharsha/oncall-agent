"""Resolved runtime settings.

Everything here can be overridden with an environment variable prefixed
``ONCALL_AGENT_``, which is how the LLM backend, audit log location, and
(in later phases) cluster/Slack credentials get swapped between a local
dev run and CI without touching code.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

DEFAULT_AUDIT_LOG_PATH = Path(".oncall-agent/audit.jsonl")
DEFAULT_LLM_PROVIDER = "scripted"
ENV_PREFIX = "ONCALL_AGENT_"


class Settings(BaseModel):
    """Resolved configuration for a single run of the agent."""

    llm_provider: str = DEFAULT_LLM_PROVIDER
    audit_log_path: Path = DEFAULT_AUDIT_LOG_PATH

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        source = os.environ if env is None else env
        kwargs: dict[str, str] = {}
        if (value := source.get(f"{ENV_PREFIX}LLM_PROVIDER")) is not None:
            kwargs["llm_provider"] = value
        if (value := source.get(f"{ENV_PREFIX}AUDIT_LOG_PATH")) is not None:
            kwargs["audit_log_path"] = value
        return cls(**kwargs)
