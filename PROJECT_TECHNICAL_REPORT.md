# Agentic AI NOC Prototype — Technical and Interview Report

**Repository snapshot reviewed:** `main`, local `HEAD` `e003e41664090d2cf63b802fa6ae2e03425e9047`, seven commits ahead of `origin/main`. The working tree was clean before this report was created. This report documents the implementation in that snapshot; it does not claim deployment or production experience.

## A. Executive summary

This repository is a local, synthetic-data prototype for investigating a telecom NOC incident. It demonstrates a bounded LangGraph workflow that validates an incident, collects simulated evidence, runs deterministic fixture-backed alarm normalization/deduplication/correlation and declared-topology analysis for one site, asks a configured structured-output model for hypotheses and an advisory recommendation, and validates an `IncidentAssessment` result.

The prototype is designed to make evidence references, uncertainty, provider/tool failures, and the boundary between observations and interpretations visible. Its deterministic rules and tests are reproducible offline. A seven-scenario evaluation reports structural checks and synthetic-fixture metrics; it does not establish real-world diagnostic accuracy, savings, or MTTR improvement.

The current implementation is not a production NOC system: the tools are local dictionaries, the structured alarm/topology path is fixture-specific, ticket data is injected only by the evaluation harness, and there are no live adapters, product-grade run tracing, operator approval service, action executor, or deployed AWS components. Recommendations remain advisory and no network or ticket changes are performed. The project demonstrates practical patterns and trade-offs; it should not be presented as a deployed transformation.

## B. Requirements traceability

The source of requirement IDs and acceptance intent is the project authority document `NOC_Prototype_MVP_Requirements_Updated_Telecom_AI.docx` (sections 4–5). Status below describes repository evidence, not planned architecture. “Verified” means local tests or offline evaluation exercise the stated behavior, not validation against production systems.

### Functional requirements

