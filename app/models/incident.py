from typing import List
from pydantic import BaseModel


class Incident(BaseModel):
    incident_id: str
    site: str
    technology: str
    severity: str
    description: str
    alarms: List[str]
    packet_loss: float
    latency_ms: float
    active_users: int

class IncidentAssessment(BaseModel):
    incident_id: str
    severity: str
    affected_service: str
    probable_root_cause: str
    evidence: List[str]
    confidence: float
    recommended_action: str
    action_risk: str
    requires_human_approval: bool
    rationale: str

