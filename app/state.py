from typing import TypedDict, List, Any

from langgraph.graph.message import add_messages
from typing_extensions import Annotated


class NOCState(TypedDict, total=False):

    incident_id: str
    site: str
    technology: str
    severity: str
    description: str

    telemetry: dict
    alarms: dict
    network_path: dict

    evidence: List[str]

    diagnosis: str
    confidence: float
    recommended_action: str
    action_risk: str
    requires_human_approval: bool
    rationale: str

    messages: Annotated[List[Any], add_messages]