| ID | Status | Implemented components and verification | Remaining gap |
|---|---|---|---|
| FR-01 Incident intake | **Partial** | `app/models/incident.py:Incident`; `app/graph.py:_validate_input`; `tests/test_incident.py`, `tests/test_assessment_path.py` cover valid, missing, malformed, and boundary input. Pydantic parses ISO-compatible timestamps and strips surrounding string whitespace. | This is validation/coercion, not full canonical normalization: naive timestamps are accepted and timestamps are not normalized to a canonical timezone representation. Synthetic prototype contract only. |
| FR-02 Typed tool contracts | **Partial** | `app/evidence.py:collect_evidence` classifies alarm, telemetry, and inventory lookup results into typed `EvidenceRecord`s; contract/error cases in `tests/test_assessment_path.py`. | Lookup functions return dictionaries, not dedicated typed input/output schemas; ticket and knowledge adapters are absent; timeout behavior is injected only in evaluation. |
| FR-03 Alarm deduplication | **Implemented and verified** | `app/alarm_processing.py:normalize_alarms`, `deduplicate_alarms`; `app/models/alarm.py`; `tests/test_alarm_processing.py`. Identity, timezone, anchored five-minute window, invalid rows, counts, and references are tested. | Rules are synthetic and must be checked against real source semantics before use. |
| FR-04 Alarm correlation | **Partial** | `app/alarm_correlation.py:correlate_alarms`; `tests/test_alarm_correlation.py`; related/unrelated scenarios in `tests/test_evaluation.py`. Exact-condition, same-element, distinct-source-event recurrence is deterministic and explainable. | The rule does not correlate via topology or incident context. Nearby timestamps alone do not qualify. Broader correlation requires validated source rules and labels. |
| FR-05 Topology and service impact | **Implemented and verified for the fixture** | `app/models/topology.py`, `app/topology_analysis.py:analyze_topology`, `data/topology/phase2c_den042.json`; `tests/test_topology_analysis.py`. | One small synthetic topology; no real inventory adapter or observed service-health source. |
| FR-06 Evidence gathering | **Partial** | `app/evidence.py:collect_evidence`, `app/models/evidence.py:EvidenceRecord`, assessment and integration tests. IDs, source, incident/site, status, limitations, and optional observation time are represented. | Product sources cover alarms, telemetry, and flat inventory only. Ticket/knowledge evidence is not collected by the graph. Basic dictionary tools do not supply source-record IDs or timestamps. |
| FR-07 Root-cause assessment | **Partial** | `AssessmentDraft` and `RootCauseHypothesis` in `app/models/assessment.py`; `_assessment_node` in `app/graph.py`; tests cover citations, conflicts, confidence, and inconclusive outcomes. | Hypotheses and alternatives are model-proposed; no semantic truth evaluator or deterministic conflict verification. Alternative hypotheses and discriminating checks are not guaranteed by the schema. |
| FR-08 Structured assessment | **Partial** | Versioned `IncidentAssessment` schema (`1.0`) validates ownership, citations, status, and approval metadata; `tests/test_assessment.py`, `tests/test_assessment_path.py`. | Correlation groups, affected elements/services, and topology paths are exposed in separate graph state, not as fields in the canonical assessment. “Affected services” is populated from incident input only. |
| FR-09 Bounded orchestration | **Partial** | `app/graph.py:build_graph` is a fixed four-node, single-pass graph; graph integration tests cover terminal handling. | No explicit configurable step/tool-call budget, retry policy, or enforced timeout. Case F simulates a timeout outcome; it does not prove a timeout wrapper around actual tool calls. |
| FR-10 Recommendation and approval | **Partial** | Assessment includes action, rationale, risk, type, approval flag, next steps; `IncidentAssessment` forces approval metadata for operational or non-LOW risk. | No expected-benefit or prerequisite fields, approval workflow, or execution capability. The flag is metadata only. |
| FR-11 Audit and traceability | **Partial** | Evidence IDs and typed derived results support some reconstruction; `app/evaluation.py` reports per-run checks and outcomes. | No product run/correlation ID, structured stage/tool trace, per-stage timing, or durable audit record. Evaluation run IDs are harness labels, not workflow audit IDs. |
| FR-12 Failure and uncertainty | **Implemented for tested cases** | `app/evidence.py`, `app/graph.py:_assessment_node`; assessment-path and Phase 2D integration tests cover missing, malformed, provider, and component failures and cautious status. | Staleness is not meaningfully evaluated because fixtures lack observation timestamps; no production failure isolation or retry strategy. |
| FR-13 Configuration/provider boundary | **Partial** | `app/config.py` reads provider/model/temperature from environment; `app/llm.py:get_llm` isolates provider construction. | Only Ollama is implemented. The test suite does not verify missing/invalid configuration behavior, and there is no second provider demonstrating portability. |
| FR-14 Evaluation harness | **Implemented and verified** | `app/evaluation.py`, `data/evaluation/scenarios.json`, `tests/test_evaluation.py`; documented offline CLI. | Fixed doubles and small synthetic labels limit what results mean. |
| FR-15 Operational metrics/report | **Partial** | Evaluation reports alarm counts, correlation pairs/groups, structural references, a narrow diagnosis-support check, uncertainty, failures, approval metadata, completion, actions, and optional runtime. | No product triage-duration instrumentation; diagnosis metric is one expected-reference assertion, not diagnosis quality. It does not fulfill full production observability. |
| FR-16 Architecture artifacts | **Implemented and verified as documentation** | `ARCHITECTURE.md` contains current and proposed AWS Mermaid diagrams, boundaries, controls, use cases, and roadmap. | The target is conceptual, not deployed or security-reviewed. |
| FR-17 Telecom scenario | **Partial** | Case A combines synthetic telemetry, structured alarm and topology fixtures, an evaluation-only ticket record, and unrelated event discipline; `tests/test_phase2d_graph_integration.py`. | The “ticket/service symptom” is injected only in evaluation; there is no ticket adapter or independent service-health observation. A path shows potential dependency, not an observed outage. |
| FR-18 Reproducibility | **Implemented and verified** | `README.md`, `DEVELOPMENT.md`; local suite and evaluation command rerun for this report. | A fresh environment still depends on installing unpinned dependencies and, for live-model mode, a separately installed local Ollama model. |

### Non-functional and safety requirements

