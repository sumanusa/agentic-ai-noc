"""Bounded incident assessment and fixture-backed deterministic analysis graph."""

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any, Literal

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from app.evidence import collect_evidence
from app.alarm_processing import deduplicate_alarms, normalize_alarms
from app.alarm_correlation import correlate_alarms
from app.llm import get_llm
from app.models.assessment import (
    ASSESSMENT_CONFIDENCE_GATE,
    AssessmentDraft,
    AssessmentFinding,
    IncidentAssessment,
)
from app.models.evidence import EvidenceRecord, make_evidence_record
from app.models.incident import Incident
from app.models.topology import TopologySnapshot
from app.state import AssessmentState
from app.topology_analysis import analyze_topology


_ALARM_FIXTURE = Path(__file__).resolve().parents[1] / "data/alarms/phase2d_integration_events.json"
_TOPOLOGY_FIXTURE = Path(__file__).resolve().parents[1] / "data/topology/phase2c_den042.json"


def _validate_input(state: AssessmentState) -> dict[str, Any]:
    incident = Incident.model_validate(state.get("incident", {}))
    return {"validated_incident": incident}


def _collect(state: AssessmentState) -> dict[str, Any]:
    return {"evidence": collect_evidence(state["validated_incident"])}


def _phase2_analysis(state: AssessmentState) -> dict[str, Any]:
    """Run the bounded, fixture-only deterministic alarm and topology pipeline."""
    incident: Incident = state["validated_incident"]
    evidence = list(state["evidence"])
    if incident.site != "DEN-042":
        return {"evidence": evidence, "phase2_status": "fixture_unavailable", "deterministic_findings": []}
    try:
        with _ALARM_FIXTURE.open(encoding="utf-8") as stream:
            alarm_rows = json.load(stream)
        alarm_evidence = make_evidence_record(
            source="phase2d_alarm_fixture", evidence_type="raw_alarm_events",
            incident_id=incident.incident_id, site=incident.site, value=alarm_rows,
            collection_status="success",
            limitation="Synthetic alarm fixture; not a live network observation.",
        )
        evidence.append(alarm_evidence)
        normalized = normalize_alarms(alarm_rows, evidence_id=alarm_evidence.evidence_id)
        deduplicated = deduplicate_alarms(normalized)
        correlated = correlate_alarms(deduplicated)

        with _TOPOLOGY_FIXTURE.open(encoding="utf-8") as stream:
            topology_data = json.load(stream)
        topology_evidence = make_evidence_record(
            source="phase2c_topology_fixture", evidence_type="declared_topology",
            incident_id=incident.incident_id, site=incident.site, value=topology_data,
            collection_status="success",
            limitation="Synthetic declared topology; not a live network observation.",
        )
        evidence.append(topology_evidence)
        topology = TopologySnapshot.model_validate(topology_data)
        affected = sorted({event.element_id for event in deduplicated.operational_events if event.element_id})
        topology_result = analyze_topology(topology, affected)
        findings = []
        for group in correlated.groups:
            event_refs = [
                reference.source_event_id or reference.source_record_id or f"row {reference.input_index}"
                for member in group.members for reference in member.original_event_references
            ]
            findings.append(AssessmentFinding(
                statement=("Deterministic correlation relates distinct alarm observations under "
                           f"{group.rule_id}; members: {', '.join(event_refs)}. This is not a root-cause finding."),
                kind="inference", evidence_ids=[alarm_evidence.evidence_id],
            ))
        for impact in topology_result.service_impacts:
            if impact.status == "potentially_affected":
                findings.append(AssessmentFinding(
                    statement=(f"Declared topology provides a potential dependency path to service "
                               f"{impact.service_id}; observed service impact remains unknown."),
                    kind="inference", evidence_ids=[topology_evidence.evidence_id],
                ))
        return {
            "evidence": evidence, "alarm_normalization": normalized,
            "alarm_deduplication": deduplicated, "alarm_correlation": correlated,
            "topology_analysis": topology_result, "phase2_status": "success",
            "deterministic_findings": findings,
        }
    except Exception as exc:
        failure = make_evidence_record(
            source="phase2_deterministic_analysis", evidence_type="analysis_failure",
            incident_id=incident.incident_id, site=incident.site,
            value={"error_type": type(exc).__name__}, collection_status="failure",
            limitation="Synthetic fixture analysis failed; no derived result is available.",
        )
        evidence.append(failure)
        return {"evidence": evidence, "phase2_status": "failure",
                "phase2_error": type(exc).__name__, "deterministic_findings": []}


