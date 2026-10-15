from pathlib import Path

from oncall_agent.config import (
    DEFAULT_AUDIT_LOG_PATH,
    DEFAULT_DEPLOY_HISTORY_PATH,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_PROMETHEUS_URL,
    DEFAULT_RUNBOOK_DIR,
    Settings,
)


def test_defaults_when_env_is_empty():
    settings = Settings.from_env(env={})
    assert settings.llm_provider == DEFAULT_LLM_PROVIDER
    assert settings.audit_log_path == DEFAULT_AUDIT_LOG_PATH
    assert settings.prometheus_url == DEFAULT_PROMETHEUS_URL
    assert settings.runbook_dir == DEFAULT_RUNBOOK_DIR
    assert settings.deploy_history_path == DEFAULT_DEPLOY_HISTORY_PATH
    assert settings.kubectl_namespace is None
    assert settings.kubectl_context is None


def test_env_overrides_llm_provider():
    settings = Settings.from_env(env={"ONCALL_AGENT_LLM_PROVIDER": "local"})
    assert settings.llm_provider == "local"


def test_env_overrides_audit_log_path():
    settings = Settings.from_env(env={"ONCALL_AGENT_AUDIT_LOG_PATH": "/tmp/custom/audit.jsonl"})
    assert settings.audit_log_path == Path("/tmp/custom/audit.jsonl")


def test_unrelated_env_vars_are_ignored():
    settings = Settings.from_env(env={"PATH": "/usr/bin", "HOME": "/root"})
    assert settings.llm_provider == DEFAULT_LLM_PROVIDER


def test_env_overrides_prometheus_url():
    settings = Settings.from_env(env={"ONCALL_AGENT_PROMETHEUS_URL": "http://prom.internal:9090"})
    assert settings.prometheus_url == "http://prom.internal:9090"


def test_env_overrides_kubectl_namespace_and_context():
    settings = Settings.from_env(
        env={"ONCALL_AGENT_KUBECTL_NAMESPACE": "prod", "ONCALL_AGENT_KUBECTL_CONTEXT": "prod-cluster"}
    )
    assert settings.kubectl_namespace == "prod"
    assert settings.kubectl_context == "prod-cluster"


def test_env_overrides_runbook_dir():
    settings = Settings.from_env(env={"ONCALL_AGENT_RUNBOOK_DIR": "/tmp/custom-runbooks"})
    assert settings.runbook_dir == Path("/tmp/custom-runbooks")


def test_env_overrides_deploy_history_path():
    settings = Settings.from_env(env={"ONCALL_AGENT_DEPLOY_HISTORY_PATH": "/tmp/deploys.jsonl"})
    assert settings.deploy_history_path == Path("/tmp/deploys.jsonl")