| ID | Status | Evidence and gap |
|---|---|---|
| NFR-01 Safety boundary | **Implemented and verified** | Only synthetic/local sources are wired; no write adapter/action node. Evaluation reports zero external actions. No production endpoint is exercised. |
| NFR-02 Evidence integrity | **Implemented for current fixtures** | Assessments retain evidence records; event groups and topology paths preserve supplied references. Malformed event rows remain issues. No real source lifecycle or durable evidence archive exists. |
| NFR-03 Determinism | **Implemented and verified** | Alarm, correlation, topology, and offline evaluation tests establish repeatable behavior for fixed input. Model-backed responses are not guaranteed deterministic. |
| NFR-04 Reliability | **Partial** | Explicit terminal statuses and exception conversion are tested; graph is finite. Enforced source timeouts, bounded retries, and a configurable call budget are missing. |
| NFR-05 Validation | **Implemented and verified for defined boundaries** | Pydantic contracts and malformed/preconstructed-model regression tests cover incident, assessment, alarm, correlation, and topology results. |
| NFR-06 Security hygiene | **Partial** | `.gitignore` excludes `.env`, `.venv`, and caches; configuration is environment-based; AWS design discusses controls. No IAM, secret manager, redacted structured logging, production access policy, or security review exists. `.env` contents were not inspected for this report. |
| NFR-07 Explainability | **Implemented with limitations** | Deterministic rules retain provenance; model hypotheses are a separate schema; confidence is explicitly uncalibrated. Model semantics are not independently verified. |
| NFR-08 Testability | **Implemented and verified** | Deterministic tests and evaluation use synthetic fixtures/fixed doubles and pass without Ollama or external services. One Ollama integration test is opt-in and skipped here. |
| NFR-09 Maintainability | **Implemented** | Domain models and focused modules/tests are split by concern. Dependency versions are not pinned; `requirements.txt` also lists packages without active imports in this implementation. |
| NFR-10 Honest claims | **Implemented in current documentation/evaluation** | Synthetic, proposed, structural, uncalibrated, and non-MTTR outputs are labelled. This report maintains those qualifications. |

## C. Architecture and end-to-end workflow

### Actual workflow

`app/graph.py:build_graph` connects a fixed sequence: `validate_input → collect_evidence → deterministic_analysis → assess → END`. There are no conditional agent/tool loops. `app/state.py:AssessmentState` carries the validated `Incident`, `EvidenceRecord` list, Phase 2 typed results and deterministic findings, terminal assessment, and failure/status fields.

1. **Intake:** `_validate_input` validates the `incident` mapping as `app.models.incident.Incident`. Required fields are incident ID, site, technology, severity, and description; optional timestamp, service, and related references are validated by the model.
2. **Collection:** `_collect` calls `app.evidence:collect_evidence` once for each of three local functions: alarm strings, telemetry, and flat inventory/path data. `_classify_result` differentiates successful empty alarm data from missing/error and malformed/failure results. Exceptions become failed evidence records. These functions are simulated dictionaries in `app/tools/alarms.py`, `telemetry.py`, and `inventory.py`.
3. **Structured alarm/topology step:** `_phase2_analysis` runs only for `DEN-042`. It reads `data/alarms/phase2d_integration_events.json` and `data/topology/phase2c_den042.json`, creates synthetic evidence records, and calls `normalize_alarms → deduplicate_alarms → correlate_alarms → analyze_topology`. Other sites return `fixture_unavailable`; there is no inferred topology from the flat inventory dictionary. Exceptions become a failure evidence record and terminal inconclusive assessment.
4. **Deterministic results:** correlation and potential service-dependency interpretations go into `deterministic_findings` in graph state. They remain separate from `IncidentAssessment.findings` (observed facts) and `hypotheses` (model interpretations). Topology potential impact never means observed service health.
5. **Assessment:** `_assessment_node` builds prompt messages with the incident, evidence, and Phase 2 results, then requests `AssessmentDraft` through `llm.with_structured_output(...).invoke(...)`. It revalidates returned data, checks cited IDs belong to successful evidence, and computes a cautious status. Provider errors and invalid output yield an explicit inconclusive assessment; no successful evidence skips model generation.
6. **Terminal contract:** `IncidentAssessment` schema version `1.0` carries findings, hypotheses, missing evidence, conflicts, uncertainty, confidence, advisory recommendation, risk, approval metadata, next steps, and retained evidence. A supported hypothesis is needed for `assessed`; the 0.5 threshold is an uncalibrated prototype gate, not a probability or operationally validated cutoff.

The assessment’s observed facts are deterministic renderings of values in successful evidence records. This is suitable for synthetic fixtures but does not establish that a real adapter’s payload is authoritative or semantically correct. Model-created conflict entries are explicitly `unverified_model_proposal`. Failed evidence is not eligible citation evidence.

### Contracts and processing rules

