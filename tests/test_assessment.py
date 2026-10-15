import pytest
from pydantic import ValidationError

from app.models.assessment import (
    AssessmentFinding,
    EvidenceConflict,
    IncidentAssessment,
    RootCauseHypothesis,
)
from app.models.evidence import make_evidence_record


def evidence(*, incident_id="INC-1", site="DEN-042", status="success", value=None):
    return make_evidence_record(
        source="telemetry", evidence_type="telemetry", incident_id=incident_id,
        site=site, value=value or {"packet_loss": 18.2}, collection_status=status,
    )


def assessment_for(records, evidence_ids=None, **updates):
    ids = evidence_ids if evidence_ids is not None else [records[0].evidence_id]
    fields = {
        "incident_id": "INC-1", "site": "DEN-042", "incident_summary": "Packet loss",
        "status": "assessed", "generation_status": "llm_success",
        "findings": [AssessmentFinding(
            statement="Telemetry returned a packet-loss measurement.",
            kind="observed_fact", evidence_ids=[ids[0]],
        )],
        "hypotheses": [RootCauseHypothesis(
            statement="Possible backhaul degradation", confidence=0.75,
            supporting_evidence_ids=ids,
        )],
        "confidence": 0.75, "uncertainty": "Other causes have not been ruled out.",
        "recommended_action": "Review the backhaul counters.",
        "rationale": "The telemetry indicates elevated packet loss.",
        "action_risk": "LOW", "recommendation_type": "investigative",
        "human_approval_required": False, "evidence": records,
    }
    fields.update(updates)
    return IncidentAssessment(**fields)


def test_assessment_validates_confidence_and_evidence_references():
    record = evidence()
    assessment = assessment_for([record])
    assert assessment.schema_version == "1.0"
    assert assessment.hypotheses[0].supporting_evidence_ids == [record.evidence_id]

    with pytest.raises(ValidationError, match="unknown evidence IDs"):
        assessment_for([record], evidence_ids=["ev-does-not-exist"])

    with pytest.raises(ValidationError):
        assessment_for([record], confidence=1.1)


@pytest.mark.parametrize("record, message", [
    (evidence(incident_id="INC-OTHER"), "different incident"),
    (evidence(site="SLC-001"), "different site"),
])
def test_assessment_rejects_evidence_from_another_owner(record, message):
    with pytest.raises(ValidationError, match=message):
        assessment_for([record])


@pytest.mark.parametrize("status", ["missing", "failure"])
def test_assessment_rejects_citing_unavailable_evidence(status):
    record = evidence(status=status, value={"error": "unavailable"})
    with pytest.raises(ValidationError, match="not successfully collected"):
        assessment_for([record])


def test_assessment_rejects_duplicate_evidence_ids():
    record = evidence()
    with pytest.raises(ValidationError, match="evidence IDs must be unique"):
        assessment_for([record, record])


def test_assessment_requires_supported_hypothesis_for_assessed_status():
    record = evidence()
    with pytest.raises(ValidationError, match="requires confidence"):
        assessment_for([record], confidence=0.49)
    result = assessment_for([record], status="inconclusive", confidence=0.49)
    assert result.hypotheses[0].statement == "Possible backhaul degradation"
    assert result.hypotheses[0].supporting_evidence_ids == [record.evidence_id]


def test_operational_or_non_low_risk_recommendations_require_approval():
    record = evidence()
    result = assessment_for(
        [record], recommendation_type="operational", action_risk="LOW",
        human_approval_required=False,
    )
    assert result.human_approval_required is True


def test_model_proposed_conflict_is_explicitly_unverified():
    conflict = EvidenceConflict(
        description="These records appear to disagree.",
        evidence_ids=["ev-1", "ev-2"],
    )
    assert conflict.verification_status == "unverified_model_proposal"
