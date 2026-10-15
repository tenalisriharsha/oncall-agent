# oncall-agent

An agentic SRE incident responder. Given an alert, it investigates like
an on-call engineer would: form a hypothesis, call a read-only tool,
revise the hypothesis from what came back, and keep going until it can
state a root cause and a proposed fix — with every step written to an
audit trail and every state-changing action blocked behind human
approval.

## Project Status

This project is being built in public, one night at a time. See
[`PROGRESS.md`](PROGRESS.md) for the full architecture, the phased build
plan, and exactly where work left off.

**Current phase:** Phase 1 (scaffold + core foundation) and Phase 2
(real read-only tool integrations) are complete — domain models, an
append-only audit trail, a pluggable LLM provider interface with a
deterministic scripted policy, the investigate → hypothesize →
diagnose loop, real Prometheus/kubectl/runbook/deploy-history clients
alongside the original fakes, and a CLI, all backed by a full test
suite.

## Preview

All screenshots below are real terminal output from the commands shown
— nothing hand-typed or edited.

**`oncall-agent --help`** — the four Phase 1 commands:

![CLI help](docs/screenshots/01-cli-help.png)

**`oncall-agent config`** — resolved settings, scripted provider by default:

![Resolved configuration](docs/screenshots/02-config.png)

**`oncall-agent demo --scenario deploy-regression`** — a recent deploy drives the diagnosis toward a rollback:

![Deploy-regression scenario](docs/screenshots/03-demo-deploy-regression.png)

**`oncall-agent demo --scenario oom`** — no recent deploy, pods OOMKilled, fix is to scale up:

![OOM scenario](docs/screenshots/04-demo-oom.png)

**`oncall-agent demo --scenario unknown`** — neither signal present, low-confidence diagnosis that escalates to a human:

![Unknown-cause scenario](docs/screenshots/05-demo-unknown.png)

**`oncall-agent audit`** — the full audit trail across all three runs above, step by step:

![Audit trail](docs/screenshots/06-audit-trail.png)

**`oncall-agent demo --scenario bogus`** — invalid input is rejected before anything runs:

![Invalid scenario error](docs/screenshots/07-demo-invalid-scenario.png)

## Why this exists

Real incident response is a loop: look at evidence, form a theory, look
at more evidence, revise the theory, eventually act. Most "AI SRE" demos
skip straight to "and then it fixes it," which is exactly the part that
should never happen without a human saying yes. This project is built
around that constraint from day one: the agent can look at anything
read-only, but every mutating action — restart, rollback, scale — stops
and waits for an explicit approval, logged alongside everything else.

It also doesn't assume you have a paid LLM API key. The default
provider is a deterministic, rule-based policy that needs no network
access at all, which is what tests and CI run against. A real model —
hosted or local — is a pluggable alternative, not a requirement.

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
│   ├── fakes.py          FakeRecentDeploysTool, FakePodStatusTool (demo doubles)
│   ├── prometheus.py     PrometheusClient / PrometheusQueryTool — read-only PromQL
│   ├── kubectl.py        KubectlClient — get/describe/logs only, never a write
│   ├── deploys.py        DeployHistoryStore/Tool — append-only deploy ledger
│   └── runbooks.py       RunbookSearchTool — keyword search over runbooks/*.md
└── cli.py               click CLI: version, config, demo, audit, tools
```

`tools/` ships two implementations of the same `Tool` interface: the
Phase 1 fakes (deterministic, used by `demo` and most tests) and the
Phase 2 real clients (`prometheus.py`, `kubectl.py`, `deploys.py`,
`runbooks.py`), reachable directly via `oncall-agent tools <name>`.
Both sides of that interface are interchangeable — nothing above the
`Tool` contract needs to know or care which one it's holding.

Full phase-by-phase plan (richer reasoning, the Slack approval gate,
the chaos-kit simulator, the scorecard) is in
[`PROGRESS.md`](PROGRESS.md).

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Requires Python 3.10+. No API key needed — the default LLM provider is
fully local and deterministic.

## Usage

```bash
# print the installed version
oncall-agent version

# show resolved configuration
oncall-agent config

# run a full canned investigation end to end
oncall-agent demo --scenario deploy-regression
oncall-agent demo --scenario oom
oncall-agent demo --scenario unknown

# inspect the audit trail an investigation left behind
oncall-agent audit

# call a real read-only tool directly, outside an investigation
oncall-agent tools query-prometheus 'up{job="checkout-service"}' --url http://localhost:9090
oncall-agent tools pod-status checkout-service --namespace prod
oncall-agent tools logs checkout-service-abc123 --tail 100
oncall-agent tools search-runbooks "pods crash looping oom killed"
oncall-agent tools record-deploy checkout-service v2.5.0 --previous-version v2.4.1
oncall-agent tools deploy-history checkout-service
```

Each `demo` run drives the real investigation loop — the scripted
policy decides what to check, the fake tools return canned evidence,
and every step is appended to the audit log — so `oncall-agent audit`
afterwards shows exactly how the agent got to its conclusion.

The `tools` group calls the same Phase 2 clients the investigation
loop would, directly: `query-prometheus` runs a PromQL instant query
against a real Prometheus; `pod-status` and `logs` shell out to a
read-only `kubectl` (only `get`/`describe`/`logs` are ever allowed —
anything else is refused before it runs); `search-runbooks`
keyword-searches the markdown corpus under `runbooks/`; and
`record-deploy`/`deploy-history` write to and read from a local
append-only deploy ledger that stands in for a CD system's webhook
history. None of these need a live cluster or Prometheus to build or
test against — every unit test mocks the HTTP/subprocess boundary.

## Testing

```bash
pytest -q --cov=oncall_agent
```

91 tests, 99% statement coverage, no network access or API key
required — this is also what CI runs. The real Prometheus/kubectl
clients are tested by mocking the HTTP/subprocess boundary, so the
suite never needs a live cluster or metrics backend.

## License

MIT
