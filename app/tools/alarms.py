from typing import Dict
from langchain_core.tools import tool


def get_site_alarms_data(site: str) -> Dict:
    """
    Core network alarm service implementation.
    """

    alarms = {
        "DEN-042": {
            "alarms": [
                "CELL_UNAVAILABLE",
                "HIGH_PACKET_LOSS",
                "BACKHAUL_LATENCY_HIGH",
            ]
        }
    }

    return alarms.get(
        site,
        {
            "alarms": [],
            "error": f"No alarm data available for {site}",
        },
    )


@tool
def get_site_alarms(site: str) -> Dict:
    """
    Retrieve active network alarms for a telecom site.
    """

    return get_site_alarms_data(site)