def _deterministic_findings(evidence: list[EvidenceRecord]) -> list[AssessmentFinding]:
    findings = []
    for record in evidence:
        if record.collection_status != "success":
            continue
        if isinstance(record.value, dict):
            for key, value in record.value.items():
                values = value if isinstance(value, list) else [value]
                if isinstance(value, list) and not value:
                    statement = f"The simulated {record.source} source reported no {key} for site {record.site}."
                    findings.append(AssessmentFinding(
                        statement=statement,
                        kind="observed_fact",
                        evidence_ids=[record.evidence_id],
                    ))
                for item in values:
                    statement = f"The simulated {record.source} source reported {key}={item!r} for site {record.site}."
                    findings.append(AssessmentFinding(
                        statement=statement,
                        kind="observed_fact",
                        evidence_ids=[record.evidence_id],
                    ))
        else:
            findings.append(AssessmentFinding(
                statement=f"The simulated {record.source} source returned data for site {record.site}.",
                kind="observed_fact",
                evidence_ids=[record.evidence_id],
            ))
    return findings


def _inconclusive(
    incident: Incident,
    evidence: list[EvidenceRecord],
    *,
    generation_status: str,
    uncertainty: str,
    question: str,
) -> IncidentAssessment:
    missing = [
        f"{item.source}: {item.collection_status}"
        for item in evidence
        if item.collection_status != "success"
    ]
    return IncidentAssessment(
        incident_id=incident.incident_id,
        site=incident.site,
        incident_summary=incident.description,
        status="inconclusive",
        generation_status=generation_status,
        findings=_deterministic_findings(evidence),
        missing_evidence=missing,
        unresolved_questions=[question],
        confidence=0.0,
        uncertainty=uncertainty,
        recommended_action="Collect additional evidence before making a diagnosis.",
        rationale="The assessment is inconclusive because evidence or model output was insufficient.",
        action_risk="LOW",
        recommendation_type="investigative",
        human_approval_required=False,
        recommended_next_steps=["Review source availability and gather additional evidence before diagnosing."],
        evidence=evidence,
    )


