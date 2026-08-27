def build_incident_prompt(
    incident_id: str,
    site: str,
    technology: str,
    severity: str,
    description: str,
) -> str:

    return f"""
Investigate the following network incident.

Incident ID: {incident_id}
Site: {site}
Technology: {technology}
Severity: {severity}

Incident Description:
{description}

Determine what information you need to investigate this incident.
Use the available NOC tools to gather factual evidence.
"""

