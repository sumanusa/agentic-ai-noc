import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceRecord(BaseModel):
    """A provenance-carrying result from a simulated data source."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    evidence_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    evidence_type: str = Field(min_length=1)
    incident_id: str = Field(min_length=1)
    site: str = Field(min_length=1)
    timestamp_status: Literal["available", "unavailable"]
    observed_at: str | None = None
    value: Any = None
    collection_status: Literal["success", "missing", "failure"]
    limitation: str | None = None

    @model_validator(mode="after")
    def timestamp_status_matches_value(self):
        if (self.timestamp_status == "available") != (self.observed_at is not None):
            raise ValueError("timestamp_status must match whether observed_at is present")
        return self


def make_evidence_record(
    *, source: str, evidence_type: str, incident_id: str, site: str,
    value: Any, collection_status: Literal["success", "missing", "failure"],
    limitation: str | None = None, observed_at: str | None = None,
) -> EvidenceRecord:
    """Build a stable ID from the synthetic source result and its context."""
    canonical = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    fingerprint = "|".join((source, evidence_type, incident_id, site, canonical, collection_status))
    evidence_id = f"ev-{hashlib.sha256(fingerprint.encode()).hexdigest()[:16]}"
    return EvidenceRecord(
        evidence_id=evidence_id,
        source=source,
        evidence_type=evidence_type,
        incident_id=incident_id,
        site=site,
        timestamp_status="available" if observed_at else "unavailable",
        observed_at=observed_at,
        value=value,
        collection_status=collection_status,
        limitation=limitation,
    )
