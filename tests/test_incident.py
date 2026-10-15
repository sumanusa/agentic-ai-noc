import pytest
from pydantic import ValidationError

from app.models.incident import Incident


def valid_payload():
    return {
        "incident_id": "INC-2026-001", "site": "DEN-042", "technology": "5G",
        "severity": "SEV-2", "description": "Elevated latency and packet loss.",
    }


def test_valid_incident_and_optional_context():
    incident = Incident.model_validate({
        **valid_payload(), "affected_service": "5G access", "related_event_refs": [" EVT-1 "],
        "occurred_at": "2026-10-14T12:00:00Z",
    })
    assert incident.related_event_refs == ["EVT-1"]
    assert incident.affected_service == "5G access"
    assert incident.occurred_at is not None


@pytest.mark.parametrize("updates", [
    {"site": ""}, {"incident_id": " "}, {"severity": "x" * 31},
    {"description": "x" * 2001}, {"occurred_at": "not-a-timestamp"}, {"unexpected": True},
    {"related_event_refs": [""]},
])
def test_invalid_or_boundary_incident_values_are_rejected(updates):
    payload = valid_payload()
    payload.update(updates)
    with pytest.raises(ValidationError):
        Incident.model_validate(payload)


def test_missing_required_incident_fields_are_rejected():
    with pytest.raises(ValidationError, match="description"):
        Incident.model_validate({"incident_id": "INC-1", "site": "DEN-042"})
