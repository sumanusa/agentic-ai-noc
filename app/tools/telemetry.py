from typing import Dict
from langchain_core.tools import tool


def get_site_telemetry_data(site: str) -> Dict:
    """
    Core telemetry service implementation.

    This function is independent of the agent framework.
    """

    telemetry = {
        "DEN-042": {
            "packet_loss": 18.2,
            "latency_ms": 247,
            "cpu_percent": 81,
            "memory_percent": 72,
            "active_users": 187,
        }
    }

    return telemetry.get(
        site,
        {
            "error": f"No telemetry available for {site}"
        },
    )


@tool
def get_site_telemetry(site: str) -> Dict:
    """
    Retrieve network telemetry for a telecom site.
    """

    return get_site_telemetry_data(site)

