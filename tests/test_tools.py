import pytest

from oncall_agent.tools.base import ToolRegistry
from oncall_agent.tools.fakes import FakePodStatusTool, FakeRecentDeploysTool


def test_fake_recent_deploys_tool_returns_configured_values():
    tool = FakeRecentDeploysTool(minutes_since_last_deploy=7, version="v3", previous_version="v2")
    result = tool.run(service="checkout-service")
    assert result == {
        "service": "checkout-service",
        "minutes_since_last_deploy": 7,
        "version": "v3",
        "previous_version": "v2",
    }


def test_fake_pod_status_tool_returns_configured_values():
    tool = FakePodStatusTool(restarts=9, oom_killed=True)
    result = tool.run(service="checkout-service")
    assert result == {"service": "checkout-service", "restarts": 9, "oom_killed": True}


def test_registry_register_and_get():
    registry = ToolRegistry()
    tool = FakeRecentDeploysTool()
    registry.register(tool)
    assert registry.get("get_recent_deploys") is tool


def test_registry_get_unknown_tool_raises_key_error():
    registry = ToolRegistry()
    registry.register(FakeRecentDeploysTool())
    with pytest.raises(KeyError, match="Unknown tool"):
        registry.get("get_pod_status")


def test_registry_names_sorted():
    registry = ToolRegistry()
    registry.register(FakePodStatusTool())
    registry.register(FakeRecentDeploysTool())
    assert registry.names() == ["get_pod_status", "get_recent_deploys"]
