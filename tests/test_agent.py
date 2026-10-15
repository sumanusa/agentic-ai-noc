"""Optional local-Ollama integration test; excluded from ordinary CI runs."""

import os

import pytest

from app.graph import build_graph


pytestmark = pytest.mark.skipif(
    os.getenv("NOC_RUN_OLLAMA_INTEGRATION") != "1",
    reason="set NOC_RUN_OLLAMA_INTEGRATION=1 to run the local Ollama integration",
)


def test_den_042_agent_investigation():
    incident = {
        "incident_id": "INC-2026-001",
        "site": "DEN-042",
        "technology": "5G",
        "severity": "SEV-2",
        "description": "Degraded 5G service with elevated latency and packet loss.",
    }
    result = build_graph().invoke({"incident": incident})
    assert result["assessment"].incident_id == "INC-2026-001"
