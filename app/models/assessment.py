from typing import List

from pydantic import BaseModel, Field


class IncidentAssessment(BaseModel):
    """
    Structured output produced by the NOC investigation agent.
    """

    incident_id: str
    site: str

    root_cause: str = Field(
        description="Most likely root cause based on the available evidence."
    )

    evidence: List[str] = Field(
        description="Factual evidence supporting the root cause."
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Agent confidence in the root cause assessment."
    )

    recommended_action: str = Field(
        description="Recommended next diagnostic or remediation action."
    )

    risk: str = Field(
        description="Risk level of the recommended action: LOW, MEDIUM, or HIGH."
    )

    human_approval_required: bool = Field(
        description="Whether human approval should be required before the action."
    )

