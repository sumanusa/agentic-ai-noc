import re

import pytest
from pydantic import ValidationError

from app.evidence import SYNTHETIC_LIMITATION, collect_evidence
from app.graph import _deterministic_findings, build_graph
from app.models.assessment import AssessmentDraft, EvidenceConflict, RootCauseHypothesis
from app.models.incident import Incident


INCIDENT = {
    "incident_id": "INC-2026-001", "site": "DEN-042", "technology": "5G",
    "severity": "SEV-2", "description": "Elevated latency and packet loss.",
}


class StubLLM:
    def __init__(self, make_draft=None, error=None):
        self.make_draft = make_draft
        self.error = error

    def with_structured_output(self, schema):
        assert schema is AssessmentDraft
        return self

    def invoke(self, messages):
        if self.error:
            raise self.error
        content = messages[-1].content
        ids = re.findall(r"ev-[a-f0-9]{16}", content)
        return self.make_draft(ids)


def run(make_draft, incident=INCIDENT):
    return build_graph(llm=StubLLM(make_draft)).invoke({"incident": incident})["assessment"]


def supported_draft(ids):
    return AssessmentDraft(
        hypotheses=[{
            "statement": "Possible backhaul performance degradation.",
            "confidence": 0.78,
            "supporting_evidence_ids": ids,
        }],
        confidence=0.78,
        uncertainty="The fixture does not establish a confirmed root cause.",
        recommended_action="Review backhaul counters.",
        rationale="The alarm and telemetry fixtures indicate a possible performance issue.",
        action_risk="LOW",
        recommendation_type="investigative",
        human_approval_required=False,
        recommended_next_steps=["Review backhaul counters and recent maintenance."],
    )


def draft_without_hypotheses(ids, **updates):
    fields = {
        "hypotheses": [], "confidence": 0.2,
        "uncertainty": "The evidence is insufficient for a root-cause hypothesis.",
        "recommended_action": "Collect current backhaul counters.",
        "rationale": "The available fixture evidence does not establish a cause.",
        "action_risk": "LOW", "recommendation_type": "investigative",
        "human_approval_required": False,
    }
    fields.update(updates)
    return AssessmentDraft(**fields)


def test_evidence_has_stable_provenance_and_synthetic_limitation():
    incident = Incident.model_validate(INCIDENT)
    first = collect_evidence(incident)
    second = collect_evidence(incident)
    assert [e.evidence_id for e in first] == [e.evidence_id for e in second]
    assert {e.source for e in first} == {"alarms", "telemetry", "inventory"}
    assert all(e.timestamp_status == "unavailable" and e.observed_at is None for e in first)
    assert all(e.limitation == SYNTHETIC_LIMITATION for e in first)


def test_source_exception_becomes_failure_evidence(monkeypatch):
    from app import evidence as evidence_module

    def unavailable(_site):
        raise TimeoutError("fixture source timeout")

    monkeypatch.setattr(evidence_module, "get_site_telemetry_data", unavailable)
    records = collect_evidence(Incident.model_validate(INCIDENT))
    telemetry = next(record for record in records if record.source == "telemetry")
    assert telemetry.collection_status == "failure"
    assert telemetry.value == {"error_type": "TimeoutError"}
    assert "not a live network observation" in telemetry.limitation


@pytest.mark.parametrize(("result", "expected_status"), [
    ({"alarms": []}, "success"),
    ({"alarms": ["CELL_UNAVAILABLE"]}, "success"),
    ({"alarms": [], "error": "No alarm data available"}, "missing"),
    ({}, "failure"),
    ({"alarms": "none"}, "failure"),
    ([], "failure"),
])
def test_alarm_result_contract_distinguishes_empty_missing_and_malformed(
    monkeypatch, result, expected_status,
):
    from app import evidence as evidence_module

    monkeypatch.setattr(evidence_module, "get_site_alarms_data", lambda _site: result)
    records = collect_evidence(Incident.model_validate(INCIDENT))
    alarm = next(record for record in records if record.source == "alarms")
    assert alarm.collection_status == expected_status
    if expected_status == "success" and result == {"alarms": []}:
        assert any("reported no alarms" in f.statement for f in _deterministic_findings([alarm]))


