from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.evidence import EvidenceRecord


ASSESSMENT_CONFIDENCE_GATE = 0.5


def _unique_ids(ids: list[str]) -> list[str]:
    if len(ids) != len(set(ids)):
        raise ValueError("evidence references must be unique")
    return ids


class AssessmentFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    statement: str = Field(min_length=1)
    kind: Literal["observed_fact", "inference"]
    evidence_ids: list[str] = Field(min_length=1)

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence_ids(cls, ids: list[str]) -> list[str]:
        return _unique_ids(ids)


class RootCauseHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    statement: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("supporting_evidence_ids", "contradicting_evidence_ids")
    @classmethod
    def unique_evidence_ids(cls, ids: list[str]) -> list[str]:
        return _unique_ids(ids)

    @model_validator(mode="after")
    def require_evidence_reference(self):
        if not (self.supporting_evidence_ids or self.contradicting_evidence_ids):
            raise ValueError("a hypothesis must reference supporting or contradicting evidence")
        return self


class EvidenceConflict(BaseModel):
    """A model-proposed conflict; it is not verified by deterministic rules."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    description: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=2)
    verification_status: Literal["unverified_model_proposal"] = "unverified_model_proposal"

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence_ids(cls, ids: list[str]) -> list[str]:
        return _unique_ids(ids)


class AssessmentDraft(BaseModel):
    """LLM-authored interpretations only; observed facts are built separately."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    hypotheses: list[RootCauseHypothesis] = Field(default_factory=list)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: str = Field(min_length=1)
    recommended_action: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    action_risk: Literal["LOW", "MEDIUM", "HIGH"]
    recommendation_type: Literal["investigative", "operational"]
    human_approval_required: bool
    recommended_next_steps: list[str] = Field(default_factory=list)


class IncidentAssessment(BaseModel):
    """Canonical, versioned output with evidence ownership and status invariants."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    schema_version: Literal["1.0"] = "1.0"
    incident_id: str = Field(min_length=1)
    site: str = Field(min_length=1)
    incident_summary: str = Field(min_length=1)
    status: Literal["assessed", "inconclusive"]
    generation_status: Literal[
        "llm_success", "llm_failure", "invalid_llm_output", "demo_stub", "not_attempted"
    ]
    findings: list[AssessmentFinding] = Field(default_factory=list)
    hypotheses: list[RootCauseHypothesis] = Field(default_factory=list)
    affected_services: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_interpretation: Literal[
        "uncalibrated_model_reported_0_to_1_not_probability"
    ] = "uncalibrated_model_reported_0_to_1_not_probability"
    uncertainty: str = Field(min_length=1)
    recommended_action: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    action_risk: Literal["LOW", "MEDIUM", "HIGH"]
    recommendation_type: Literal["investigative", "operational"]
    human_approval_required: bool
    recommended_next_steps: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_integrity(self):
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        if len(evidence_by_id) != len(self.evidence):
            raise ValueError("assessment evidence IDs must be unique")
        for item in self.evidence:
            if item.incident_id != self.incident_id:
                raise ValueError("evidence belongs to a different incident")
            if item.site != self.site:
                raise ValueError("evidence belongs to a different site")

        referenced_ids: set[str] = set()
        for finding in self.findings:
            referenced_ids.update(finding.evidence_ids)
        for hypothesis in self.hypotheses:
            referenced_ids.update(hypothesis.supporting_evidence_ids)
            referenced_ids.update(hypothesis.contradicting_evidence_ids)
        for conflict in self.conflicts:
            referenced_ids.update(conflict.evidence_ids)
        unknown_ids = referenced_ids - evidence_by_id.keys()
        if unknown_ids:
            raise ValueError(f"assessment references unknown evidence IDs: {sorted(unknown_ids)}")
        unsuccessful = [
            evidence_id for evidence_id in referenced_ids
            if evidence_by_id[evidence_id].collection_status != "success"
        ]
        if unsuccessful:
            raise ValueError(f"assessment cites evidence that was not successfully collected: {sorted(unsuccessful)}")

        if self.status == "assessed":
            supported = [h for h in self.hypotheses if h.supporting_evidence_ids]
            if not supported:
                raise ValueError("assessed status requires a supported hypothesis")
            if self.confidence < ASSESSMENT_CONFIDENCE_GATE:
                raise ValueError("assessed status requires confidence at or above the assessment gate")

        if self.recommendation_type == "operational" or self.action_risk != "LOW":
            self.human_approval_required = True
        return self
