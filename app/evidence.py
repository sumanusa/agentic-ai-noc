import math
from typing import Any, Callable, Literal

from app.models.evidence import EvidenceRecord, make_evidence_record
from app.models.incident import Incident
from app.tools.alarms import get_site_alarms_data
from app.tools.inventory import get_network_path_data
from app.tools.telemetry import get_site_telemetry_data


SYNTHETIC_LIMITATION = "Synthetic local fixture; not a live network observation."
_TELEMETRY_FIELDS = (
    "packet_loss", "latency_ms", "cpu_percent", "memory_percent", "active_users",
)
_INVENTORY_FIELDS = (
    "site", "backhaul", "router", "interface", "secondary_backhaul",
)


def _classify_result(
    source: str, result: Any, expected_site: str,
) -> tuple[Literal["success", "missing", "failure"], str | None]:
    if not isinstance(result, dict):
        return "failure", "Tool returned a non-object result."

    if "error" in result:
        error = result.get("error")
        error_keys = {"error", "alarms"} if source == "alarms" else {"error"}
        if (
            isinstance(error, str) and error.strip()
            and set(result) <= error_keys
            and (source != "alarms" or result.get("alarms") == [])
        ):
            return "missing", error
        return "failure", "Tool returned a malformed error result."

    if source == "alarms":
        alarms = result.get("alarms")
        if isinstance(alarms, list) and all(isinstance(item, str) and item.strip() for item in alarms):
            return "success", None  # An empty list is a valid no-alarms response.
        return "failure", "Alarm result must contain a list of non-empty alarm names."

    if source == "telemetry":
        if not all(field in result for field in _TELEMETRY_FIELDS):
            return "failure", "Telemetry result is missing required measurements."
        if any(
            isinstance(result[field], bool)
            or not isinstance(result[field], (int, float))
            or not math.isfinite(result[field])
            for field in _TELEMETRY_FIELDS
        ):
            return "failure", "Telemetry measurements must be finite numbers."
        return "success", None

    if source == "inventory":
        if result.get("site") != expected_site:
            return "failure", "Inventory result site does not match the requested site."
        if not all(
            isinstance(result.get(field), str) and result[field].strip()
            for field in _INVENTORY_FIELDS
        ):
            return "failure", "Inventory result is missing required path fields."
        return "success", None

    return "failure", "No result contract is defined for this source."


def collect_evidence(incident: Incident) -> list[EvidenceRecord]:
    """Collect each simulated source once and classify its declared result contract."""
    sources: list[tuple[str, str, Callable[[str], Any]]] = [
        ("alarms", "alarm", get_site_alarms_data),
        ("telemetry", "telemetry", get_site_telemetry_data),
        ("inventory", "network_path", get_network_path_data),
    ]
    records = []
    for source, evidence_type, lookup in sources:
        try:
            value = lookup(incident.site)
            status, detail = _classify_result(source, value, incident.site)
            limitation = SYNTHETIC_LIMITATION
            if detail:
                limitation = f"{SYNTHETIC_LIMITATION} {detail}"
        except Exception as exc:  # Keep source failures explicit and local to the source.
            value = {"error_type": type(exc).__name__}
            status = "failure"
            limitation = f"{SYNTHETIC_LIMITATION} Source collection failed."
        records.append(make_evidence_record(
            source=source,
            evidence_type=evidence_type,
            incident_id=incident.incident_id,
            site=incident.site,
            value=value,
            collection_status=status,
            limitation=limitation,
        ))
    return records
