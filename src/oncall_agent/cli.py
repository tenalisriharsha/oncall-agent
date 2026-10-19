"""Command-line entry point.

Phase 1 ships four commands: ``version`` and ``config`` for sanity
checks, ``demo`` to run a full canned investigation end to end with the
scripted policy and fake tools, and ``audit`` to inspect the trail that
investigation left behind.
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .actions import ActionRegistry
from .approval import AutoApprovalGate, CLIApprovalGate, SlackDecisionInbox
from .audit import AuditTrail
from .config import Settings
from .investigation import run_investigation
from .llm import get_provider
from .llm.ollama import OllamaProviderError
from .models import Alert, ApprovalDecision, ApprovalStatus, Severity
from .report import REPORT_FORMATS, export_report
from .response import respond_to_incident
from .simulator import SCENARIOS as SIM_SCENARIOS
from .simulator import (
    Scorecard,
    ScenarioRun,
    build_scorecard,
    get_scenario,
    render_comparison_markdown,
    render_scorecard_markdown,
    run_all_scenarios,
    run_scenario,
)
from .tools import FakePodStatusTool, FakeRecentDeploysTool, ToolRegistry
from .tools.deploys import DeployHistoryStore, DeployHistoryTool, DeployRecord
from .tools.kubectl import KubectlClient, KubectlError, KubectlLogsTool, KubectlPodStatusTool
from .tools.prometheus import PrometheusClient, PrometheusQueryError, PrometheusQueryTool
from .tools.runbooks import RunbookSearchTool

APPROVAL_GATES = ("skip", "auto", "cli")

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
    table.add_row("slack_webhook_url", settings.slack_webhook_url or "(not configured)")
    table.add_row("slack_decision_inbox_path", str(settings.slack_decision_inbox_path))
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
@click.option(
    "--approval",
    "approval_gate_name",
    type=click.Choice(APPROVAL_GATES),
    default="skip",
    show_default=True,
    help=(
        "Gate any proposed mutating action on human approval: 'skip' stops at the "
        "diagnosis like before, 'cli' prompts at this terminal, 'auto' approves "
        "immediately (no human, for scripted runs)."
    ),
)
def demo(
    scenario: str,
    audit_log_path: str | None,
    report_path: str | None,
    report_format: str,
    approval_gate_name: str,
) -> None:
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

    if approval_gate_name == "skip":
        diagnosis = run_investigation(alert, provider, tools, audit)
        approval = None
        action_result = None
    else:
        approval_gate = (
            CLIApprovalGate() if approval_gate_name == "cli" else AutoApprovalGate()
        )
        response = respond_to_incident(
            alert, provider, tools, audit, approval_gate, action_registry=ActionRegistry.noop()
        )
        diagnosis = response.diagnosis
        approval = response.approval
        action_result = response.action_result

    _print_diagnosis(diagnosis, approval, action_result)
    console.print(f"[dim]Audit trail written to {log_path}[/dim]")

    if report_path:
        written = export_report(alert, diagnosis, report_path, fmt=report_format)
        console.print(f"[dim]Diagnosis report written to {written}[/dim]")


def _print_diagnosis(diagnosis, approval, action_result) -> None:
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

    if approval is not None:
        style = "green" if approval.status == ApprovalStatus.APPROVED else "red"
        approval_body = f"[bold]Status:[/bold] {approval.status.value}\n[bold]Approver:[/bold] {approval.approver}"
        if approval.reason:
            approval_body += f"\n[bold]Reason:[/bold] {approval.reason}"
        console.print(Panel(approval_body, title="Approval", border_style=style))

    if action_result is not None:
        style = "green" if action_result.success else "red"
        action_body = (
            f"[bold]Action:[/bold] {action_result.action.value}\n"
            f"[bold]Success:[/bold] {action_result.success}\n"
            f"[bold]Output:[/bold] {action_result.output}"
        )
        console.print(Panel(action_body, title="Action executed", border_style=style))


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


@main.command(name="approve")
@click.argument("incident_id")
@click.option("--approver", required=True, help="Who is recording this decision.")
@click.option(
    "--reject",
    is_flag=True,
    help="Reject the action instead of approving it (default is approve).",
)
@click.option("--reason", default="", help="Optional reason, especially useful for a rejection.")
@click.option(
    "--inbox",
    "inbox_path",
    default=None,
    help="Slack decision inbox to write to. Defaults to the configured path.",
)
def approve_cmd(incident_id: str, approver: str, reject: bool, reason: str, inbox_path: str | None) -> None:
    """Record a human approval decision for an incident awaiting one.

    This is the manual stand-in for clicking "Approve"/"Reject" on a
    Slack message: a real Slack app would append to this same inbox from
    its Events API callback. A `SlackApprovalGate` polling that incident
    picks the decision up and unblocks.
    """
    settings = Settings.from_env()
    path = inbox_path or str(settings.slack_decision_inbox_path)
    inbox = SlackDecisionInbox(path)
    decision = ApprovalDecision(
        incident_id=incident_id,
        status=ApprovalStatus.REJECTED if reject else ApprovalStatus.APPROVED,
        approver=approver,
        reason=reason,
    )
    inbox.record(decision)
    verb = "Rejected" if reject else "Approved"
    console.print(f"[green]{verb}[/green] incident {incident_id} as {approver}.")


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


@main.group()
def simulate() -> None:
    """Fire the incident simulator's fault-injected scenarios at the agent."""