def test_malformed_telemetry_and_inventory_results_are_failures(monkeypatch):
    from app import evidence as evidence_module

    monkeypatch.setattr(evidence_module, "get_site_telemetry_data", lambda _site: {})
    monkeypatch.setattr(evidence_module, "get_network_path_data", lambda _site: {"site": "DEN-042"})
    records = collect_evidence(Incident.model_validate(INCIDENT))
    assert next(e for e in records if e.source == "telemetry").collection_status == "failure"
    assert next(e for e in records if e.source == "inventory").collection_status == "failure"


def test_inventory_result_for_a_different_site_is_failure_evidence(monkeypatch):
    from app import evidence as evidence_module

    monkeypatch.setattr(evidence_module, "get_network_path_data", lambda _site: {
        "site": "SLC-001", "backhaul": "BH-1", "router": "RTR-1",
        "interface": "xe-0/0/1", "secondary_backhaul": "BH-2",
    })
    records = collect_evidence(Incident.model_validate(INCIDENT))
    inventory = next(record for record in records if record.source == "inventory")
    assert inventory.collection_status == "failure"
    assert "does not match" in inventory.limitation


def test_complete_incident_to_assessment_path_without_ollama():
    assessment = run(supported_draft)
    assert assessment.incident_id == INCIDENT["incident_id"]
    assert assessment.status == "assessed"
    assert assessment.generation_status == "llm_success"
    assert assessment.confidence_interpretation.endswith("not_probability")
    assert all(f.kind == "observed_fact" for f in assessment.findings)
    assert any("packet_loss=18.2" in finding.statement for finding in assessment.findings)
    assert all(h.supporting_evidence_ids for h in assessment.hypotheses)
    assert assessment.affected_services == []
    assert assessment.recommended_action == "Review backhaul counters."
    assert assessment.rationale
    assert assessment.action_risk == "LOW"
    assert assessment.human_approval_required is False
    evidence_ids = {e.evidence_id for e in assessment.evidence}
    assert set(assessment.hypotheses[0].supporting_evidence_ids) <= evidence_ids


def test_insufficient_and_missing_evidence_stays_inconclusive():
    assessment = run(lambda ids: draft_without_hypotheses(
        ids, unresolved_questions=["Can additional site telemetry be collected?"],
        recommended_next_steps=["Collect fresh telemetry."],
    ), {**INCIDENT, "site": "UNKNOWN-SITE"})
    assert assessment.status == "inconclusive"
    assert assessment.generation_status == "not_attempted"
    assert assessment.hypotheses == []
    assert len(assessment.missing_evidence) == 3
    assert assessment.unresolved_questions


def test_conflicting_evidence_is_explicit_and_referenced():
    def draft(ids):
        return draft_without_hypotheses(
            ids, confidence=0.25,
            conflicts=[{"description": "Two sources disagree.", "evidence_ids": ids[:2]}],
        )
    assessment = run(draft)
    assert assessment.status == "inconclusive"
    assert assessment.conflicts[0].description == "Two sources disagree."
    assert len(assessment.conflicts[0].evidence_ids) == 2
    assert assessment.conflicts[0].verification_status == "unverified_model_proposal"


@pytest.mark.parametrize(("draft_score", "hypothesis_score", "status", "result_score"), [
    (0.49, 0.49, "inconclusive", 0.49),
    (0.50, 0.50, "assessed", 0.50),
    (0.90, 0.49, "inconclusive", 0.49),
    (0.49, 0.90, "inconclusive", 0.49),
    (0.80, 0.75, "assessed", 0.75),
])
def test_confidence_gate_preserves_supported_hypotheses(
    draft_score, hypothesis_score, status, result_score,
):
    def draft(ids):
        value = supported_draft(ids).model_dump()
        value["confidence"] = draft_score
        value["hypotheses"][0]["confidence"] = hypothesis_score
        return AssessmentDraft.model_validate(value)

    assessment = run(draft)
    assert assessment.status == status
    assert assessment.confidence == pytest.approx(result_score)
    assert len(assessment.hypotheses) == 1
    assert assessment.hypotheses[0].confidence == pytest.approx(hypothesis_score)


