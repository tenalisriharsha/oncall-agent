import json
import subprocess

import pytest

from oncall_agent.tools.kubectl import (
    KubectlClient,
    KubectlDescribeTool,
    KubectlError,
    KubectlLogsTool,
    KubectlPodStatusTool,
)


def fake_runner(stdout: str = "", returncode: int = 0, stderr: str = ""):
    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    return runner


PODS_JSON = {
    "items": [
        {
            "status": {
                "containerStatuses": [
                    {"restartCount": 3, "lastState": {}},
                ]
            }
        },
        {
            "status": {
                "containerStatuses": [
                    {
                        "restartCount": 2,
                        "lastState": {"terminated": {"reason": "OOMKilled"}},
                    },
                ]
            }
        },
    ]
}


def test_run_refuses_mutating_subcommand():
    client = KubectlClient(runner=fake_runner())
    with pytest.raises(KubectlError, match="Refusing to run non-read-only"):
        client._run(["delete", "pod", "foo"])


def test_run_refuses_empty_args():
    client = KubectlClient(runner=fake_runner())
    with pytest.raises(KubectlError, match="Refusing to run"):
        client._run([])


def test_run_includes_namespace_and_context():
    seen = {}

    def runner(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    client = KubectlClient(namespace="prod", context="prod-cluster", runner=runner)
    client._run(["get", "pods"])

    assert seen["cmd"] == ["kubectl", "get", "pods", "-n", "prod", "--context", "prod-cluster"]


def test_run_raises_on_nonzero_exit():
    client = KubectlClient(runner=fake_runner(returncode=1, stderr="not found"))
    with pytest.raises(KubectlError, match="not found"):
        client._run(["get", "pods"])


def test_run_raises_on_runner_exception():
    def raising_runner(cmd, **kwargs):
        raise OSError("no such file")

    client = KubectlClient(runner=raising_runner)
    with pytest.raises(KubectlError, match="Failed to run"):
        client._run(["get", "pods"])


def test_get_pods_json_parses_output():
    client = KubectlClient(runner=fake_runner(stdout=json.dumps(PODS_JSON)))
    assert client.get_pods_json(selector="app=checkout-service") == PODS_JSON


def test_get_pods_json_raises_on_bad_json():
    client = KubectlClient(runner=fake_runner(stdout="not json"))
    with pytest.raises(KubectlError, match="Could not parse"):
        client.get_pods_json()


def test_describe_pod_returns_stdout():
    client = KubectlClient(runner=fake_runner(stdout="Name: foo\nStatus: Running"))
    assert client.describe_pod("foo") == "Name: foo\nStatus: Running"


def test_logs_includes_tail_and_previous_flag():
    seen = {}

    def runner(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="log line", stderr="")

    client = KubectlClient(runner=runner)
    client.logs("foo", tail_lines=50, previous=True)

    assert seen["cmd"] == ["kubectl", "logs", "foo", "--tail", "50", "-p"]


def test_pod_status_tool_aggregates_restarts_and_oom():
    client = KubectlClient(runner=fake_runner(stdout=json.dumps(PODS_JSON)))
    tool = KubectlPodStatusTool(client)

    result = tool.run(service="checkout-service")

    assert result == {
        "service": "checkout-service",
        "pod_count": 2,
        "restarts": 5,
        "oom_killed": True,
    }


def test_pod_status_tool_no_oom_when_none_terminated():
    pods = {"items": [{"status": {"containerStatuses": [{"restartCount": 0, "lastState": {}}]}}]}
    client = KubectlClient(runner=fake_runner(stdout=json.dumps(pods)))
    tool = KubectlPodStatusTool(client)

    result = tool.run(service="checkout-service")

    assert result["oom_killed"] is False
    assert result["restarts"] == 0


def test_logs_tool_returns_payload():
    client = KubectlClient(runner=fake_runner(stdout="boot ok\n"))
    tool = KubectlLogsTool(client)

    result = tool.run(pod_name="checkout-service-abc123", tail_lines=10)

    assert result == {
        "pod_name": "checkout-service-abc123",
        "tail_lines": 10,
        "logs": "boot ok\n",
    }


def test_describe_tool_returns_payload():
    client = KubectlClient(runner=fake_runner(stdout="Name: foo"))
    tool = KubectlDescribeTool(client)

    result = tool.run(pod_name="foo")

    assert result == {"pod_name": "foo", "description": "Name: foo"}
