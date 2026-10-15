# Agentic AI NOC Incident Resolution Prototype

A local prototype demonstrating an agentic AI approach to telecom Network Operations Center (NOC) incident investigation.

The project explores how an AI agent can use an LLM, NOC diagnostic tools, and structured data models to investigate a network incident and produce an evidence-based assessment.

> **Status:** Phases 1–4 implemented as a local synthetic prototype; not production-ready.

## Purpose

The prototype is being developed as a practical exploration of Agentic AI for telecom operations.

Implemented capabilities include:

- LLM-driven incident investigation
- Model-assisted assessment synthesis
- Simulated telecom NOC diagnostic tools
- Evidence gathering
- Structured incident assessment
- LangGraph-based orchestration
- Local LLM execution
- Deterministic alarm normalization, deduplication, and correlation
- Declared-topology traversal and potential service-dependency analysis
- Bounded graph integration and synthetic evaluation reporting

Autonomous network remediation and live telecom/ITSM integration are outside the MVP.

## Current Architecture (Implemented local prototype)

```text
Incident -> validation -> simulated evidence -> deterministic alarm/topology analysis
                                              -> separate model hypotheses
                                              -> validated advisory assessment
```

For the implemented components, proposed AWS target, controls, data flow, and prioritized
use cases, see [ARCHITECTURE.md](ARCHITECTURE.md). Its AWS diagram is conceptual only;
no cloud service is deployed or integrated.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Application development |
| LangGraph | Agent orchestration |
| LangChain | LLM and tool integration |
| Ollama | Local LLM runtime |
| Qwen 3 8B | Local development model |
| Pydantic | Structured data contracts |
| Pytest | Automated testing |

## Project Structure

```text
app/
├── agents/        # Agent components
├── models/        # Structured data models
├── prompts/       # Prompt modules; graph currently builds its assessment prompt inline
├── tools/         # NOC diagnostic tools
├── config.py      # Configuration
├── graph.py       # LangGraph orchestration
├── llm.py         # LLM configuration
├── main.py        # Application entry point
└── state.py       # Agent state

data/
├── incidents.json
├── network/
└── runbooks/

tests/             # Automated tests
```

## Prerequisites

- Python 3.11+
- Ollama
- Qwen 3 8B
- Git

The current development environment is local macOS.

## Setup

Clone the repository and enter the project directory:

```bash
git clone <repository-url>
cd agentic-noc
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Install the local model:

```bash
ollama pull qwen3:8b
```

## Incident input and assessment

`Incident` requires non-empty `incident_id`, `site`, `technology`, `severity`, and
`description`. Optional `affected_service` and `related_event_refs` are preserved;
`occurred_at` accepts an ISO-compatible timestamp. Unknown fields and invalid boundary
values are rejected.

The graph accepts `{"incident": <incident object>}` and returns an
`IncidentAssessment` at `result["assessment"]`. Assessment facts are generated from
the collected evidence records; model-generated root-cause hypotheses remain separate
and cite evidence IDs. Evidence is marked as synthetic, and timestamps are explicitly
unavailable for the current fixtures. Unsupported citations or weak evidence produce
an inconclusive assessment; validated low-confidence hypotheses are retained in that
result. Conflicts proposed by the model are labelled `unverified_model_proposal` and
are not deterministic proof of disagreement. `generation_status` distinguishes successful model output,
provider failure, invalid output, a skipped model call when no evidence is available,
and the offline demo stub.
Confidence is an uncalibrated model-reported score from 0 to 1, not a probability.
Hypotheses below the 0.5 assessment gate remain inconclusive; this threshold is a
prototype decision, not a calibrated telecom confidence measure.

The advisory output includes a recommended action, rationale, LOW/MEDIUM/HIGH risk,
recommendation type, and human-approval flag. Operational or MEDIUM/HIGH-risk
recommendations are marked as requiring human approval. No action is executed.

The current tools are simulated alarm, telemetry, and inventory lookups. They do not
represent live network observations. For DEN-042, a bounded graph step also processes a
dedicated structured synthetic alarm fixture through normalization, deduplication,
correlation, and declared-topology analysis. Results are exposed in typed graph state;
deterministic correlation and potential-impact interpretations remain separate from
assessment observed facts and model hypotheses. Service traversal reports potential
dependency only and keeps observed service impact unknown. Other sites report that the
Phase 2 fixture is unavailable and retain the existing assessment path. No live-system
integration, write operation, or remediation is implemented.

## Running Tests

Use the project environment's Python interpreter:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider
```

