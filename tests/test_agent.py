from app.graph import build_graph


def test_den_042_agent_investigation():

    incident = {
        "incident_id": "INC-2026-001",
        "site": "DEN-042",
        "technology": "5G",
        "severity": "SEV-2",
        "description": (
            "Customers are experiencing degraded 5G service "
            "with elevated latency and packet loss."
        ),
    }

    graph = build_graph()

    result = graph.invoke(incident)

    assert result["incident_id"] == "INC-2026-001"
    assert result["site"] == "DEN-042"
    assert len(result["messages"]) > 0

    