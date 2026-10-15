from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Incident(BaseModel):
    """Validated input contract for one synthetic incident."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    incident_id: str = Field(min_length=1, max_length=100)
    site: str = Field(min_length=1, max_length=100)
    technology: str = Field(min_length=1, max_length=50)
    severity: str = Field(min_length=1, max_length=30)
    description: str = Field(min_length=1, max_length=2000)
    occurred_at: datetime | None = None
    affected_service: str | None = Field(default=None, max_length=200)
    related_event_refs: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("related_event_refs")
    @classmethod
    def validate_event_refs(cls, refs: list[str]) -> list[str]:
        if any(not ref.strip() or len(ref) > 100 for ref in refs):
            raise ValueError("event references must be non-empty and at most 100 characters")
        return [ref.strip() for ref in refs]