@simulate.command("list")
def simulate_list() -> None:
    """List the simulator's scenarios and the fault each one injects."""
    table = Table(title="Incident simulator scenarios")
    table.add_column("name", no_wrap=True)
    table.add_column("severity")
    table.add_column("runbook", no_wrap=True)
    for scenario in SIM_SCENARIOS:
        table.add_row(scenario.name, scenario.severity.value, scenario.runbook)
    console.print(table)


@simulate.command("run")
@click.argument("scenario_name")
@click.option(
    "--audit-log",
    "audit_log_path",
    default=None,
    help="Where to append the audit trail. Defaults to .oncall-agent/simulator.jsonl.",
)
def simulate_run(scenario_name: str, audit_log_path: str | None) -> None:
    """Fire one scenario's injected fault through the full agent + approval loop."""
    try:
        scenario = get_scenario(scenario_name)
    except KeyError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)

    run = run_scenario(scenario, audit_log_path=audit_log_path)
    console.print(
        Panel(
            f"[bold]{run.alert.title}[/bold]\n{run.alert.description}\n"
            f"service={run.alert.service} severity={run.alert.severity.value}\n"
            f"[dim]fault injected: {scenario.fault_type.value}[/dim]",
            title=f"Scenario '{scenario.name}' — Alert {run.alert.id}",
        )
    )
    _print_diagnosis(run.response.diagnosis, run.response.approval, run.response.action_result)
    console.print(f"[dim]{scenario.notes}[/dim]")


@simulate.command("run-all")
@click.option(
    "--audit-log",
    "audit_log_path",
    default=None,
    help="Where to append the audit trail. Defaults to .oncall-agent/simulator.jsonl.",
)
def simulate_run_all(audit_log_path: str | None) -> None:
    """Fire every scenario and print a one-line summary of each outcome."""
    table = Table(title="Incident simulator results")
    table.add_column("scenario", no_wrap=True)
    table.add_column("action", no_wrap=True)
    table.add_column("confidence", no_wrap=True)
    table.add_column("root cause", no_wrap=True)
    for scenario in SIM_SCENARIOS:
        run: ScenarioRun = run_scenario(scenario, audit_log_path=audit_log_path)
        diagnosis = run.response.diagnosis
        table.add_row(
            scenario.name,
            diagnosis.action.value if diagnosis.action else "(none)",
            f"{diagnosis.confidence:.2f}",
            _truncate(diagnosis.root_cause, 40),
        )
    console.print(table)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


