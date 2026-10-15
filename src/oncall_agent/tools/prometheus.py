"""A read-only Prometheus client and the tool that wraps it.

Talks to the standard Prometheus HTTP API (``/api/v1/query``) over plain
``requests`` calls. There is no write path here by design: this module
can only ever read metrics, never push them or change server state.
"""

from __future__ import annotations

from typing import Any

import requests

from .base import Tool


class PrometheusQueryError(RuntimeError):
    """Raised when Prometheus reports a query error or is unreachable."""


class PrometheusClient:
    """Thin wrapper around Prometheus's instant-query HTTP endpoint."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def instant_query(self, query: str) -> dict[str, Any]:
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/query",
                params={"query": query},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise PrometheusQueryError(f"Could not reach Prometheus at {self.base_url}: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise PrometheusQueryError(f"Prometheus returned a non-JSON response: {response.text}") from exc

        if response.status_code != 200 or payload.get("status") != "success":
            error = payload.get("error", response.text)
            raise PrometheusQueryError(f"Prometheus query failed: {error}")

        return payload["data"]


class PrometheusQueryTool(Tool):
    """Runs a read-only PromQL instant query."""

    name = "query_prometheus"
    description = "Run a read-only PromQL instant query against Prometheus."
    read_only = True

    def __init__(self, client: PrometheusClient) -> None:
        self.client = client

    def run(self, query: str, **kwargs: Any) -> dict[str, Any]:
        data = self.client.instant_query(query)
        return {
            "query": query,
            "result_type": data.get("resultType"),
            "result": data.get("result", []),
        }