- **Evidence:** `app/models/evidence.py:EvidenceRecord` includes stable synthetic ID, source/type, incident/site, optional time, value, collection status, and limitation. `make_evidence_record` hashes contextual source data; current local tools provide no real source-record identifier or observation timestamp.
- **Alarm normalization:** `app/models/alarm.py` preserves source IDs and raw rows when present; actual row index is a locator, never a fabricated event ID. Malformed envelopes have envelope-level issues without invented row locator. Invalid rows do not become events.
- **Deduplication:** `app/alarm_processing.py:deduplicate_alarms` requires complete identity and timezone-aware time. Identity is source, site, element, event code/type, severity, and lifecycle; if source event ID exists it must match, otherwise those attributes form the fallback fingerprint. The configurable default window is five minutes, inclusive and anchored to the earliest representative. Equal timestamp ties use first input row. Duplicate groups preserve source/evidence references and reconcile original, representative, suppressed, and invalid counts.
- **Correlation:** `app/alarm_correlation.py:correlate_alarms` groups distinct source event IDs with complete exact matching attributes for the same alarm condition inside an anchored 15-minute window. The relationship is not proof of common cause. This narrow rule does not use cross-element topology paths or incident context.
- **Topology:** `app/models/topology.py` validates typed elements, directed edges, service mappings, coverage, and analysis results. `app/topology_analysis.py:analyze_topology` traverses only declared provider-to-dependent edges; breadth-first shortest paths use lexicographic edge-ID tie-breaking. Incomplete coverage keeps missing-path conclusions unknown. A declared service path means `potentially_affected`; `observed_impact` stays `unknown`.
- **Assessment:** `app/models/assessment.py:IncidentAssessment` checks unique evidence IDs, incident/site ownership, successful cited evidence, and the supported-hypothesis status invariant. Operational or MEDIUM/HIGH risk implies `human_approval_required=True`, but that field does not create a human workflow.

### Technology choices and trade-offs

| Technology | Actual use | Trade-off / limit |
|---|---|---|
| Python 3.11 | Runtime used by this environment and test run. | `requirements.txt` versions are unpinned, so a clean install is not dependency-lock reproducible. |
| Pydantic | Input, evidence, assessment, alarm, correlation, and topology contracts; semantic validators enforce cross-field invariants. | Contracts validate shape and selected semantics, not truth of source data or model explanations. |
| LangGraph | Compiled fixed state graph (`app/graph.py`). | The “agentic” aspect is structured model interpretation within a predictable one-pass workflow; there is no autonomous planning loop. |
| LangChain | Message classes, structured model output interface, tool decorators, and Ollama adapter. | The three decorated lookup functions are backed by local dictionaries and are not dynamically called by an agent loop. |
| Ollama / Qwen 3 8B | Default configured model (`app/config.py`, `app/llm.py`); optional `--demo-ollama` and integration test. | This report’s tests/evaluation did not call it. Model quality, latency, and output consistency are not measured here. |
| Pytest | Deterministic unit/integration and evaluation tests. | Offline doubles prove contracts and fixture assertions, not live-model semantic performance. |
| FastAPI, Uvicorn, Streamlit, ChromaDB | Listed in `requirements.txt`; no imports/use were found in `app/` or tests. | They should be described as installed dependency candidates only, not implemented API, UI, or retrieval capabilities. |

No vector database/RAG, dashboard, cloud runtime, or multi-agent architecture is implemented. The simpler deterministic pipeline keeps behavior inspectable; broader correlation, retrieval, and provider selection should be added only with a defined use case and measured acceptance criteria.

## D. Evaluation methodology and results

### Scenarios

`data/evaluation/scenarios.json` defines seven labelled cases. Case F contains two workflow runs, yielding eight runs total. `app/evaluation.py:run_evaluation` uses fixed offline assessment doubles and synthetic fixture data.

| Case | Purpose and expected behavior | Current coverage |
|---|---|---|
| A — Correlated fault | Repeated source event is deduplicated with references retained; distinct same-condition events correlate; declared router/interface/cell/service path is exposed as potential dependency; supported hypothesis and safe diagnostic action. Ticket context is injected by evaluator only. | End-to-end tests and labeled checks; not a ticket integration or service-outage confirmation. |
| B — Duplicate storm | Suppress repeated same-identity rows within the duplicate window and retain counts/references. | Fixture and evaluation assertions. |
| C — Unrelated alarm | Do not group alarms merely because time/site are close when identity differs. | Fixture and evaluation assertions. |
| D — Incomplete topology | Report unknown impact and inconclusive assessment rather than inventing a path or claiming unaffected service. | Partial topology fixture and evaluation assertions. |
| E — Conflicting evidence | Expose model-proposed conflict between synthetic telemetry and evaluator-injected ticket text; stay inconclusive and request further check. | Fixed double exercises contract; conflict is not independently verified by deterministic comparison. |
| F — Tool/provider failure | Exercise synthetic telemetry timeout evidence and unavailable provider as separate subcases; terminate safely. | Two injected modes; does not validate infrastructure timeout enforcement. |
| G — Low evidence | Avoid asserting a root cause and remain inconclusive when evidence is insufficient. | Fixed double and evaluation assertions. |

