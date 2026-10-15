"""A deploy/CD history source backed by an append-only JSON-lines ledger.

Most CD systems either expose a proper API or, when they don't, a
webhook that fires on every deploy. This models the latter: a CD
pipeline (or a webhook receiver in front of one) appends one
:class:`DeployRecord` per release, and this tool answers "what was the
most recent deploy to this service?" by reading that ledger back. It
follows the same append-only, JSON-lines shape as :class:`~oncall_agent.audit.AuditTrail`
so a deploy history is just as auditable as the investigation itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .base import Tool


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DeployRecord(BaseModel):
    """One deploy of one service, as recorded by the CD pipeline."""

    service: str
    version: str
    previous_version: str
    deployed_at: datetime = Field(default_factory=_utcnow)


class DeployHistoryStore:
    """An append-only JSON-lines ledger of :class:`DeployRecord` entries."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, record: DeployRecord) -> DeployRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json())
            fh.write("\n")
        return record

    def history_for(self, service: str) -> list[DeployRecord]:
        if not self.path.exists():
            return []
        records: list[DeployRecord] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = DeployRecord.model_validate_json(line)
                if record.service == service:
                    records.append(record)
        return records


class DeployHistoryTool(Tool):
    """Returns the most recent deploy to a service from the deploy ledger."""

    name = "get_recent_deploys"
    description = "Return recent deploy history for a service from the CD deploy ledger."
    read_only = True

    def __init__(self, store: DeployHistoryStore) -> None:
        self.store = store

    def run(self, service: str, **kwargs: Any) -> dict[str, Any]:
        records = self.store.history_for(service)
        if not records:
            return {
                "service": service,
                "minutes_since_last_deploy": None,
                "version": None,
                "previous_version": None,
            }

        latest = max(records, key=lambda r: r.deployed_at)
        minutes_since = int((_utcnow() - latest.deployed_at).total_seconds() // 60)
        return {
            "service": service,
            "minutes_since_last_deploy": minutes_since,
            "version": latest.version,
            "previous_version": latest.previous_version,
        }
