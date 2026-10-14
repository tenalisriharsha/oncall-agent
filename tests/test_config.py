from pathlib import Path

from oncall_agent.config import DEFAULT_AUDIT_LOG_PATH, DEFAULT_LLM_PROVIDER, Settings


def test_defaults_when_env_is_empty():
    settings = Settings.from_env(env={})
    assert settings.llm_provider == DEFAULT_LLM_PROVIDER
    assert settings.audit_log_path == DEFAULT_AUDIT_LOG_PATH


def test_env_overrides_llm_provider():
    settings = Settings.from_env(env={"ONCALL_AGENT_LLM_PROVIDER": "local"})
    assert settings.llm_provider == "local"


def test_env_overrides_audit_log_path():
    settings = Settings.from_env(env={"ONCALL_AGENT_AUDIT_LOG_PATH": "/tmp/custom/audit.jsonl"})
    assert settings.audit_log_path == Path("/tmp/custom/audit.jsonl")


def test_unrelated_env_vars_are_ignored():
    settings = Settings.from_env(env={"PATH": "/usr/bin", "HOME": "/root"})
    assert settings.llm_provider == DEFAULT_LLM_PROVIDER
