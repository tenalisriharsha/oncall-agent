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
├── llm/
│   ├── base.py          LLMProvider / LLMRequest / LLMResponse contract
│   ├── scripted.py      ScriptedPolicyProvider — deterministic default
│   └── factory.py       get_provider(name) — swap providers from config
├── tools/
│   ├── base.py           Tool / ToolRegistry contract
│   └── fakes.py          FakeRecentDeploysTool, FakePodStatusTool (demo doubles)
└── cli.py               click CLI: version, config, demo, audit
```

The investigation loop is provider- and tool-agnostic: it asks whatever
`LLMProvider` is configured what to do next given the evidence gathered
so far, executes that decision against whatever `Tool`s are registered,
and logs every step to the `AuditTrail` before moving on. Phase 1 wires
this up end to end with a deterministic rule-based provider and two fake
tools; later phases swap in real tool integrations and richer reasoning
without changing this shape.

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

- [ ] **Phase 2 — Real read-only tool integrations**
  - Prometheus query client
  - `kubectl get/describe/logs` client (read-only)
  - Runbook RAG search over a local markdown runbook corpus
  - Deploy/CD history source
  - All implementing the Phase 1 `Tool` interface, swappable with the fakes

- [ ] **Phase 3 — Smarter reasoning**
  - Multi-hypothesis ranking & comparison
  - Re-planning when new evidence contradicts a hypothesis
  - Optional local-model provider (e.g. Ollama) alongside the scripted policy
  - Structured diagnosis report export (markdown/JSON)

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

**Next session: start Phase 2.** Build the real Prometheus and `kubectl`
read-only clients against the existing `Tool` interface in
`src/oncall_agent/tools/base.py` — see `tools/fakes.py` for the shape
those clients need to match. The runbook RAG search and deploy-history
source can follow in the same phase. Keep the fakes around for tests;
real clients should be exercised separately (e.g. integration tests
behind a marker, since they need a live cluster/Prometheus).

STATUS: IN_PROGRESS
