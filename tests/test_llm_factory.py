import pytest

from oncall_agent.llm.factory import available_providers, get_provider
from oncall_agent.llm.scripted import ScriptedPolicyProvider


def test_get_provider_returns_scripted_by_name():
    provider = get_provider("scripted")
    assert isinstance(provider, ScriptedPolicyProvider)


def test_get_provider_unknown_name_raises_value_error():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_provider("gpt-nonexistent")


def test_get_provider_local_raises_not_implemented_with_explanation():
    with pytest.raises(NotImplementedError, match="later phase"):
        get_provider("local")


def test_available_providers_lists_scripted():
    assert "scripted" in available_providers()