### Fresh verification for this report

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider` — **130 passed, 1 skipped**, 131 collected. The skip is the opt-in Ollama integration test.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app.evaluation --no-runtime --output /tmp/agentic-noc-project-report-evaluation.json` — **passed**, 7 scenarios, 8 workflow runs, 0 failed checks. JSON output was also inspected from the temporary file outside the repository.
- `git diff --check` — passed for tracked changes. Because this report is untracked, its whitespace was checked separately with `git diff --no-index --check /dev/null PROJECT_TECHNICAL_REPORT.md` — passed.

Aggregate evaluation values from that exact run:

| Metric | Observed output | Definition / caveat |
|---|---:|---|
| Alarm rows / operational representatives / suppressed | 28 / 21 / 7 | Across all eight workflow runs, including repeated scenario executions. |
| Duplicate suppression rate | 0.25 | Suppressed / input; fixture-specific, not operational value. |
| Correlation pair TP / FP / FN | 3 / 0 / 0 | Labels in this synthetic test set only. Pair precision and recall both 1.0 here; not a general accuracy estimate. Four expected and four actual groups are separately reported. |
| Material claims with valid successful evidence references | 221 / 221 | 100% structural reference coverage. This checks known successful IDs, not whether claims are true or evidence semantically supports them. |
| Diagnosis support checks | 1 / 1 passed | The leading hypothesis cited expected successful fixture evidence. Semantic diagnosis quality is explicitly not scored. |
| Terminal assessment runs | 8 / 8 | Completion rate 1.0 means a terminal assessment was produced, not that all runs were successful diagnoses. Five were inconclusive. |
| Failure outcomes | 1 provider failure; 1 tool-error record; 2 unavailable-evidence records; 0 validation failures | Failure categories remain distinct. These are injected synthetic modes. |
| External actions | 0 | The prototype has no action adapter. |
| Runtime | null for all runs (`--no-runtime`) | Machine-dependent timing deliberately omitted; never use as operational MTTR. |

The evaluation is repeatable and reports per-case expected/actual checks, but its metric scope is narrow. The 221/221 grounding result is structural citation coverage. The correlation numbers describe event-pair labels in a tiny fixture set. The single diagnosis check is an evidence-reference check, not an assessment of whether backhaul was actually the cause. Fixed doubles do not measure an Ollama model or any other LLM. `--no-runtime` makes the listed timing entries null; without it, process runtime is local machine execution time, not human triage or repair time.

## E. Reliability, safety, and security

### Implemented controls

- Rejects malformed incident boundaries and malformed structured model output; preconstructed Pydantic instances are converted to plain data and revalidated at important processing boundaries.
- Keeps failed/missing evidence statuses explicit; only successfully collected evidence can support assessment citations.
- Retains contradictory evidence references while marking model-proposed conflicts unverified.
- Reports incomplete topology as unknown and potential dependency separately from observed service health.
- Uses deterministic event rules and a finite graph; provider and Phase 2 failures produce visible inconclusive results.
- Adds risk and approval metadata; no action is executed. Test/evaluation inputs are synthetic, and deterministic tests do not require Ollama/network/cloud.
- `.gitignore` excludes `.env`, `.venv`, Python bytecode, pytest cache, and `.DS_Store`. This review did not inspect `.env`.

### Not implemented / production prerequisites

There is no production identity/access integration, least-privilege adapter role, secret manager, data encryption/retention enforcement, redacted structured log pipeline, durable audit trail, workflow correlation ID, stage timing trace, rate/cost quota, or cloud observability. There is also no actual human approval queue or authorization check. A flag in the response is not an approval control. Before any pilot: classify source data, agree data ownership/freshness and permitted use, implement read-only scoped adapters, enforce tool timeouts and bounded retries, add safe trace IDs/logging, define approval and audit policy, test security controls, and validate source identity/topology/correlation assumptions against approved representative data. Keep remediation outside until it has a separate authorization and safety case.

## F. Implemented architecture versus proposed AWS target

