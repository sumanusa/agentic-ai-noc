"""CLI entry point for readiness checks and a reproducible synthetic demo."""

import argparse
import re

from app.graph import build_graph
from app.models.assessment import AssessmentDraft


DEMO_INCIDENT = {
    "incident_id": "INC-2026-001",
    "site": "DEN-042",
    "technology": "5G",
    "severity": "SEV-2",
    "description": "Degraded 5G service with elevated latency and packet loss.",
}


class _DemoStructuredModel:
    """Fixed offline stand-in; its output is labelled demo_stub in the report."""

    def with_structured_output(self, schema):
        if schema is not AssessmentDraft:
            raise TypeError("offline demo only supports AssessmentDraft")
        return self

    def invoke(self, messages):
        evidence_ids = re.findall(r"ev-[a-f0-9]{16}", messages[-1].content)
        return AssessmentDraft(
            hypotheses=[{
                "statement": "Possible backhaul performance degradation is consistent with the synthetic signals.",
                "confidence": 0.72,
                "supporting_evidence_ids": evidence_ids,
            }],
            confidence=0.72,
            uncertainty="This is a hypothesis from synthetic fixtures; verify with current operational data.",
            recommended_action="Review current backhaul interface counters.",
            rationale="The simulated latency alarm and telemetry provide a reason for additional backhaul checks.",
            action_risk="LOW",
            recommendation_type="investigative",
            human_approval_required=False,
            recommended_next_steps=["Review current backhaul interface counters and recent maintenance records."],
        )


def main():
    parser = argparse.ArgumentParser(description="Agentic AI NOC prototype")
    parser.add_argument(
        "--demo", action="store_true",
        help="run the reproducible synthetic incident using a labelled offline model stub",
    )
    parser.add_argument(
        "--demo-ollama", action="store_true",
        help="run the synthetic incident using the configured Ollama model",
    )
    args = parser.parse_args()

    if args.demo and args.demo_ollama:
        parser.error("choose either --demo or --demo-ollama")
    if args.demo or args.demo_ollama:
        kwargs = {"llm": _DemoStructuredModel(), "success_status": "demo_stub"} if args.demo else {}
        result = build_graph(**kwargs).invoke({"incident": DEMO_INCIDENT})
        print(result["assessment"].model_dump_json(indent=2))
        return

    build_graph()
    print("Agentic AI NOC system initialized.")
    print("Ready to receive incidents.")


if __name__ == "__main__":
    main()
