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
incident simulator that injects faults (hand-rolled, not chaos-kit — see
Phase 5 below for why), and a scorecard that measures root-cause
accuracy, action accuracy, and steps taken across six scenarios.

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
├── approval.py           ApprovalGate — CLIApprovalGate, SlackApprovalGate, AutoApprovalGate
├── actions.py            ActionExecutor — kubectl-backed and dry-run (Noop) executors
├── response.py           respond_to_incident — investigation + approval gate + action execution
├── simulator/
│   ├── faults.py          FaultType, FAULT_PROFILES, inject_fault — canned fault evidence
│   ├── scenarios.py        Scenario, SCENARIOS — six incidents, one per runbook, with ground truth
│   ├── runner.py           run_scenario / run_all_scenarios — fires respond_to_incident unattended
│   └── scorecard.py        score_run / build_scorecard — root-cause/action accuracy per provider
└── cli.py               click CLI: version, config, demo, audit, approve, simulate, tools
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

Phase 5 added a layer *next to* the loop, not inside it:
`simulator/runner.py`'s `run_scenario()` builds an `Alert` from a
`Scenario`, injects a `FaultType`'s canned evidence into a fresh
`ToolRegistry` (`simulator/faults.py`'s `inject_fault()`), and calls
`respond_to_incident()` completely unchanged, with an
`AutoApprovalGate` standing in for a human so a whole scenario suite
can run unattended.

Phase 6 added a comparison layer *next to* the simulator, not inside it:
`simulator/scorecard.py`'s `score_run()` compares one `ScenarioRun`'s
actual `Diagnosis.category`/`.action` against its `Scenario`'s
`expected_category`/`expected_action` ground truth (new fields on both
models — `Diagnosis.category` is tagged by the scripted policy on every
branch of `_diagnose()`, mirroring what it already tagged on the leading
hypothesis), and counts the audit trail's `TOOL_CALL`/
`HYPOTHESIS_FORMED`/`HYPOTHESIS_REVISED` events as "steps taken."
`build_scorecard()` aggregates a whole suite into root-cause accuracy,
action accuracy, and step counts; `render_markdown()`/
`render_comparison_markdown()` turn a `Scorecard` (or several, for a
provider comparison) into a standalone document. None of this touches
`run_investigation`, `respond_to_incident`, the scripted policy's control
flow, or any existing scenario's evidence — same purely-additive,
layer-on-top pattern every phase before it used.

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

- [x] **Phase 5 — Incident simulator** (Night 5)
  - `simulator/faults.py`: `FaultType` (one per runbook — `BAD_DEPLOY`,
    `OOM_CRASH_LOOP`, `DEPENDENCY_OUTAGE`, `NETWORK_PARTITION`,
    `DISK_PRESSURE`, `CONFIG_DRIFT`), `FAULT_PROFILES` (the canned
    ground-truth evidence each fault makes the fake tools return), and
    `inject_fault()` — builds a fresh `ToolRegistry` wired to that
    evidence. Hand-rolled rather than built on chaos-kit or any external
    chaos-engineering tool: checked what chaos-kit actually offers before
    starting, and since every existing demo/test already runs against
    canned tool evidence (`tools/fakes.py`) and nothing here needs a live
    cluster to inject a fault into, a dependency stayed unnecessary —
    `FAULT_PROFILES` just describes what a live cluster's tools would
    have reported if that fault were real
  - `simulator/scenarios.py`: `Scenario` (alert + fault type + runbook +
    a ground-truth note) and `SCENARIOS` — six incidents, one per
    runbook in `runbooks/`
  - `simulator/runner.py`: `run_scenario()`/`run_all_scenarios()` — build
    an `Alert` from a `Scenario`, inject its fault, and call
    `respond_to_incident()` (Phase 4) completely unchanged, with an
    `AutoApprovalGate` standing in for a human so a whole suite runs
    unattended. Each `ScenarioRun` carries the full `IncidentResponse`
    plus its audit trail (`events`) — exactly the shape a Phase 6
    scorecard needs (steps taken, revisions, whether it acted)
  - CLI: `oncall-agent simulate list` / `simulate run <name>` /
    `simulate run-all`
  - Of the six scenarios, two are diagnosed precisely by the existing
    scripted policy (bad deploy -> `ROLLBACK`, OOM crash loop ->
    `SCALE`); the other four (dependency outage, network partition, disk
    pressure, config drift) all show no recent deploy and no OOM signal
    — the only failure shape the policy can currently tell apart from
    "deploy caused it" — so all four escalate, correctly for the
    dependency outage and as a safe-but-imprecise fallback for the other
    three. That gap is intentional, documented in each scenario's
    `notes` field, and exactly what Phase 6's scorecard should be able
    to measure rather than paper over
  - Full test suite (200 tests, 99% statement coverage)

- [x] **Phase 6 — Scorecard & polish** (Night 6)
  - `models.py`: `Diagnosis.category` — the category of the hypothesis a
    diagnosis actually concluded from, mirroring `Hypothesis.category`.
    Purely additive (`None` default); `ScriptedPolicyProvider._diagnose()`
    now tags it on every branch, matching the category each branch's own
    `root_cause` text already claimed (including the generic fallback
    branch, which claims "downstream dependency failure" regardless of
    whether the leading hypothesis was ever revised to that category —
    tagging the diagnosis directly sidesteps that existing mismatch rather
    than inheriting it)
  - `simulator/scenarios.py`: every `Scenario` gained `expected_category`/
    `expected_action` — ground-truth labels a scorecard compares the
    actual diagnosis against. Three reuse the scripted policy's own
    category constants (the faults it's built to recognize); the other
    three (`network_partition`, `disk_pressure`, `config_drift`) are true
    causes the policy has no dedicated signal for yet, so the scorecard
    can show the gap numerically instead of the policy's generic fallback
    silently "passing"
  - `simulator/scorecard.py`: `score_run()` (one scenario vs. its ground
    truth: category match, action match, steps taken, revisions),
    `build_scorecard()` (aggregates a suite: root-cause accuracy, action
    accuracy, total/average steps), `render_markdown()`/
    `render_comparison_markdown()` (standalone report, and a provider vs.
    provider comparison)
  - CLI: `oncall-agent simulate scorecard [--provider scripted|ollama]
    [--report PATH] [--audit-log PATH]` and `oncall-agent simulate
    compare [--report PATH] [--audit-log PATH]` — the latter always
    scores the scripted policy and also scores `OllamaProvider` if a
    local Ollama server answers at the configured URL, falling back to
    scripted-only with a printed warning (not a crash) if it doesn't
  - Measured result against the scripted policy today: **50% root-cause
    accuracy (3/6)** but **100% action accuracy (6/6)** — it never
    proposes a wrong destructive action, even on the three scenarios it
    mislabels, because the fallback for "no dedicated signal" is always
    `ESCALATE`, never a guess. This is exactly the gap Phase 5's notes
    predicted a scorecard should surface numerically
  - "Cost per scenario" is measured as step count (tool calls + hypotheses
    formed/revised from the audit trail), not token cost — the scripted
    policy has no token cost, and `OllamaProvider`'s would need a real
    local model running to measure honestly (still untested against one;
    see below)
  - Full test suite (216 tests, 99% statement coverage)

## Where to resume

All six planned phases are complete. There is no next phase queued;
everything below is optional future work, not a blocker for this
project's stated scope (see `DAILY_REPORT.md` for the full summary and
known limitations). If picked back up, the most natural next steps, in
rough order of value, are:

1. Close the root-cause gap the Phase 6 scorecard measures: give
   `disk_pressure`/`network_partition`/`config_drift` their own
   `Hypothesis.category` and a dedicated tool signal to detect them,
   following the same pattern Phase 3 used for
   `deploy_regression`/`resource_exhaustion`/`dependency_failure`. The
   scorecard now shows exactly how much this would move the number
   (50% → up to 100% root-cause accuracy) without needing to guess.
2. Wire the real Phase 2 tools (`tools/prometheus.py`,
   `tools/kubectl.py`, `tools/runbooks.py`, `tools/deploys.py`) and
   Phase 4's `ActionRegistry.kubectl(...)` into a "live" investigation
   mode, as an alternative to `demo`/`simulate`'s fake/canned evidence.
   Both are already built and tested standalone (`oncall-agent tools
   <name>`); nothing about the `Tool`/`ActionExecutor` interfaces needs
   to change for this, only a new entry point that registers them
   instead of the fakes.
3. Smoke-test `OllamaProvider` against a real local Ollama server
   (`ONCALL_AGENT_LLM_PROVIDER=ollama oncall-agent demo`, or
   `oncall-agent simulate compare` once one is running) — it has only
   ever been exercised against a mocked HTTP boundary, so the prompt in
   `llm/ollama.py` has had no real-model tuning.
4. Wire a real Slack Events API endpoint behind `oncall-agent approve`
   (currently a manual CLI stand-in for the button click) if this ever
   needs to run against an actual Slack workspace instead of the local
   `SlackDecisionInbox` file.
5. Add integration tests against a live Prometheus/cluster (the
   `integration` pytest marker is registered in `pyproject.toml` but
   unused) if/when one becomes available to test against; they should
   stay skipped by default.

STATUS: COMPLETE

## Build history (moved from README)

This project is being built in public, one night at a time. See
[`PROGRESS.md`](PROGRESS.md) for the full architecture, the phased build
plan, and exactly where work left off.

**Current phase: Phases 1–6 are complete** — domain models, an
append-only audit trail, a pluggable LLM provider interface with a
deterministic scripted policy, the investigate → hypothesize →
diagnose loop, real Prometheus/kubectl/runbook/deploy-history clients
alongside the original fakes, multi-hypothesis ranking with
contradiction-triggered re-planning, an optional local-model provider
(Ollama), structured diagnosis report export (Markdown/JSON), a human
approval gate (CLI prompt and Slack) in front of every state-changing
action, action executors that only run once a human has said yes, an
incident simulator that fires six fault-injected scenarios through the
full investigate → approve → act loop unattended, a scorecard that
scores every scenario's diagnosis against ground truth (root-cause
accuracy, action accuracy, steps taken) and compares providers, and a
CLI, all backed by a full test suite. See [`DAILY_REPORT.md`](DAILY_REPORT.md)
for a night-by-night summary, test results, and known limitations.