`ARCHITECTURE.md` contains two Mermaid diagrams. The first describes the implemented local flow. The second is a conceptual AWS option—not provisioned, deployed, integrated, costed, or security-reviewed. It proposes approved source adapters → API Gateway or managed connector → EventBridge/SQS (DLQ) → Lambda normalization → Step Functions bounded orchestration, with S3 evidence archive, DynamoDB run state/idempotency, a provider-neutral model adapter (Bedrock as a candidate), CloudWatch, IAM, KMS, Secrets Manager, and human review. The proposed flow ends in an advisory result and includes no action executor.

Those service choices are architectural hypotheses, not commitments. Discovery is needed for source protocols, throughput, latency, residency, data classification, identity, retention, service-health authority, failure/replay semantics, and model constraints. RAG/vector storage is not assumed. The repository contains no AWS infrastructure-as-code or cloud integration.

## G. Repository map and reproducibility

```text
app/
  graph.py, state.py, evidence.py, evaluation.py
  alarm_processing.py, alarm_correlation.py, topology_analysis.py
  models/{incident,evidence,assessment,alarm,correlation,topology}.py
  tools/{alarms,telemetry,inventory,knowledge}.py   # only first three are wired to graph
  config.py, llm.py, main.py, prompts/
data/
  incidents.json, network/, runbooks/
  alarms/, topology/, evaluation/scenarios.json, evaluation fixtures
tests/                                                # focused contracts and integration checks
README.md, ARCHITECTURE.md, DEVELOPMENT.md, requirements.txt
```