def _plain_model_data(value: Any) -> Any:
    """Convert model instances recursively to data so Pydantic must validate them."""
    if isinstance(value, BaseModel):
        return _plain_model_data(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {key: _plain_model_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_model_data(item) for item in value]
    return value


def _analysis_prompt_data(value: Any) -> Any:
    """Serialize derived results without repeating their evidence IDs as citations."""
    plain = _plain_model_data(value)
    if isinstance(plain, dict):
        return {key: _analysis_prompt_data(item) for key, item in plain.items() if key != "evidence_id"}
    if isinstance(plain, list):
        return [_analysis_prompt_data(item) for item in plain]
    return plain


def _model_output_failure(
    incident: Incident,
    evidence: list[EvidenceRecord],
    *,
    status: Literal["llm_failure", "invalid_llm_output"],
    exception: Exception,
) -> IncidentAssessment:
    invalid = status == "invalid_llm_output"
    return _inconclusive(
        incident,
        evidence,
        generation_status=status,
        uncertainty=(
            "The model response did not satisfy the assessment schema."
            if invalid else "The model was unavailable or failed during assessment generation."
        ),
        question=(
            f"Retry assessment with a valid structured response ({type(exception).__name__})."
            if invalid else f"Restore model availability and retry ({type(exception).__name__})."
        ),
    )


def _assessment_node(
    state: AssessmentState,
    llm: Any,
    success_status: Literal["llm_success", "demo_stub"],
) -> dict[str, Any]:
    incident: Incident = state["validated_incident"]
    evidence: list[EvidenceRecord] = state["evidence"]
    if state.get("phase2_status") == "failure":
        return {"assessment": _inconclusive(
            incident, evidence, generation_status="not_attempted",
            uncertainty="Deterministic alarm or topology analysis failed; derived evidence is unavailable.",
            question=("Repair the synthetic Phase 2 analysis input or component "
                      f"({state.get('phase2_error', 'unknown failure')}) and retry."),
        )}
    successful = [item for item in evidence if item.collection_status == "success"]
    if not successful:
        return {"assessment": _inconclusive(
            incident,
            evidence,
            generation_status="not_attempted",
            uncertainty="No simulated evidence source returned usable data.",
            question="Can the alarm, telemetry, and inventory sources provide data for this site?",
        )}

    prompt = [
        SystemMessage(content=(
            "Assess this synthetic telecom incident using only the supplied evidence. "
            "Return hypotheses and interpretation, not observed facts. Cite only supplied "
            "evidence_id values. Do not invent services, topology, timestamps, or tool calls. "
            "A root cause is a hypothesis, never a confirmed fact. If support is weak, return "
            "no hypotheses, low confidence, and additional investigative steps. Correlation "
            "is a relationship between observations, not root-cause proof. Topology indicates "
            "potential dependency only; observed service impact remains unknown without health evidence. Return a "
            "recommended_action and rationale, rate its risk LOW/MEDIUM/HIGH, identify it as "
            "investigative or operational, and state whether approval is required. Operational "
            "actions and MEDIUM/HIGH risk recommendations require human approval. Never claim "
            "to execute an action."
        )),
        HumanMessage(content=(
            f"Incident: {incident.model_dump_json()}\n"
            f"Evidence: {[item.model_dump(mode='json') for item in evidence]}\n"
            f"Deterministic analysis: {json.dumps({key: _analysis_prompt_data(state[key]) for key in ('alarm_normalization', 'alarm_deduplication', 'alarm_correlation', 'topology_analysis') if key in state}, default=str)}"
        )),
    ]
    try:
        raw_draft = llm.with_structured_output(AssessmentDraft).invoke(prompt)
    except (ValidationError, OutputParserException) as exc:
        return {"assessment": _model_output_failure(
            incident, evidence, status="invalid_llm_output", exception=exc,
        )}
    except Exception as exc:
        return {"assessment": _model_output_failure(
            incident, evidence, status="llm_failure", exception=exc,
        )}

    try:
        draft = AssessmentDraft.model_validate(_plain_model_data(raw_draft))
    except Exception as exc:
        return {"assessment": _model_output_failure(
            incident, evidence, status="invalid_llm_output", exception=exc,
        )}

    available_ids = {
        item.evidence_id for item in evidence
        if item.collection_status == "success"
    }
    cited_ids = set()
    for hypothesis in draft.hypotheses:
        cited_ids.update(hypothesis.supporting_evidence_ids)
        cited_ids.update(hypothesis.contradicting_evidence_ids)
    for conflict in draft.conflicts:
        cited_ids.update(conflict.evidence_ids)
    if cited_ids - available_ids:
        invalid = ValueError("citation is absent or was not successfully collected")
        return {"assessment": _model_output_failure(
            incident, evidence, status="invalid_llm_output", exception=invalid,
        )}

    supported_hypotheses = [h for h in draft.hypotheses if h.supporting_evidence_ids]
    confidence = min(
        draft.confidence,
        max((h.confidence for h in supported_hypotheses), default=0.0),
    ) if supported_hypotheses else 0.0
    enough_evidence = bool(supported_hypotheses) and confidence >= ASSESSMENT_CONFIDENCE_GATE
    return {"assessment": IncidentAssessment(
        incident_id=incident.incident_id,
        site=incident.site,
        incident_summary=incident.description,
        status="assessed" if enough_evidence else "inconclusive",
        generation_status=success_status,
        findings=_deterministic_findings(evidence),
        hypotheses=draft.hypotheses,
        affected_services=[incident.affected_service] if incident.affected_service else [],
        missing_evidence=[
            f"{item.source}: {item.collection_status}"
            for item in evidence if item.collection_status != "success"
        ],
        conflicts=draft.conflicts,
        unresolved_questions=draft.unresolved_questions,
        confidence=confidence,
        uncertainty=draft.uncertainty,
        recommended_action=draft.recommended_action,
        rationale=draft.rationale,
        action_risk=draft.action_risk,
        recommendation_type=draft.recommendation_type,
        human_approval_required=draft.human_approval_required,
        recommended_next_steps=draft.recommended_next_steps,
        evidence=evidence,
    )}


def build_graph(
    llm: Any | None = None,
    *,
    success_status: Literal["llm_success", "demo_stub"] = "llm_success",
):
    """Build the assessment graph; pass an LLM-compatible stub for offline tests."""
    model = llm if llm is not None else get_llm()
    builder = StateGraph(AssessmentState)
    builder.add_node("validate_input", _validate_input)
    builder.add_node("collect_evidence", _collect)
    builder.add_node("deterministic_analysis", _phase2_analysis)
    builder.add_node("assess", lambda state: _assessment_node(state, model, success_status))
    builder.add_edge(START, "validate_input")
    builder.add_edge("validate_input", "collect_evidence")
    builder.add_edge("collect_evidence", "deterministic_analysis")
    builder.add_edge("deterministic_analysis", "assess")
    builder.add_edge("assess", END)
    return builder.compile()
