from typing import Any, Literal, TypedDict

from app.models.assessment import AssessmentFinding, IncidentAssessment
from app.models.alarm import AlarmDeduplicationResult, AlarmNormalizationResult
from app.models.correlation import AlarmCorrelationResult
from app.models.evidence import EvidenceRecord
from app.models.incident import Incident
from app.models.topology import TopologyAnalysisResult


class AssessmentState(TypedDict, total=False):
    incident: dict[str, Any]
    validated_incident: Incident
    evidence: list[EvidenceRecord]
    alarm_normalization: AlarmNormalizationResult
    alarm_deduplication: AlarmDeduplicationResult
    alarm_correlation: AlarmCorrelationResult
    topology_analysis: TopologyAnalysisResult
    deterministic_findings: list[AssessmentFinding]
    phase2_status: Literal["success", "fixture_unavailable", "failure"]
    phase2_error: str
    assessment: IncidentAssessment
