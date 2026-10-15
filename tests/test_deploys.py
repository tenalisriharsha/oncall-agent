from datetime import datetime, timedelta, timezone
from pathlib import Path

from oncall_agent.tools.deploys import DeployHistoryStore, DeployHistoryTool, DeployRecord


def test_store_round_trips_records(tmp_path: Path):
    store = DeployHistoryStore(tmp_path / "deploys.jsonl")
    record = DeployRecord(service="checkout-service", version="v2", previous_version="v1")
    store.append(record)

    history = store.history_for("checkout-service")

    assert len(history) == 1
    assert history[0].service == "checkout-service"
    assert history[0].version == "v2"


def test_store_filters_by_service(tmp_path: Path):
    store = DeployHistoryStore(tmp_path / "deploys.jsonl")
    store.append(DeployRecord(service="checkout-service", version="v2", previous_version="v1"))
    store.append(DeployRecord(service="payments-service", version="v9", previous_version="v8"))

    assert len(store.history_for("checkout-service")) == 1
    assert len(store.history_for("payments-service")) == 1
    assert store.history_for("unknown-service") == []


def test_history_for_missing_file_returns_empty(tmp_path: Path):
    store = DeployHistoryStore(tmp_path / "missing.jsonl")
    assert store.history_for("checkout-service") == []


def test_history_for_skips_blank_lines(tmp_path: Path):
    path = tmp_path / "deploys.jsonl"
    store = DeployHistoryStore(path)
    store.append(DeployRecord(service="checkout-service", version="v2", previous_version="v1"))
    with path.open("a") as fh:
        fh.write("\n\n")

    assert len(store.history_for("checkout-service")) == 1


def test_tool_returns_nulls_when_no_history(tmp_path: Path):
    store = DeployHistoryStore(tmp_path / "deploys.jsonl")
    tool = DeployHistoryTool(store)

    result = tool.run(service="checkout-service")

    assert result == {
        "service": "checkout-service",
        "minutes_since_last_deploy": None,
        "version": None,
        "previous_version": None,
    }


def test_tool_returns_most_recent_deploy(tmp_path: Path):
    store = DeployHistoryStore(tmp_path / "deploys.jsonl")
    now = datetime.now(timezone.utc)
    store.append(
        DeployRecord(
            service="checkout-service",
            version="v1",
            previous_version="v0",
            deployed_at=now - timedelta(hours=2),
        )
    )
    store.append(
        DeployRecord(
            service="checkout-service",
            version="v2",
            previous_version="v1",
            deployed_at=now - timedelta(minutes=12),
        )
    )

    tool = DeployHistoryTool(store)
    result = tool.run(service="checkout-service")

    assert result["version"] == "v2"
    assert result["previous_version"] == "v1"
    assert result["minutes_since_last_deploy"] in (11, 12, 13)
