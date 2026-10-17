# oncall-agent — build log

## Vision

An agentic SRE incident responder that works like an on-call engineer:
given an alert, it forms hypotheses, calls read-only tools (Prometheus
queries, `kubectl get/describe/logs`, a runbook RAG search, recent
deploys), revises its plan from the results, and ends with a root-cause
diagnosis plus a proposed fix.

Every state-changing action (restart, rollback, scale) is blocked behind
a human approval gate — CLI and Slack — and every step the agent takes
is written to an append-only audit trail. The project ships with an
incident simulator that uses chaos-kit to inject faults, and a scorecard
that measures root-cause accuracy, steps taken, and cost per scenario
across 5-6 scenarios.

LLM access is a pluggable provider: a scripted, deterministic policy for
tests and CI (no paid API key, no network access required), with
optional local-model support planned. Python, fully tested.

## Architecture

```
src/oncall_agent/
├── models.py          Alert, Hypothesis, Diagnosis, ToolCallRecord, AuditEvent
├── audit.py            AuditTrail — append-only JSON-lines audit log
├── config.py            Settings — env-driven configuration (ONCALL_AGENT_*)
├── investigation.py    the investigate -> hypothesize -> diagnose loop
├── reasoning.py         rank_hypotheses / current_hypothesis — multi-hypothesis comparison
├── report.py             export_report — Markdown/JSON diagnosis report export
├── llm/
│   ├── base.py          LLMProvider / LLMRequest / LLMResponse contract
│   ├── scripted.py      ScriptedPolicyProvider — deterministic default, re-plans on contradiction
│   ├── ollama.py         OllamaProvider — optional local-model backend
│   └── factory.py       get_provider(name, **kwargs) — swap providers from config
├── tools/
│   ├── base.py           Tool / ToolRegistry contract
│   ├── fakes.py          FakeRecentDeploysTool, FakePodStatusTool (demo doubles)
│   ├── prometheus.py     PrometheusClient / PrometheusQueryTool — read-only PromQL
│   ├── kubectl.py        KubectlClient — get/describe/logs only, refuses anything else
│   ├── deploys.py        DeployHistoryStore/Tool — append-only deploy ledger
│   └── runbooks.py       RunbookSearchTool — keyword search over runbooks/*.md
└── cli.py               click CLI: version, config, demo, audit, tools
```

The investigation loop is provider- and tool-agnostic: it asks whatever
`LLMProvider` is configured what to do next given the evidence gathered
so far, executes that decision against whatever `Tool`s are registered,
and logs every step to the `AuditTrail` before moving on. Phase 1 wired
this up end to end with a deterministic rule-based provider and two fake
tools; Phase 2 added real tool implementations behind the same `Tool`
interface, so the loop's shape never changed. Phase 3 added a second
`LLMProvider` (`OllamaProvider`) behind the same contract, plus a
re-planning step inside the scripted policy itself — the loop's shape
still never changed; a revision is just another `FORM_HYPOTHESIS`
response with `is_revision=True`. The `demo` CLI command still uses the
fakes (deterministic, needed for reproducible scenarios and
screenshots); the real clients are reachable directly via
`oncall-agent tools <name>` and are built to be registered into the
same `ToolRegistry` the loop reads from once a "live" investigation
mode needs live evidence instead of canned evidence.

Phase 4 added a layer *above* the loop rather than inside it:
`response.respond_to_incident()` calls `run_investigation()` completely
unchanged, then — only if the resulting `Diagnosis.action` is a
mutating one — asks an `ApprovalGate` (`approval.py`: `CLIApprovalGate`,
`SlackApprovalGate`, `AutoApprovalGate`) and, once approved, hands the
action to an `ActionRegistry` (`actions.py`: kubectl-backed executors or
a dry-run `NoopActionExecutor` registry) via `execute_action()`, which
refuses anything without an `APPROVED` decision and always logs the
outcome. `run_investigation()` itself has zero awareness any of this
exists — same pattern Phase 3 used for re-planning.

## Phased build plan

- [x] **Phase 1 — Scaffold & core foundation** (Night 1)
  - Project scaffold (`pyproject.toml`, package layout, CI workflow)
  - Domain models: `Alert`, `Hypothesis`, `Diagnosis`, `ToolCallRecord`, `AuditEvent`
  - Append-only audit trail (`AuditTrail`, JSON-lines)
  - Env-driven configuration (`Settings`)
  - Pluggable LLM provider interface + `ScriptedPolicyProvider` (deterministic, default, no API key)
  - Read-only tool interface + fake demo tools (`get_recent_deploys`, `get_pod_status`)
  - The investigate -> hypothesize -> diagnose loop (`run_investigation`)
  - CLI: `version`, `config`, `demo` (3 canned scenarios), `audit`
  - Full test suite (44 tests, 99% statement coverage)

