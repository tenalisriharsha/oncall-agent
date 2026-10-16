"""Command-line entry point.

Phase 1 ships four commands: ``version`` and ``config`` for sanity
checks, ``demo`` to run a full canned investigation end to end with the
scripted policy and fake tools, and ``audit`` to inspect the trail that
investigation left behind.
"""

from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .audit import AuditTrail
from .config import Settings
from .investigation import run_investigation
from .llm import get_provider
from .models import Alert, Severity
from .report import REPORT_FORMATS, export_report
from .tools import FakePodStatusTool, FakeRecentDeploysTool, ToolRegistry
from .tools.deploys import DeployHistoryStore, DeployHistoryTool, DeployRecord
from .tools.kubectl import KubectlClient, KubectlError, KubectlLogsTool, KubectlPodStatusTool
from .tools.prometheus import PrometheusClient, PrometheusQueryError, PrometheusQueryTool
from .tools.runbooks import RunbookSearchTool

console = Console()

SCENARIOS = {
    "deploy-regression": dict(
        title="High error rate on checkout-service",
        description="5xx rate on checkout-service exceeded 5% for 5 minutes.",
        service="checkout-service",
        severity=Severity.HIGH,
        deploy_minutes_ago=12,
        version="v2.4.1",
        previous_version="v2.4.0",
        pod_restarts=5,
        oom_killed=False,
    ),
    "oom": dict(
        title="checkout-service pods crash-looping",
        description="checkout-service pods are restarting repeatedly.",
        service="checkout-service",
        severity=Severity.CRITICAL,
        deploy_minutes_ago=180,
        version="v2.4.0",
        previous_version="v2.3.9",
        pod_restarts=20,
        oom_killed=True,
    ),
    "unknown": dict(
        title="Elevated latency on checkout-service",
        description="p99 latency on checkout-service is 3x baseline.",
        service="checkout-service",
        severity=Severity.MEDIUM,
        deploy_minutes_ago=180,
        version="v2.4.0",
        previous_version="v2.3.9",
        pod_restarts=0,
        oom_killed=False,
    ),
}


@click.group()
def main() -> None:
    """oncall-agent: an agentic SRE incident responder."""


@main.command()
def version() -> None:
    """Print the installed version."""
    console.print(f"oncall-agent {__version__}")


@main.command(name="config")
def config_cmd() -> None:
    """Show resolved configuration."""
    settings = Settings.from_env()
    table = Table(title="oncall-agent configuration")
    table.add_column("setting")
    table.add_column("value")
    table.add_row("llm_provider", settings.llm_provider)
    table.add_row("audit_log_path", str(settings.audit_log_path))
    table.add_row("prometheus_url", settings.prometheus_url)
    table.add_row("kubectl_namespace", settings.kubectl_namespace or "(default context namespace)")
    table.add_row("kubectl_context", settings.kubectl_context or "(current context)")
    table.add_row("runbook_dir", str(settings.runbook_dir))
    table.add_row("deploy_history_path", str(settings.deploy_history_path))
    table.add_row("ollama_url", settings.ollama_url)
    table.add_row("ollama_model", settings.ollama_model)
    console.print(table)


@main.command()
@click.option(
    "--scenario",
    type=click.Choice(sorted(SCENARIOS)),
    default="deploy-regression",
    show_default=True,
    help="Which canned incident scenario to investigate.",
)
@click.option(
    "--audit-log",
    "audit_log_path",
    default=None,
    help="Where to append the audit trail. Defaults to the configured path.",
)
@click.option(
    "--report",
    "report_path",
    default=None,
    help="If given, export the structured diagnosis report to this path.",
)
@click.option(
    "--report-format",
    "report_format",
    type=click.Choice(REPORT_FORMATS),
    default="markdown",
    show_default=True,
    help="Format for --report.",
)
def demo(scenario: str, audit_log_path: str | None, report_path: str | None, report_format: str) -> None:
    """Run a full canned investigation with the scripted policy provider."""
    settings = Settings.from_env()
    log_path = audit_log_path or str(settings.audit_log_path)

    params = SCENARIOS[scenario]
    alert = Alert(
        title=params["title"],
        description=params["description"],
        service=params["service"],
        severity=params["severity"],
    )

    tools = ToolRegistry()
    tools.register(
        FakeRecentDeploysTool(
            minutes_since_last_deploy=params["deploy_minutes_ago"],
            version=params["version"],
            previous_version=params["previous_version"],
        )
    )
    tools.register(
        FakePodStatusTool(restarts=params["pod_restarts"], oom_killed=params["oom_killed"])
    )

    if settings.llm_provider == "ollama":
        provider = get_provider("ollama", base_url=settings.ollama_url, model=settings.ollama_model)
    else:
        provider = get_provider(settings.llm_provider)
    audit = AuditTrail(log_path)

    console.print(
        Panel(
            f"[bold]{alert.title}[/bold]\n{alert.description}\n"
            f"service={alert.service} severity={alert.severity.value}",
            title=f"Alert {alert.id}",
        )
    )

    diagnosis = run_investigation(alert, provider, tools, audit)

    body = (
        f"[bold]Root cause:[/bold] {diagnosis.root_cause}\n"
        f"[bold]Confidence:[/bold] {diagnosis.confidence:.2f}\n"
        f"[bold]Proposed fix:[/bold] {diagnosis.proposed_fix}\n"
        f"[bold]Requires approval:[/bold] {diagnosis.requires_approval}\n\n"
        f"[bold]Evidence:[/bold]\n" + "\n".join(f"  - {e}" for e in diagnosis.evidence)
    )
    if diagnosis.hypotheses_considered:
        body += "\n\n[bold]Hypotheses considered (ranked by confidence):[/bold]\n" + "\n".join(
            f"  {i}. ({h.confidence:.2f}) {h.statement}"
            for i, h in enumerate(diagnosis.hypotheses_considered, start=1)
        )
    console.print(Panel(body, title="Diagnosis", border_style="green"))
    console.print(f"[dim]Audit trail written to {log_path}[/dim]")

    if report_path:
        written = export_report(alert, diagnosis, report_path, fmt=report_format)
        console.print(f"[dim]Diagnosis report written to {written}[/dim]")


