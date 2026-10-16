"""Structured diagnosis report export (Markdown or JSON).

Turns a completed investigation (the alert plus the final `Diagnosis`,
including every hypothesis it considered along the way) into a document
that can be handed to a human on-call engineer or archived alongside the
audit trail — something more shareable than a terminal panel.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Alert, Diagnosis

REPORT_FORMATS = ("markdown", "json")


def diagnosis_report_dict(alert: Alert, diagnosis: Diagnosis) -> dict:
    """The report as a plain JSON-serializable dict."""
    return {
        "alert": alert.model_dump(mode="json"),
        "diagnosis": diagnosis.model_dump(mode="json"),
    }


def render_markdown(alert: Alert, diagnosis: Diagnosis) -> str:
    """Render the report as a standalone Markdown document."""
    lines = [
        f"# Incident report: {alert.id}",
        "",
        f"**Title:** {alert.title}",
        f"**Service:** {alert.service}",
        f"**Severity:** {alert.severity.value}",
        f"**Fired at:** {alert.fired_at.isoformat(timespec='seconds')}",
        "",
        "## Diagnosis",
        "",
        f"**Root cause:** {diagnosis.root_cause}",
        f"**Confidence:** {diagnosis.confidence:.2f}",
        f"**Proposed fix:** {diagnosis.proposed_fix}",
        f"**Requires approval:** {diagnosis.requires_approval}",
        "",
        "### Evidence",
        "",
    ]
    lines += [f"- {e}" for e in diagnosis.evidence] or ["- (none recorded)"]

    if diagnosis.hypotheses_considered:
        lines += ["", "### Hypotheses considered (ranked by confidence)", ""]
        for rank, hypothesis in enumerate(diagnosis.hypotheses_considered, start=1):
            lines.append(f"{rank}. ({hypothesis.confidence:.2f}) {hypothesis.statement}")

    lines.append("")
    return "\n".join(lines)


def export_report(alert: Alert, diagnosis: Diagnosis, path: str | Path, fmt: str = "markdown") -> Path:
    """Write the report to ``path`` in the given format and return it."""
    if fmt not in REPORT_FORMATS:
        raise ValueError(f"Unknown report format '{fmt}'. Use one of: {', '.join(REPORT_FORMATS)}.")

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        output_path.write_text(
            json.dumps(diagnosis_report_dict(alert, diagnosis), indent=2), encoding="utf-8"
        )
    else:
        output_path.write_text(render_markdown(alert, diagnosis), encoding="utf-8")

    return output_path