- [x] **Phase 2 — Real read-only tool integrations** (Night 2)
  - Prometheus query client (`PrometheusClient`/`PrometheusQueryTool`) over the standard `/api/v1/query` HTTP API
  - `kubectl get/describe/logs` client (`KubectlClient`) — a single chokepoint refuses any subcommand outside `get`/`describe`/`logs`, so nothing here can mutate a cluster
  - Runbook keyword search (`RunbookSearchTool`) over a 6-runbook markdown corpus in `runbooks/` (one per Phase 5 scenario), dependency-free and deterministic
  - Deploy/CD history source (`DeployHistoryStore`/`DeployHistoryTool`) — an append-only JSON-lines ledger, same shape as the audit trail, standing in for a CD webhook history
  - All four implement the Phase 1 `Tool` interface and are drop-in swappable with the fakes
  - New `Settings` fields (`prometheus_url`, `kubectl_namespace`, `kubectl_context`, `runbook_dir`, `deploy_history_path`), all env-driven
  - New CLI group `oncall-agent tools` (`query-prometheus`, `pod-status`, `logs`, `search-runbooks`, `record-deploy`, `deploy-history`) to call any real tool directly
  - Unit tests mock the HTTP/subprocess boundary (`requests.get`, `subprocess.run`) so the suite needs no live Prometheus or cluster; `KubectlClient`'s runner is resolved at construction time (not bound as a import-time default) specifically so tests can monkeypatch `subprocess.run` safely
  - Full test suite (91 tests, 99% statement coverage)

- [x] **Phase 3 — Smarter reasoning** (Night 3)
  - `reasoning.py`: `rank_hypotheses()` (confidence-ranked, for comparison/reporting) and
    `current_hypothesis()` (most recent — the standing belief, which may have superseded
    an earlier one)
  - `Hypothesis.category` (optional tag: `deploy_regression`, `resource_exhaustion`,
    `dependency_failure`) and `Diagnosis.hypotheses_considered` (ranked list attached to
    every diagnosis) added to the domain models
  - `ScriptedPolicyProvider` re-plans once: if pod health shows zero restarts and no OOM
    signal — flatly contradicting a deploy-based hypothesis — it revises toward a
    dependency-failure hypothesis instead of diagnosing on a hunch that evidence just
    disproved. A new `EventType.HYPOTHESIS_REVISED` audit event (and
    `LLMResponse.is_revision`) distinguishes a revision from a first guess in the trail.
    Purely additive: every Phase 1/2 decision path and test is byte-for-byte unchanged
    because the revision check only fires on hypotheses the scripted policy itself
    tagged with a category
  - `llm/ollama.py`: `OllamaProvider`, an optional local-model backend satisfying the
    same `LLMProvider` contract — posts to a local Ollama server's `/api/generate` and
    parses the model's JSON reply into an `LLMResponse`. Not the default; registered in
    `llm/factory.py` as `"ollama"` (the scripted policy stays default so tests/CI stay
    network-free). `get_provider()` now forwards `**kwargs` to the provider constructor
    so `base_url`/`model` can be set
  - New `Settings` fields `ollama_url`/`ollama_model` (env-driven, same pattern as the
    rest); `oncall-agent config` now shows every resolved setting, not just two
  - `report.py`: `export_report()` renders a completed investigation (alert + diagnosis
    + ranked hypotheses) as standalone Markdown or JSON. Wired into the CLI via
    `oncall-agent demo --report PATH [--report-format markdown|json]`
  - Full test suite (136 tests, 99% statement coverage)

- [x] **Phase 4 — Human approval gate** (Night 4)
  - `models.py`: `ActionType` (`restart`/`rollback`/`scale`/`escalate`),
    `Diagnosis.action`/`action_arguments` (the machine-actionable shape of
    `proposed_fix`), `ApprovalDecision`, `ActionResult`, `IncidentResponse`,
    and a new `EventType.ACTION_EXECUTED`
  - `ScriptedPolicyProvider` now tags every diagnosis with the `ActionType`
    its `proposed_fix` implies: deploy regression -> `ROLLBACK` (to the
    previous version), OOM -> `SCALE` (replica bump), anything that
    escalates to a human (dependency failure, or no signal at all) ->
    `ESCALATE` — the one action type that never needs approval, since it
    never mutates anything
  - `approval.py`: `ApprovalGate` contract plus three implementations —
    `CLIApprovalGate` (blocking y/n terminal prompt), `AutoApprovalGate`
    (approves immediately, for scripted/CI runs), and `SlackApprovalGate`
    (posts to a Slack webhook, or prints if none is configured, then polls
    a `SlackDecisionInbox` — a JSON-lines file standing in for what a real
    Slack Events API handler would append to on a button click)
  - `actions.py`: `ActionExecutor` contract, `KubectlMutationClient` (a
    second, narrower kubectl chokepoint restricted to `rollout`/`scale` —
    deliberately a separate class from the read-only `tools/kubectl.py`
    client so that client's "nothing here can mutate a cluster" guarantee
    stays true for every existing caller), `RestartActionExecutor`/
    `RollbackActionExecutor`/`ScaleActionExecutor`, a dry-run
    `NoopActionExecutor` (what `demo` uses, since its evidence is fake),
    `ActionRegistry`, and `execute_action()` — the single chokepoint that
    refuses to run anything without an `APPROVED` decision and always logs
    the outcome (success or failure) to the audit trail
  - `response.py`: `respond_to_incident()` — investigate, then gate any
    actionable fix on approval, then execute if approved. A pure wrapper
    around the unchanged `run_investigation()`, same layering Phase 3 used
  - CLI: `oncall-agent demo --approval {skip,cli,auto}` (default `skip`,
    so every pre-Phase-4 `demo` invocation is byte-for-byte unchanged) and
    a new `oncall-agent approve <incident-id> --approver NAME [--reject]
    [--reason TEXT]` command — the manual stand-in for the Slack button
    click, writing to the same decision inbox `SlackApprovalGate` polls
  - New `Settings` fields `slack_webhook_url`/`slack_decision_inbox_path`
  - Full test suite (185 tests, 99% statement coverage)

