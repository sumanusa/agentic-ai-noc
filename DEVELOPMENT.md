# Development Guide

## 1. Environment

The project is currently developed locally on macOS using:

- Python 3.11
- Visual Studio Code
- Python virtual environment (`.venv`)
- Ollama
- Qwen 3 8B
- Git

## 2. Clone and Open

```bash
git clone <repository-url>
cd agentic-noc
code .
```

If `code` is not available, open the project folder directly in VS Code.

## 3. Virtual Environment

Create the environment:

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

Verify:

```bash
which python
```

It should point to the project's `.venv/bin/python`.

## 4. Dependencies

Install dependencies into the active environment:

```bash
python -m pip install -r requirements.txt
```

Using `python -m pip` helps ensure packages are installed into the same environment used to run the project.

## 5. Deterministic tests

Run tests with:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider
```

This disables bytecode and pytest-cache writes and runs the deterministic suite. The
Ollama integration test is opt-in with `NOC_RUN_OLLAMA_INTEGRATION=1`; it requires a
running local Ollama service and the configured model.

Run the offline labelled scenario suite and print its JSON report:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app.evaluation --no-runtime
```

Save a copy for inspection (stdout remains JSON as well):

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app.evaluation --no-runtime --output /tmp/noc-evaluation.json
python3 -c 'import json; r=json.load(open("/tmp/noc-evaluation.json")); print(json.dumps({"status":r["status"],"scenario_count":r["scenario_count"],"incident_count":r["incident_count"],"workflow_run_count":r["workflow_run_count"],"failed_check_count":r["failed_check_count"],"metrics":r["metrics"]}, indent=2))'
```

The report's `scenarios` array carries expected/actual assertions for each labelled case
and subcase. `incident_count` equals workflow runs because each run receives a distinct
synthetic incident ID; Case F makes it 8 for 7 scenarios. `failed_check_count` counts
assertion mismatches. `metrics.reliability`
separates failed tool evidence (`tool_error_records`) from unavailable/missing evidence
(`unavailable_evidence_records`); provider failure and validation failure runs are
reported separately. `assessment.status == "inconclusive"` is a terminal cautious
assessment and does not itself mean a scenario check failed. `diagnosis_support` reports
case-specific evidence support assertions, while `evidence_grounding` reports only
structural reference validity; neither scores semantic diagnosis truth. Correlation
precision/recall are event-pair matches against the labelled synthetic fixtures, not a
general accuracy estimate. Alarm suppression rate is suppressed fixture rows divided
by all input fixture rows across all workflow executions, including repeated scenario
runs. Runtime is optional and machine-dependent; it is not MTTR.

The suite uses fixed offline LLM test doubles and synthetic fixtures; it does not call
Ollama, network services, or cloud services. Ticket context is injected only by the
evaluation harness and is not a graph adapter. These results do not measure live model
behavior, production reliability, or operational savings.

This is particularly important if Conda or another Python installation is also present on the machine.

To verify the environment:

```bash
which python
which pytest
```

`python -m pytest` should still be used even if `which pytest` points somewhere else.

## 6. Ollama

Verify Ollama:

```bash
ollama --version
```

List installed models:

```bash
ollama list
```

Install the current development model if necessary:

```bash
ollama pull qwen3:8b
```

The current implementation uses Ollama locally. Provider/model configuration should remain separate from agent logic.

## 7. Configuration and Secrets

Local environment-specific values may be stored in:

```text
.env
```

Do not commit:

- API keys
- Passwords
- Access tokens
- Credentials
- Private endpoints
- Other sensitive configuration

The `.gitignore` excludes `.env`, `.venv`, Python caches, and pytest caches.

## 8. Run the graph and synthetic incident demo

From the project root:

```bash
python -m app.main
```

The command above initializes the graph. To run a complete synthetic incident through
validation, evidence collection, and assessment validation without Ollama:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app.main --demo
```

This uses a fixed offline model stub and marks the result `generation_status: demo_stub`.
To run the same fixture through configured Ollama instead, use
`python -m app.main --demo-ollama`.

The input object requires `incident_id`, `site`, `technology`, `severity`, and
`description`; optional `occurred_at` (ISO-compatible), `affected_service`, and
`related_event_refs` are supported.
The graph result exposes a validated `IncidentAssessment` at `result["assessment"]`.
For DEN-042, it also returns `phase2_status`, typed alarm normalization,
deduplication, correlation, and topology results, plus a separate
`deterministic_findings` list. Other sites report `fixture_unavailable` for Phase 2
and retain the Phase 1 assessment path. These analysis results use synthetic fixtures.
Observed findings are generated from provenance-carrying simulated tool records;
hypotheses are separate and cite evidence IDs. Preconstructed Pydantic model results
are converted to plain data and revalidated. Assessment validation checks evidence
incident/site ownership, unique IDs, and successful collection status for every cited
record. A valid empty alarm list means “no alarms”; explicit missing-data payloads are
marked missing; malformed/empty results and exceptions are marked failures.

Model-proposed conflicts are labelled `unverified_model_proposal`; disagreement is not
deterministically verified. Low-confidence supported hypotheses are retained while the
overall assessment is marked inconclusive below the documented 0.5 gate. The score is
uncalibrated and is not a probability.

Advisory results include recommended action, rationale, risk, type, and approval flag.
Operational and MEDIUM/HIGH-risk recommendations always require human approval in the
result. No approval workflow, remediation, or external action is implemented.

## 9. Optional local-Ollama integration test

Run the opt-in integration test:

```bash
NOC_RUN_OLLAMA_INTEGRATION=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_agent.py
```

This test calls the configured local model and is excluded from the deterministic test
command above.

Verbose deterministic output:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -v
```

Specific test:

```bash
python -m pytest tests/test_agent.py -v
```

## 10. Development Workflow

Use a small, testable change cycle:

```text
Make Change
    |
    v
Run Focused Test
    |
    v
Run Full Test Suite
    |
    v
Review Git Diff
    |
    v
Commit
    |
    v
Push
```

Typical commands:

```bash
python -m pytest
git status
git diff
git add .
git commit -m "Describe the change"
git push
```

## 11. Project Conventions

### Prompts

Keep generic agent behavior in the system prompt.

Keep incident-specific information separate so it can be supplied as input.

### Tools

Tools should provide factual operational information and avoid embedding diagnosis or business logic that belongs in the agent/assessment layer.

### Models

Use Pydantic models for important structured data contracts.

### Tests

Add or update tests when changing tools, models, or agent behavior.

## 12. Current Scope

The current prototype uses simulated network data and read-only NOC tools.

It does not:

- Connect to production telecom infrastructure
- Execute real network changes
- Provide autonomous remediation
- Store production customer data

Future capabilities should be introduced incrementally with appropriate policy, authorization, auditability, and human oversight.
