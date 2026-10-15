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
DEFAULT_PROMETHEUS_URL = "http://localhost:9090"
DEFAULT_RUNBOOK_DIR = Path("runbooks")
DEFAULT_DEPLOY_HISTORY_PATH = Path(".oncall-agent/deploys.jsonl")
ENV_PREFIX = "ONCALL_AGENT_"


class Settings(BaseModel):
    """Resolved configuration for a single run of the agent."""

    llm_provider: str = DEFAULT_LLM_PROVIDER
    audit_log_path: Path = DEFAULT_AUDIT_LOG_PATH
    prometheus_url: str = DEFAULT_PROMETHEUS_URL
    kubectl_namespace: str | None = None
    kubectl_context: str | None = None
    runbook_dir: Path = DEFAULT_RUNBOOK_DIR
    deploy_history_path: Path = DEFAULT_DEPLOY_HISTORY_PATH

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        source = os.environ if env is None else env
        kwargs: dict[str, str] = {}
        if (value := source.get(f"{ENV_PREFIX}LLM_PROVIDER")) is not None:
            kwargs["llm_provider"] = value
        if (value := source.get(f"{ENV_PREFIX}AUDIT_LOG_PATH")) is not None:
            kwargs["audit_log_path"] = value
        if (value := source.get(f"{ENV_PREFIX}PROMETHEUS_URL")) is not None:
            kwargs["prometheus_url"] = value
        if (value := source.get(f"{ENV_PREFIX}KUBECTL_NAMESPACE")) is not None:
            kwargs["kubectl_namespace"] = value
        if (value := source.get(f"{ENV_PREFIX}KUBECTL_CONTEXT")) is not None:
            kwargs["kubectl_context"] = value
        if (value := source.get(f"{ENV_PREFIX}RUNBOOK_DIR")) is not None:
            kwargs["runbook_dir"] = value
        if (value := source.get(f"{ENV_PREFIX}DEPLOY_HISTORY_PATH")) is not None:
            kwargs["deploy_history_path"] = value
        return cls(**kwargs)