- [ ] **Phase 5 — Incident simulator**
  - chaos-kit-based fault injection
  - 5-6 scenario definitions (bad deploy, OOM, dependency outage, network partition, disk pressure, config drift)
  - Scenario runner that fires alerts against injected faults and lets the agent investigate

- [ ] **Phase 6 — Scorecard & polish**
  - Root-cause accuracy, steps taken, and cost per scenario across the simulator
  - Comparison report across providers (scripted vs. local model)
  - Final docs/README polish and packaging

## Where to resume

**Next session: start Phase 5 — incident simulator.** This needs a
fault-injection mechanism (chaos-kit or a hand-rolled equivalent — worth
checking what chaos-kit actually gives you before committing to the
dependency, since the whole rest of this project has stayed
dependency-light on purpose) and 5-6 scenario definitions (bad deploy,
OOM, dependency outage, network partition, disk pressure, config drift
— the `runbooks/` corpus already has one markdown runbook per scenario
from Phase 2, which is a reasonable source of truth for what each
scenario should actually inject). The scenario runner fires an `Alert`
against the injected fault and lets `respond_to_incident()` (Phase 4)
investigate and act on it end to end, auto-approving
(`AutoApprovalGate`) so the simulator can run unattended.

The real Phase 2 tools (`tools/prometheus.py`, `tools/kubectl.py`,
`tools/runbooks.py`, `tools/deploys.py`) are still only reachable
standalone via `oncall-agent tools <name>` — not yet wired into
`run_investigation`/the `demo` command, since `demo` needs
deterministic, canned evidence for reproducible scenarios and
screenshots. The simulator is exactly the place this finally matters:
each scenario should inject a fault into *real* state (a local
Prometheus, a kind/minikube cluster, or fakes dressed up to look like
them) and register the real tools into a `ToolRegistry`, not the fakes
`demo` uses. Phase 4's `ActionRegistry.kubectl(...)` (real, kubectl-
backed executors) is already built for this and currently unused
outside its own tests — the simulator is its first real caller.

The scripted policy's re-planning (Phase 3) only revises once, and only
when pod health shows *zero* signal at all (no restarts, no OOM) — a
deliberately narrow trigger chosen so every Phase 1/2 test fixture
(which builds `Hypothesis` objects without a `category`) stays
untouched. The same pattern — tag hypotheses with `category`, check
`current_hypothesis(...)` before acting on one — is the way to add more
contradiction checks as the simulator's scenarios exercise paths the
scripted policy doesn't handle well yet (e.g. network partition and
config drift have no dedicated category today; they'll fall through to
the generic "no deploy, no OOM -> escalate" branch, which may or may not
be the right call once there's a scenario actually testing it).

`SlackApprovalGate` (Phase 4) is tested only against a mocked
`requests.post` and a `SlackDecisionInbox` file — there is no real
Slack Events API endpoint behind `oncall-agent approve`, by design (that
would need a hosted webhook receiver, out of scope for a local-only
project). If a real Slack app ever gets wired up, it should append to
the same `SlackDecisionInbox` shape `approve` already writes.

`OllamaProvider` (Phase 3) is untested against a real Ollama server —
only against a mocked HTTP boundary, same pattern as the Prometheus/
kubectl clients. If a local Ollama install becomes available to
develop against, worth a manual smoke test (`ONCALL_AGENT_LLM_PROVIDER=
ollama oncall-agent demo`) to see how a real model's output quality
compares to the scripted policy's canned decision tree — the prompt in
`llm/ollama.py` has had no real-model tuning yet.

No integration tests against a live Prometheus/cluster exist yet
(the `integration` pytest marker is registered in `pyproject.toml` but
unused) — add them if/when a live cluster or Prometheus becomes
available to test against; they should stay skipped by default. Phase 5
is the first phase where that marker is likely to actually get used.

STATUS: IN_PROGRESS
