# oncall-agent — daily report

Six nights, six phases, all complete. This is a summary of what got
built, how it was tested, and what's intentionally left out. For the
detailed build log and architecture notes, see `PROGRESS.md`; for usage
and screenshots, see `README.md`.

## What was built, night by night

**Night 1 — scaffold & core foundation.** The domain models
(`Alert`, `Hypothesis`, `Diagnosis`, `ToolCallRecord`, `AuditEvent`), an
append-only JSON-lines audit trail, env-driven configuration, a
pluggable `LLMProvider` interface with a deterministic
`ScriptedPolicyProvider` as the default (no API key, no network access),
a read-only `Tool` interface with two fake demo tools, the
investigate → hypothesize → diagnose loop (`run_investigation`), and a
CLI with `version`/`config`/`demo`/`audit`.

**Night 2 — real read-only tool integrations.** A Prometheus query
client, a `kubectl get/describe/logs`-only client (refuses any other
subcommand at a single chokepoint), a keyword runbook search over a
six-runbook markdown corpus, and an append-only deploy-history ledger —
all behind the same `Tool` interface as the Night 1 fakes, reachable
directly via `oncall-agent tools <name>`.

**Night 3 — smarter reasoning.** Multi-hypothesis ranking
(`rank_hypotheses`/`current_hypothesis`), a re-planning step where the
scripted policy revises its hypothesis once pod health flatly
contradicts a deploy-based guess, an optional local-model provider
(`OllamaProvider`, talks to Ollama's `/api/generate`), and structured
diagnosis report export (Markdown/JSON).

**Night 4 — human approval gate.** Every diagnosis now tags a
machine-actionable `ActionType` (`restart`/`rollback`/`scale`/
`escalate`). `ApprovalGate` implementations (`CLIApprovalGate`,
`AutoApprovalGate`, `SlackApprovalGate`) stand between a diagnosis and
an `ActionExecutor` (kubectl-backed, or a dry-run `Noop` registry);
nothing mutates without an `APPROVED` decision, and every outcome is
logged. `oncall-agent approve` is the manual stand-in for a Slack
button click.

**Night 5 — incident simulator.** Six fault types (`FaultType`), one
per runbook, each mapped to canned evidence (`FAULT_PROFILES`) the fake
tools return — hand-rolled rather than built on an external
chaos-engineering tool, since every existing test already ran on canned
evidence and nothing here needs a live cluster. Six `Scenario`s fire
through `respond_to_incident` unattended (`AutoApprovalGate` standing in
for a human), end to end, via `oncall-agent simulate list/run/run-all`.

**Night 6 — scorecard & polish.** Every `Scenario` gained
`expected_category`/`expected_action` ground truth; `Diagnosis` gained a
`category` field the scripted policy now tags on every branch.
`simulator/scorecard.py` compares actual vs. expected across a suite and
reports root-cause accuracy, action accuracy, and steps taken (tool
calls plus hypotheses formed/revised), with Markdown export and a
provider-comparison mode (`oncall-agent simulate scorecard`/`compare`).

## Test results

216 tests, 99% statement coverage, run with `pytest -q --cov=oncall_agent`.
No network access or API key required — this is also what CI runs
(`.github/workflows/ci.yml`). The real Prometheus/kubectl clients, the
optional Ollama provider, and the Slack approval gate are all tested by
mocking the HTTP/subprocess boundary.

The scorecard's own numbers, run against the scripted policy:

| metric | result |
|---|---|
| root-cause accuracy | 50% (3/6) |
| action accuracy | 100% (6/6) |
| total steps (6 scenarios) | 21 |
| average steps/scenario | 3.5 |

The gap between those two numbers is the headline finding: the scripted
policy mislabels the true cause on three of six scenarios (network
partition, disk pressure, config drift — all three show no deploy and
no OOM signal, the only failure shape it currently has a dedicated
re-planning path for), but it never once proposes an unsafe action on
those misses — it always falls back to `ESCALATE` rather than guessing
a rollback or scale that wouldn't fix the real problem. The approval
gate and the scorecard were designed around exactly that property:
being wrong about the cause should be safe; being wrong about the
*action* should be structurally impossible without a human in the loop.

## Known limitations

- The real Phase 2 tools and the kubectl-backed `ActionExecutor`s are
  built and unit-tested but not wired into `demo`/`simulate` — both
  still run on deterministic fake/canned evidence by design, for
  reproducible scenarios, screenshots, and CI.
- `OllamaProvider` has only ever been exercised against a mocked HTTP
  boundary, never a real Ollama server; its prompt has had no
  real-model tuning.
- `SlackApprovalGate` posts to a webhook and polls a local
  `SlackDecisionInbox` file; there's no real Slack Events API endpoint
  behind `oncall-agent approve`, which is a manual stand-in for the
  button click a hosted webhook receiver would normally provide.
- No integration tests run against a live Prometheus or Kubernetes
  cluster (the `integration` pytest marker is registered but unused).
- Three of the six simulator scenarios are only diagnosed as a safe,
  generic escalation rather than their precise root cause — documented
  and now measured numerically by the Phase 6 scorecard rather than
  fixed, since closing that gap is itself a distinct unit of future
  work (see `PROGRESS.md`'s "Where to resume" for the concrete plan).

## Future ideas

- Give the scripted policy dedicated detection for network partitions,
  disk pressure, and config drift (each would need a new tool signal,
  not just a new category tag) to close the root-cause accuracy gap the
  scorecard surfaced.
- A "live" investigation mode that registers the real Prometheus/kubectl
  tools and the kubectl-backed action executors instead of the fakes,
  as an alternative entry point alongside `demo`/`simulate`.
- A hosted Slack Events API receiver so `SlackApprovalGate` can be
  exercised against a real workspace instead of the local decision-inbox
  file.
- Wall-clock timing alongside step count in the scorecard, once a
  provider with a meaningful latency difference (e.g. a tuned
  `OllamaProvider`) exists to compare against the scripted policy.
