"""Append-only audit trail.

Every step the agent takes during an investigation is written here as one
JSON line, so an incident can be fully reconstructed later: what the agent
saw, what it called, what it concluded, and who approved what.
"""

from __future__ import annotations

from pathlib import Path

from .models import AuditEvent


class AuditTrail:
    """A JSON-lines audit log backed by a single file.

    Each call to :meth:`log` appends one line; nothing already written is
    ever rewritten or deleted, so the file itself is the audit record.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: AuditEvent) -> AuditEvent:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json())
            fh.write("\n")
        return event

    def read_all(self) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        events: list[AuditEvent] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                events.append(AuditEvent.model_validate_json(line))
        return events

    def for_incident(self, incident_id: str) -> list[AuditEvent]:
        return [e for e in self.read_all() if e.incident_id == incident_id]