def test_operational_or_medium_risk_recommendation_requires_approval():
    def draft(ids):
        value = supported_draft(ids).model_dump()
        value.update(recommendation_type="operational", action_risk="MEDIUM", human_approval_required=False)
        return value

    assessment = run(draft)
    assert assessment.recommendation_type == "operational"
    assert assessment.human_approval_required is True


def test_invalid_model_output_and_unknown_evidence_citation_are_inconclusive():
    malformed = run(lambda ids: {"confidence": "not-a-number"})
    assert malformed.status == "inconclusive"
    assert malformed.generation_status == "invalid_llm_output"

    invented_reference = run(lambda ids: AssessmentDraft(
        hypotheses=[{
            "statement": "Unsupported cause", "confidence": 0.9,
            "supporting_evidence_ids": ["ev-0000000000000000"],
        }], confidence=0.9, uncertainty="Certain.",
    ))
    assert invented_reference.status == "inconclusive"
    assert invented_reference.generation_status == "invalid_llm_output"


@pytest.mark.parametrize("malformed_output", [
    "empty hypothesis statement",
    "out of range hypothesis confidence",
    "malformed nested conflict instance",
])
def test_preconstructed_malformed_models_are_revalidated(malformed_output):
    def make_malformed(ids):
        if malformed_output == "empty hypothesis statement":
            hypothesis = RootCauseHypothesis.model_construct(
                statement="", confidence=0.8, supporting_evidence_ids=ids,
                contradicting_evidence_ids=[],
            )
            return AssessmentDraft.model_construct(
                hypotheses=[hypothesis], conflicts=[], unresolved_questions=[],
                confidence=0.8, uncertainty="model output",
                recommended_action="Action", rationale="Reason", action_risk="LOW",
                recommendation_type="investigative", human_approval_required=False,
                recommended_next_steps=[],
            )
        if malformed_output == "out of range hypothesis confidence":
            hypothesis = RootCauseHypothesis.model_construct(
                statement="Possible cause", confidence=1.5,
                supporting_evidence_ids=ids, contradicting_evidence_ids=[],
            )
            return AssessmentDraft.model_construct(
                hypotheses=[hypothesis], conflicts=[], unresolved_questions=[],
                confidence=0.8, uncertainty="model output",
                recommended_action="Action", rationale="Reason", action_risk="LOW",
                recommendation_type="investigative", human_approval_required=False,
                recommended_next_steps=[],
            )
        malformed_conflict = EvidenceConflict.model_construct(
            description="", evidence_ids=ids[:2], verification_status="verified",
        )
        return AssessmentDraft.model_construct(
            hypotheses=[], conflicts=[malformed_conflict], unresolved_questions=[],
            confidence=0.2, uncertainty="model output", recommended_action="Action",
            rationale="Reason", action_risk="LOW", recommendation_type="investigative",
            human_approval_required=False, recommended_next_steps=[],
        )

    result = run(make_malformed)
    assert result.status == "inconclusive"
    assert result.generation_status == "invalid_llm_output"
    assert result.hypotheses == []


def test_provider_failure_is_visible_and_inconclusive():
    result = build_graph(llm=StubLLM(error=RuntimeError("provider unavailable"))).invoke(
        {"incident": INCIDENT}
    )["assessment"]
    assert result.status == "inconclusive"
    assert result.generation_status == "llm_failure"
    assert result.hypotheses == []


def test_graph_rejects_invalid_input_before_collecting_evidence():
    with pytest.raises(ValidationError):
        build_graph(llm=StubLLM(lambda ids: supported_draft(ids))).invoke({
            "incident": {"incident_id": "INC-1", "site": "DEN-042"}
        })