The deterministic suite does not require Ollama. One optional integration test is
skipped unless `NOC_RUN_OLLAMA_INTEGRATION=1` is set.

Run the repeatable seven-case evaluation and print machine-readable JSON:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app.evaluation --no-runtime
```

Use `--output evaluation.json` to save the same JSON report while printing it. At the
top level, `status`, `scenario_count`, `incident_count`, `workflow_run_count`, and
`failed_check_count` summarize the run; incident count is the number of distinct
workflow executions (including Case F's two failure subcases). `scenarios` contains
each labelled scenario/subcase, expected versus
actual checks, assessment status, evidence source failures, and limitations; `metrics`
contains aggregates. Case F contributes two workflow runs (tool timeout and provider
unavailable), so scenario count and run count differ. Use `--no-runtime` for stable
comparison; its per-run timing values are null. Without that flag, `runtime_ms_observed_not_repeatable`
is machine-dependent prototype execution time, not human triage time or operational MTTR.

The alarm suppression rate uses all alarm fixture rows across workflow runs as its
denominator, including repeated scenario executions. Correlation precision/recall are
event-pair comparisons against these labelled fixtures only; group counts are reported
separately. Structural evidence-reference coverage checks that material claims cite
successfully collected evidence IDs; it does not establish that the claim is true.
`diagnosis_support` counts case-specific checks that a leading hypothesis cites expected
successful fixture evidence. Semantic diagnosis quality remains unscored. Reliability
separates tool-error evidence records from unavailable evidence records, and reports
provider failures, validation failures, inconclusive assessments, completion, and
external-action count. A failed check means an expected deterministic assertion did not
match; unavailable evidence is a source outcome; provider failure is a model call error;
an inconclusive assessment is a valid cautious terminal result. They are not synonyms.
Ticket records are evaluation-only injected evidence because the graph has no ticket
adapter. All scenarios and model responses are synthetic/offline; fixed test doubles do
not measure live model behavior, and results are not production accuracy or savings.

## Running the Application and synthetic demo

```bash
python -m app.main
```

The command above initializes the graph. To run a reproducible incident assessment
without Ollama, use the explicitly labelled offline stub:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app.main --demo
```

To use the configured local Ollama model instead:

```bash
python -m app.main --demo-ollama
```

The offline output is a demonstration of the input/evidence/validation path, not an
LLM result. Both modes use only local synthetic fixtures.

## Design Principles

**Evidence before inference** — obtain factual network information before forming conclusions.

**Recommendation is not authorization** — an AI recommendation should not automatically authorize a network change.

**Structured outputs** — use typed contracts for operational information.

**Provider abstraction** — keep LLM provider/model configuration separate from agent logic.

**Human oversight** — potentially disruptive actions should require appropriate approval.

## Roadmap

### Phase 1 — Trustworthy Incident Assessment
- [x] Local development environment
- [x] NOC diagnostic tools
- [x] Local LLM integration
- [x] LangGraph orchestration
- [x] Validated incident intake and evidence provenance
- [x] Versioned, validated assessment with evidence references
- [x] Facts separated from hypotheses; inconclusive failure handling
- [x] Automated tests

### Phase 2 — Safe Execution and Telecom Correlation
- [x] Deterministic alarm deduplication and correlation foundations
- [x] Standalone topology traversal and potential service-dependency analysis
- [x] Bounded fixture-backed graph integration of alarms, correlation, and topology
- [x] Explicit single-pass workflow bounds; no autonomous remediation

### Phase 3 — Evaluation Harness
- [x] Fixed synthetic cases and machine-readable evaluation results
- [x] Repeatable structural grounding, reliability, and safety metrics

### Phase 4 — Operational Reporting and Architecture Package
- [x] Current-state and proposed target architecture artifacts
- [x] Operational report and integration/control documentation

### Phase 5 — Optional Extensions
- [ ] Consider extensions only after the core scenarios pass evaluation

### Future
- NOC dashboard
- OSS/NMS and ITSM integration patterns
- Event-driven architecture
- Observability and auditability
- Enterprise security and governance

## Disclaimer

This is a learning and demonstration prototype. Network data and NOC tools are simulated and do not represent a production telecom network. The system does not control real network infrastructure.
