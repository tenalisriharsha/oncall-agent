import json

import pytest
import requests

from oncall_agent.llm.base import LLMAction, LLMRequest
from oncall_agent.llm.ollama import SYSTEM_PROMPT, OllamaProvider, OllamaProviderError
from oncall_agent.models import ActionType, Alert


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def make_request() -> LLMRequest:
    alert = Alert(title="High error rate", description="5xx spike", service="checkout-service")
    return LLMRequest(alert=alert)


def test_decide_parses_call_tool_action(monkeypatch):
    decision = {
        "action": "call_tool",
        "rationale": "check deploys",
        "tool_name": "get_recent_deploys",
        "tool_arguments": {"service": "checkout-service"},
    }
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: FakeResponse(200, {"response": json.dumps(decision)})
    )

    provider = OllamaProvider()
    response = provider.decide(make_request())

    assert response.action == LLMAction.CALL_TOOL
    assert response.tool_name == "get_recent_deploys"
    assert response.tool_arguments == {"service": "checkout-service"}


def test_decide_parses_form_hypothesis_action(monkeypatch):
    decision = {
        "action": "form_hypothesis",
        "hypothesis": {"statement": "maybe a deploy", "confidence": 0.6, "evidence": ["e"]},
    }
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: FakeResponse(200, {"response": json.dumps(decision)})
    )

    response = OllamaProvider().decide(make_request())

    assert response.action == LLMAction.FORM_HYPOTHESIS
    assert response.hypothesis.statement == "maybe a deploy"
    assert response.hypothesis.confidence == 0.6


def test_decide_parses_diagnose_action(monkeypatch):
    decision = {
        "action": "diagnose",
        "diagnosis": {
            "root_cause": "bad deploy",
            "confidence": 0.8,
            "proposed_fix": "roll back",
        },
    }
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: FakeResponse(200, {"response": json.dumps(decision)})
    )

    response = OllamaProvider().decide(make_request())

    assert response.action == LLMAction.DIAGNOSE
    assert response.diagnosis.root_cause == "bad deploy"


def test_system_prompt_diagnose_shape_requests_action_fields():
    """Without these in the shape, the model never supplies them, so
    `Diagnosis.action` stays `None` for every Ollama diagnosis and
    `respond_to_incident()`/scorecard can never see an action (issue #6).
    """
    diagnose_shape = SYSTEM_PROMPT.split('"diagnose"', 1)[1]

    assert '"category"' in diagnose_shape
    assert '"action"' in diagnose_shape
    assert '"action_arguments"' in diagnose_shape


def test_decide_parses_diagnose_action_and_category(monkeypatch):
    decision = {
        "action": "diagnose",
        "diagnosis": {
            "root_cause": "bad deploy",
            "confidence": 0.9,
            "evidence": ["deploy 10m ago"],
            "proposed_fix": "roll back checkout-service to v1.2.3",
            "requires_approval": True,
            "category": "deploy_regression",
            "action": "rollback",
            "action_arguments": {"service": "checkout-service", "version": "v1.2.3"},
        },
    }
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: FakeResponse(200, {"response": json.dumps(decision)})
    )

    response = OllamaProvider().decide(make_request())

    assert response.diagnosis.action == ActionType.ROLLBACK
    assert response.diagnosis.category == "deploy_regression"
    assert response.diagnosis.action_arguments == {
        "service": "checkout-service",
        "version": "v1.2.3",
    }


def test_decide_raises_on_network_error(monkeypatch):
    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", raise_connection_error)

    with pytest.raises(OllamaProviderError, match="Could not reach Ollama"):
        OllamaProvider().decide(make_request())


def test_decide_raises_on_non_json_http_response(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(200, None, text="<html>"))

    with pytest.raises(OllamaProviderError, match="non-JSON"):
        OllamaProvider().decide(make_request())


def test_decide_raises_on_http_error_status(monkeypatch):
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: FakeResponse(500, {"error": "boom"})
    )

    with pytest.raises(OllamaProviderError, match="boom"):
        OllamaProvider().decide(make_request())


def test_decide_raises_when_model_output_is_not_json(monkeypatch):
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: FakeResponse(200, {"response": "not json at all"})
    )

    with pytest.raises(OllamaProviderError, match="Could not parse model output"):
        OllamaProvider().decide(make_request())


def test_decide_raises_on_unknown_action(monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: FakeResponse(200, {"response": json.dumps({"action": "bogus"})}),
    )

    with pytest.raises(OllamaProviderError, match="unknown action"):
        OllamaProvider().decide(make_request())


def test_decide_raises_on_non_dict_tool_arguments(monkeypatch):
    """A model can return `tool_arguments` as a list instead of an object
    (observed from a real local model). That must surface as a clean
    OllamaProviderError, not an uncaught pydantic ValidationError when
    building LLMResponse (issue #17).
    """
    decision = {
        "action": "call_tool",
        "tool_name": "get_pod_status",
        "tool_arguments": ["get_pod_status", "checkout-service"],
    }
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: FakeResponse(200, {"response": json.dumps(decision)})
    )

    with pytest.raises(OllamaProviderError):
        OllamaProvider().decide(make_request())


def test_decide_raises_on_malformed_hypothesis(monkeypatch):
    decision = {"action": "form_hypothesis", "hypothesis": {"confidence": 5.0}}
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: FakeResponse(200, {"response": json.dumps(decision)})
    )

    with pytest.raises(OllamaProviderError, match="malformed"):
        OllamaProvider().decide(make_request())


def test_base_url_trailing_slash_is_stripped():
    provider = OllamaProvider(base_url="http://localhost:11434/")
    assert provider.base_url == "http://localhost:11434"


def test_custom_model_and_url_are_used_in_request(monkeypatch):
    captured = {}
    decision = {"action": "diagnose", "diagnosis": {"root_cause": "x", "confidence": 0.5, "proposed_fix": "y"}}
    decision_text = json.dumps(decision)

    def fake_post(url, json, timeout):  # noqa: A002 - matches requests.post's kwarg name
        captured["url"] = url
        captured["json"] = json
        return FakeResponse(200, {"response": decision_text})

    monkeypatch.setattr(requests, "post", fake_post)

    provider = OllamaProvider(base_url="http://example.com:11434", model="mixtral")
    provider.decide(make_request())

    assert captured["url"] == "http://example.com:11434/api/generate"
    assert captured["json"]["model"] == "mixtral"
