from app.tools.alarms import get_site_alarms_data
from app.tools.inventory import get_network_path_data


def test_den_042_alarms():
    result = get_site_alarms_data("DEN-042")

    assert "CELL_UNAVAILABLE" in result["alarms"]
    assert "HIGH_PACKET_LOSS" in result["alarms"]


def test_den_042_network_path():
    result = get_network_path_data("DEN-042")

    assert result["router"] == "RTR-DEN-18"
    assert result["interface"] == "xe-0/0/3"

    