@simulate.command("scorecard")
@click.option(
    "--provider",
    "provider_name",
    type=click.Choice(["scripted", "ollama"]),
    default="scripted",
    show_default=True,
    help="LLM provider to score every scenario against.",
)
@click.option(
    "--report",
    "report_path",
    default=None,
    help="If given, write the scorecard as Markdown to this path.",
)
@click.option(
    "--audit-log",
    "audit_log_path",
    default=None,
    help="Where to append the audit trail. Defaults to .oncall-agent/simulator.jsonl.",
)
def simulate_scorecard(provider_name: str, report_path: str | None, audit_log_path: str | None) -> None:
    """Score every scenario's diagnosis against ground truth.

    Reports root-cause accuracy (did the diagnosis's category match the
    scenario's true cause), action accuracy (was the proposed action still
    safe even when the cause was mislabeled), and steps taken per scenario.
    """
    settings = Settings.from_env()
    provider = (
        get_provider("ollama", base_url=settings.ollama_url, model=settings.ollama_model)
        if provider_name == "ollama"
        else get_provider("scripted")
    )
    try:
        runs = run_all_scenarios(provider=provider, audit_log_path=audit_log_path)
    except OllamaProviderError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)

    scorecard = build_scorecard(runs, provider=provider_name)
    _print_scorecard(scorecard)

    if report_path:
        Path(report_path).write_text(render_scorecard_markdown(scorecard), encoding="utf-8")
        console.print(f"[dim]Scorecard written to {report_path}[/dim]")


def _print_scorecard(scorecard: Scorecard) -> None:
    table = Table(title=f"Incident simulator scorecard — provider: {scorecard.provider}")
    table.add_column("scenario", no_wrap=True)
    table.add_column("expected cause")
    table.add_column("actual cause")
    table.add_column("cause", justify="center")
    table.add_column("expected action")
    table.add_column("actual action")
    table.add_column("action", justify="center")
    table.add_column("steps", justify="right")
    for score in scorecard.scores:
        table.add_row(
            score.scenario,
            score.expected_category,
            score.actual_category or "(none)",
            "[green]match[/green]" if score.category_match else "[red]MISS[/red]",
            score.expected_action.value,
            score.actual_action.value if score.actual_action else "(none)",
            "[green]match[/green]" if score.action_match else "[red]MISS[/red]",
            str(score.steps),
        )
    console.print(table)
    console.print(
        f"[bold]Root-cause accuracy:[/bold] {scorecard.root_cause_accuracy:.0%}  "
        f"[bold]Action accuracy:[/bold] {scorecard.action_accuracy:.0%}  "
        f"[bold]Total steps:[/bold] {scorecard.total_steps}  "
        f"[bold]Avg steps/scenario:[/bold] {scorecard.average_steps:.1f}"
    )


@simulate.command("compare")
@click.option(
    "--report",
    "report_path",
    default=None,
    help="If given, write the comparison as Markdown to this path.",
)
@click.option(
    "--audit-log",
    "audit_log_path",
    default=None,
    help="Where to append the audit trail. Defaults to .oncall-agent/simulator.jsonl.",
)
def simulate_compare(report_path: str | None, audit_log_path: str | None) -> None:
    """Compare the scripted policy against the optional Ollama provider.

    Always scores the scripted policy. Also scores the Ollama provider if
    a local Ollama server is reachable at the configured URL; otherwise
    prints a warning and compares against the scripted policy alone.
    """
    settings = Settings.from_env()
    scripted_runs = run_all_scenarios(provider=get_provider("scripted"), audit_log_path=audit_log_path)
    scorecards = [build_scorecard(scripted_runs, provider="scripted")]

    ollama_provider = get_provider("ollama", base_url=settings.ollama_url, model=settings.ollama_model)
    try:
        ollama_runs = run_all_scenarios(provider=ollama_provider, audit_log_path=audit_log_path)
    except OllamaProviderError as exc:
        console.print(f"[yellow]Ollama provider unavailable, comparing against scripted only: {exc}[/yellow]")
    else:
        scorecards.append(build_scorecard(ollama_runs, provider="ollama"))

    table = Table(title="Provider comparison")
    table.add_column("provider", no_wrap=True)
    table.add_column("root-cause accuracy")
    table.add_column("action accuracy")
    table.add_column("total steps")
    table.add_column("avg steps/scenario")
    for scorecard in scorecards:
        table.add_row(
            scorecard.provider,
            f"{scorecard.root_cause_accuracy:.0%}",
            f"{scorecard.action_accuracy:.0%}",
            str(scorecard.total_steps),
            f"{scorecard.average_steps:.1f}",
        )
    console.print(table)

    if report_path:
        Path(report_path).write_text(render_comparison_markdown(scorecards), encoding="utf-8")
        console.print(f"[dim]Comparison written to {report_path}[/dim]")


if __name__ == "__main__":
    main()
