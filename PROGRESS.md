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
mode (Phase 4+) needs live evidence instead of canned evidence.

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

- [ ] **Phase 4 — Human approval gate**
  - Every state-changing action (restart, rollback, scale) blocked pending approval
  - CLI approval prompt
  - Slack approval integration
  - Action executors for approved fixes
  - Approval decisions themselves written to the audit trail

- [ ] **Phase 5 — Incident simulator**
  - chaos-kit-based fault injection
  - 5-6 scenario definitions (bad deploy, OOM, dependency outage, network partition, disk pressure, config drift)
  - Scenario runner that fires alerts against injected faults and lets the agent investigate

- [ ] **Phase 6 — Scorecard & polish**
  - Root-cause accuracy, steps taken, and cost per scenario across the simulator
  - Comparison report across providers (scripted vs. local model)
  - Final docs/README polish and packaging

## Where to resume

**Next session: start Phase 4 — human approval gate.** Diagnoses
already carry `requires_approval: bool` (always `True` today) but
nothing currently blocks on it — the loop returns the `Diagnosis` and
stops. Phase 4 should add an approval step after `DIAGNOSE` for any
proposed fix that's actually state-changing: a CLI prompt first (ask
y/n, log the decision), a Slack integration second, and then
"action executors" that are only allowed to run once a human has said
yes, with the approval decision itself written to the audit trail
(`EventType.APPROVAL_REQUESTED`/`APPROVAL_DECIDED` already exist in
`models.py`, unused since Phase 1 — this is what they're for).

The scripted policy's re-planning (Phase 3) only revises once, and only
when pod health shows *zero* signal at all (no restarts, no OOM) — a
deliberately narrow trigger chosen so every Phase 1/2 test fixture
(which builds `Hypothesis` objects without a `category`) stays
untouched. If Phase 4 or later adds more tool types, the same pattern
— tag hypotheses with `category`, check `current_hypothesis(...)` before
acting on one — is the way to add more contradiction checks without
risking the existing ones.

The real Phase 2 tools (`tools/prometheus.py`, `tools/kubectl.py`,
`tools/runbooks.py`, `tools/deploys.py`) are currently only reachable
standalone via `oncall-agent tools <name>` — they are not yet wired
into `run_investigation`/the `demo` command, since `demo` still needs
deterministic, canned evidence for reproducible scenarios and
screenshots. Wiring a "live" investigation mode that registers the
real tools into a `ToolRegistry` instead of the fakes is reasonable
scope for Phase 4+, once an approval gate exists to stop that live mode
from ever acting on a cluster unsupervised.

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
available to test against; they should stay skipped by default.

STATUS: IN_PROGRESS
