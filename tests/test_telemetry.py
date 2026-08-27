from app.tools.telemetry import get_site_telemetry_data


def test_den_042_telemetry():
    result = get_site_telemetry_data("DEN-042")

    assert result["packet_loss"] == 18.2
    assert result["latency_ms"] == 247

    