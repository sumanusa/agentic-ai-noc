from typing import Dict
from langchain_core.tools import tool


def get_network_path_data(site: str) -> Dict:
    """
    Core network inventory/path service implementation.
    """

    network = {
        "DEN-042": {
            "site": "DEN-042",
            "backhaul": "BH-7731",
            "router": "RTR-DEN-18",
            "interface": "xe-0/0/3",
            "secondary_backhaul": "BH-7731-B",
        }
    }

    return network.get(
        site,
        {
            "error": f"No network information available for {site}"
        },
    )


@tool
def get_network_path(site: str) -> Dict:
    """
    Retrieve network topology and backhaul information.
    """

    return get_network_path_data(site)
