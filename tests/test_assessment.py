from app.models.assessment import IncidentAssessment


def test_incident_assessment():

    assessment = IncidentAssessment(
        incident_id="INC-2026-001",
        site="DEN-042",
        root_cause="Backhaul degradation",
        evidence=[
            "18.2% packet loss",
            "247 ms latency",
            "BACKHAUL_LATENCY_HIGH alarm",
        ],
        confidence=0.89,
        recommended_action="Fail over to the secondary backhaul.",
        risk="MEDIUM",
        human_approval_required=True,
    )

    assert assessment.incident_id == "INC-2026-001"
    assert assessment.site == "DEN-042"
    assert 0 <= assessment.confidence <= 1
    assert assessment.human_approval_required is True

    