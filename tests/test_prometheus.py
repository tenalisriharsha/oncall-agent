import pytest
import requests

from oncall_agent.tools.prometheus import (
    PrometheusClient,
    PrometheusQueryError,
    PrometheusQueryTool,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_instant_query_returns_data_on_success(monkeypatch):
    payload = {
        "status": "success",
        "data": {"resultType": "vector", "result": [{"metric": {}, "value": [1, "0.5"]}]},
    }
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(200, payload))

    client = PrometheusClient("http://localhost:9090")
    data = client.instant_query('up{job="checkout-service"}')

    assert data["resultType"] == "vector"
    assert data["result"][0]["value"] == [1, "0.5"]


def test_instant_query_strips_trailing_slash_from_base_url():
    client = PrometheusClient("http://localhost:9090/")
    assert client.base_url == "http://localhost:9090"


def test_instant_query_raises_on_network_error(monkeypatch):
    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "get", raise_connection_error)
    client = PrometheusClient("http://localhost:9090")

    with pytest.raises(PrometheusQueryError, match="Could not reach Prometheus"):
        client.instant_query("up")


def test_instant_query_raises_on_non_json_response(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(200, None, text="<html>"))
    client = PrometheusClient("http://localhost:9090")

    with pytest.raises(PrometheusQueryError, match="non-JSON"):
        client.instant_query("up")


def test_instant_query_raises_on_prometheus_error_status(monkeypatch):
    payload = {"status": "error", "error": "bad query"}
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(200, payload))
    client = PrometheusClient("http://localhost:9090")

    with pytest.raises(PrometheusQueryError, match="bad query"):
        client.instant_query("not a promql query(")


def test_instant_query_raises_on_http_error_status(monkeypatch):
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: FakeResponse(500, {"status": "error"}, text="boom")
    )
    client = PrometheusClient("http://localhost:9090")

    with pytest.raises(PrometheusQueryError):
        client.instant_query("up")


def test_query_tool_wraps_client(monkeypatch):
    payload = {"status": "success", "data": {"resultType": "vector", "result": []}}
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(200, payload))

    tool = PrometheusQueryTool(PrometheusClient("http://localhost:9090"))
    result = tool.run(query="up")

    assert result == {"query": "up", "result_type": "vector", "result": []}