Use Python 3.11 and create a local `.venv`; install with `python -m pip install -r requirements.txt`. The dependency manifest is not pinned, so exact resolution can vary. For offline deterministic reproduction from the project root:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app.evaluation --no-runtime
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app.evaluation --no-runtime --output /tmp/noc-evaluation.json
```

The evaluation CLI prints JSON to stdout and can also write it to `--output`. Inspect top-level status/counts and `metrics`, then each `scenarios` entry for expected/actual checks, failure categories, assessment state, and limitations. The optional model integration test requires `NOC_RUN_OLLAMA_INTEGRATION=1`, a running local Ollama service, and the configured model. `python -m app.main --demo` uses a fixed offline stub; `--demo-ollama` invokes configured Ollama. Neither should be confused with the synthetic evaluation doubles or real operations.

## H. Local Git milestone history

The seven commits are present on local `main`, in dependency order. They have not been pushed by this work:

| Commit | Message |
|---|---|
| `c6ad401bd72bf65b32a4ac2b726413bbf94d61db` | Add validated incident assessment and evidence contracts |
| `a704a9ccc5e07395805a3cadc96fddc31db5595d` | Add deterministic alarm normalization and deduplication |
| `851a5c8462023ffde5714a9b99aa3dca4ffc73d6` | Add deterministic alarm correlation |
| `8635b4b9b360b895abcd9a00f4c4f36c9fde192a` | Add declared topology analysis |
| `87cd79d939db2ae5f7365c8c6779829ff422d3e8` | Integrate bounded alarm and topology investigation flow |
| `61d9cbdee825a0f4d47d8a18ab69f2b0fe963da7` | Add repeatable synthetic evaluation report |
| `e003e41664090d2cf63b802fa6ae2e03425e9047` | Document operational reporting and target architecture |

The current branch was `main`, at `e003e416`, ahead of `origin/main` by seven commits before this report was created. No Git history action was performed for this task.

## I. Known gaps and prioritized roadmap

| Priority | Work | Value / risk addressed | Acceptance evidence |
|---|---|---|---|
| 1 — MVP reliability | Add explicit timeout and bounded retry/call policy around actual adapter invocations; surface elapsed/status safely. | Closes core FR-09/NFR-04 gap before connecting real sources. | Deterministic tests for timeout, retry ceiling, cancellation, and terminal status; no external services. |
| 2 — MVP traceability | Add per-run correlation ID and structured, redacted stage/tool/validation/error/timing records. | Closes FR-11 and enables safe reconstruction. | Tests prove each run’s stages/errors correlate without logging secret or unnecessary incident content. |
| 3 — MVP contracts | Replace dict-only adapters with typed tool contracts; decide whether FR-02 ticket/knowledge lookups are required for MVP and either implement synthetic adapters or record a scope decision. | Closes FR-02/FR-06 gaps while preserving offline tests. | Contract tests for empty, unavailable, malformed, timeout, provenance and references for each in-scope source. |
| 4 — MVP integration | Add explicit correlation rules for cross-element relationships only when topology/context semantics are agreed; include validated groups, affected elements/services in canonical assessment if required. | Addresses FR-04/FR-08 without treating proximity or potential impact as cause. | Labeled positive, negative, ambiguous, partial-topology, and provenance checks. |
| 5 — MVP recommendation contract | Add expected benefit and prerequisites (or explicitly narrow the accepted requirement) and define an actual human review boundary before operational use. | Addresses FR-10; avoids implying approval from metadata. | Schema, policy, and human-approval workflow tests; still no automatic execution. |
| 6 — MVP evaluation coverage | Expand diagnosis assertions beyond one evidence-reference check; test invalid model output through evaluation and separate structural/factual review. | Improves FR-15 evidence without overclaiming truth. | More labeled cases/reviewer rubric; clearly defined denominator and no claim of general accuracy. |
| 7 — Pilot readiness | Validate schemas, identity/time rules, topology coverage, freshness, security, retention, access, and operator usability with approved data; only then assess AWS target. | Reduces domain and operational risk. | Discovery artifacts, threat/security review, source-owner sign-off, and staged read-only pilot gates. |

Optional UI, RAG, broader multi-agent behavior, streaming infrastructure, cloud deployment, and remediation are not immediate requirements. They should remain deferred unless discovery and evaluation establish value.

## J. Interview preparation

Use first-person claims only for work you can accurately substantiate. The report supports explaining the repository and its design; it does not establish who authored each commit or any production experience.

### Two-minute project walkthrough

“I built a local synthetic-data prototype for telecom incident investigation. An incident is validated with Pydantic, then a bounded LangGraph workflow collects simulated alarm, telemetry, and inventory evidence. For one fixture-backed site, deterministic modules normalize and deduplicate structured alarms, correlate repeated alarm conditions, and traverse explicitly declared topology edges. The LLM is used for structured hypotheses and an advisory recommendation; the application constructs observed findings from collected evidence separately and rejects citations to missing or unsuccessful evidence. Provider or analysis failure and incomplete evidence lead to an explicit inconclusive result. The offline evaluation covers seven scenarios and eight runs, including duplicate, unrelated, incomplete-topology, conflict, tool/provider failure, and low-evidence cases. The latest run passed all deterministic checks, but those fixtures and fixed model doubles do not demonstrate real-world diagnostic accuracy. There are no live adapters, deployed AWS services, approval workflow, or remediation. My next engineering priorities would be enforced tool timeouts and run-level audit traces, then typed source adapters and broader evidence-backed evaluation.”

### Five-minute architecture walkthrough

1. **Boundary:** Start with the validated `Incident` schema and synthetic-only input. Explain that live carrier, OSS/BSS, ITSM, or customer data are deliberately absent.
2. **Collection:** Describe the three local lookup functions and `EvidenceRecord` status model. A successful empty alarm response is different from missing or malformed data. Evidence IDs and ownership are validated; current fixtures lack real observation times.
3. **Deterministic event path:** Explain source identity preservation, fallback fingerprint only when no source event ID exists, timezone-aware anchored five-minute deduplication, and retention of every row reference. Correlation is a separate 15-minute exact-condition recurrence rule and expresses relationship, not root cause.
4. **Topology:** Show provider-to-dependent directed edges, provenance-carrying shortest paths, explicit partial coverage, and the distinction between potential dependency and measured service health. Flat inventory does not create graph edges.
5. **Model boundary:** The model receives incident/evidence/derived context and returns `AssessmentDraft`. Deterministic code constructs observed facts; hypotheses and model-proposed conflicts remain labeled. Assessment citations must reference successful evidence. The confidence score is uncalibrated and the 0.5 gate is a prototype decision.
6. **Control flow and failure:** The graph is a single fixed pass, not an unrestricted agent loop. Input validation fails before collection; provider and Phase 2 errors produce terminal inconclusive output. Clarify that actual tool timeout enforcement/retry bounds and product audit IDs remain gaps.
7. **Evaluation and target:** Report the exact synthetic test metrics and their limits. Contrast `ARCHITECTURE.md`’s proposed AWS diagram with the local code: it is an option for discovery, not deployed architecture. State the next gates before real adapters: source semantics, timeout/trace controls, security review, and operator approval design.

### Ten likely questions and technically accurate answers

1. **How do you ground an LLM assessment?** The graph supplies evidence records with IDs and only successful evidence IDs can be cited by hypotheses/conflicts. The `IncidentAssessment` validator checks ownership and citation status. That is structural grounding; it does not prove the sentence is entailed by the cited payload, so semantic support still needs evaluation or human review.
2. **Why use deterministic rules and an LLM together?** Identity, deduplication, exact-condition correlation, schema checks, and declared-edge traversal are deterministic and auditable. The model is reserved for interpretation and recommendation drafting. This reduces variability in data handling while keeping model reasoning explicitly uncertain.
3. **Is correlation root-cause analysis?** No. The implemented rule groups distinct source event IDs that match the same alarm attributes within a fixed window. It does not prove common cause and currently does not use topology to join different elements.
4. **What does 1.0 precision/recall mean here?** In the current evaluation it means three labeled event pairs matched with zero pair FP/FN over this small synthetic run set. It cannot be generalized to live alarm traffic or unseen vendors/topologies.
5. **How does topology avoid false conclusions?** Only explicit directed edges are traversed and path provenance is retained. A missing path in partial coverage is unknown; a declared dependency gives potential impact only. Independent health evidence is absent, so observed impact remains unknown.
6. **What happens on a tool or provider failure?** Collection exceptions/statuses are retained in evidence; provider and deterministic Phase 2 failures return explicit inconclusive terminal assessments. Case F injects timeout/provider-failure behaviors in the harness. Actual enforced adapter timeouts and retry/backoff remain implementation work.
7. **Is the confidence score calibrated?** No. It is model-reported in [0,1], capped against supported hypothesis scores; 0.5 is a prototype acceptance gate. It is explicitly not a probability and should not drive operational action.
8. **Why LangGraph if the flow is linear?** It gives an explicit shared state and composable workflow nodes while keeping execution bounded and inspectable. The present use does not justify an open-ended agent loop; a simpler function pipeline could also serve, and orchestration should earn its complexity.
9. **What does the evidence grounding metric prove?** It checks that counted material claims cite evidence IDs that exist and were successfully collected. It does not score claim truth, source correctness, or entailment. That is why semantic claim truth is reported as unscored.
10. **What would you change before production?** Validate source schemas/identity/time semantics, implement typed read-only adapters, enforce timeout/retry/call limits, add run-correlated redacted audit logs and security controls, collect independent service-health data, test broader labeled cases, and define a real human approval process. Then run a staged read-only pilot; this repository itself is not production ready.

### Likely challenges and honest responses

- **“You say seven phases are complete, so why are requirements partial?”** Phase commits passed their scoped acceptance gates, but the authoritative MVP includes broader typed ticket/knowledge adapters, enforced timeout/retry limits, operational traceability, and assessment fields that remain incomplete. Phase acceptance and full-specification completeness are distinct.
- **“You say evidence based, but how do you know the model claim follows from evidence?”** We enforce reference existence and successful collection, not semantic entailment. The evaluation’s grounding metric is deliberately structural, and semantic diagnosis quality is not scored.
- **“Why have a service impact result without service-health data?”** It is labeled potential dependency. `observed_impact` remains unknown; the output does not claim an outage.
- **“Is the AWS architecture implemented?”** No. It is a proposed conceptual target in `ARCHITECTURE.md`; the repository runs locally and contains no cloud infrastructure or integration.
- **“Does your 100% completion mean 100% accurate?”** No. It means all eight harness runs produced terminal assessment objects. Five were inconclusive; semantic diagnosis accuracy is not measured.
- **“Where are the approval safeguards?”** Only risk/approval metadata exists. There is no approver identity, queue, authorization enforcement, audit, or action execution. It is not a human approval workflow.

### Fundamentals to be ready to explain

Be prepared to define and reason from first principles about: event identity versus row provenance; idempotency and deduplication windows; timezone-aware timestamps; precision/recall and denominator choice; directed reachability versus causality; evidence lineage and semantic entailment; uncertainty and calibration; schema validation versus truth validation; finite-state orchestration, retries, timeouts, and idempotency; least privilege, data minimization, retention, and audit; human approval versus advisory metadata; and the difference between local runtime, triage time, and MTTR. Avoid claiming expertise in production carrier operations or AWS implementation based only on these fixtures and diagrams.

## K. Documentation accuracy notes

The existing README, architecture, and development documents generally distinguish synthetic implementation from proposed AWS and state that ticket context is evaluator-injected, confidence uncalibrated, runtime not MTTR, and no remediation/approval workflow exists. This report preserves those caveats.

One potential wording overreach is the README’s broad statement “Phases 1–4 implemented”; it describes phase deliverables, not completion of every FR/NFR in the authoritative specification. The traceability tables above are the more precise status. Also, the `tools/knowledge.py` module exists but is not wired to graph collection; its presence should not be presented as a knowledge integration. Case F’s timeout is an injected evaluation condition rather than proof of a configured timeout guard around an actual tool call.