@main.command(name="audit")
@click.option(
    "--audit-log",
    "audit_log_path",
    default=None,
    help="Audit log to read. Defaults to the configured path.",
)
@click.option("--incident", "incident_id", default=None, help="Filter to a single incident id.")
def audit_cmd(audit_log_path: str | None, incident_id: str | None) -> None:
    """Show the audit trail of one or more investigations."""
    settings = Settings.from_env()
    log_path = audit_log_path or str(settings.audit_log_path)
    trail = AuditTrail(log_path)
    events = trail.for_incident(incident_id) if incident_id else trail.read_all()

    if not events:
        console.print(f"[yellow]No audit events found at {log_path}[/yellow]")
        return

    table = Table(title=f"Audit trail ({log_path})")
    table.add_column("timestamp")
    table.add_column("incident")
    table.add_column("event")
    table.add_column("summary")
    for event in events:
        table.add_row(
            event.timestamp.isoformat(timespec="seconds"),
            event.incident_id,
            event.event_type.value,
            _summarize(event.payload),
        )
    console.print(table)


def _summarize(payload: dict) -> str:
    text = str(payload)
    return text if len(text) <= 80 else text[:77] + "..."


@main.group()
def tools() -> None:
    """Call a single real read-only tool directly, outside of an investigation."""


@tools.command("query-prometheus")
@click.argument("query")
@click.option(
    "--url",
    "prometheus_url",
    default=None,
    help="Prometheus base URL. Defaults to the configured URL.",
)
def tools_query_prometheus(query: str, prometheus_url: str | None) -> None:
    """Run a read-only PromQL instant query."""
    settings = Settings.from_env()
    client = PrometheusClient(prometheus_url or settings.prometheus_url)
    tool = PrometheusQueryTool(client)
    try:
        result = tool.run(query=query)
    except PrometheusQueryError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    console.print_json(data=result)


@tools.command("pod-status")
@click.argument("service")
@click.option("--namespace", default=None, help="Defaults to the configured namespace.")
def tools_pod_status(service: str, namespace: str | None) -> None:
    """Summarize pod restarts and OOM state for a service via kubectl."""
    settings = Settings.from_env()
    client = KubectlClient(
        namespace=namespace or settings.kubectl_namespace,
        context=settings.kubectl_context,
    )
    tool = KubectlPodStatusTool(client)
    try:
        result = tool.run(service=service)
    except KubectlError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    console.print_json(data=result)


@tools.command("logs")
@click.argument("pod_name")
@click.option("--tail", "tail_lines", default=200, show_default=True, help="Number of log lines to fetch.")
@click.option("--previous", is_flag=True, help="Fetch logs from the previous container instance.")
def tools_logs(pod_name: str, tail_lines: int, previous: bool) -> None:
    """Fetch recent logs for a pod via kubectl."""
    settings = Settings.from_env()
    client = KubectlClient(namespace=settings.kubectl_namespace, context=settings.kubectl_context)
    tool = KubectlLogsTool(client)
    try:
        result = tool.run(pod_name=pod_name, tail_lines=tail_lines, previous=previous)
    except KubectlError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    console.print(Panel(result["logs"] or "(no output)", title=f"logs: {pod_name}"))


@tools.command("record-deploy")
@click.argument("service")
@click.argument("version")
@click.option("--previous-version", "previous_version", required=True, help="Version being replaced.")
def tools_record_deploy(service: str, version: str, previous_version: str) -> None:
    """Append a deploy to the local deploy ledger (stands in for a CD webhook)."""
    settings = Settings.from_env()
    store = DeployHistoryStore(settings.deploy_history_path)
    record = store.append(DeployRecord(service=service, version=version, previous_version=previous_version))
    console.print(
        f"[green]Recorded deploy:[/green] {service} {previous_version} -> {version} "
        f"at {record.deployed_at.isoformat(timespec='seconds')}"
    )


@tools.command("deploy-history")
@click.argument("service")
def tools_deploy_history(service: str) -> None:
    """Show the most recent deploy to a service from the deploy ledger."""
    settings = Settings.from_env()
    store = DeployHistoryStore(settings.deploy_history_path)
    tool = DeployHistoryTool(store)
    console.print_json(data=tool.run(service=service))


@tools.command("search-runbooks")
@click.argument("query")
@click.option("--top-k", default=3, show_default=True, help="Maximum number of runbooks to return.")
def tools_search_runbooks(query: str, top_k: int) -> None:
    """Keyword-search the local runbook corpus."""
    settings = Settings.from_env()
    tool = RunbookSearchTool(settings.runbook_dir, top_k=top_k)
    result = tool.run(query=query)
    if not result["matches"]:
        console.print(f"[yellow]No runbook matches for '{query}'.[/yellow]")
        return
    for match in result["matches"]:
        console.print(
            Panel(match["excerpt"], title=f"{match['runbook']} (score={match['score']})")
        )


if __name__ == "__main__":
    main()
