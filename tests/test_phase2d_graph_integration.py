import re

import pytest

from app import graph as graph_module
from app.graph import build_graph
from app.models.assessment import AssessmentDraft

INCIDENT = {
    "incident_id": "INC-PHASE2D-001", "site": "DEN-042", "technology": "5G",
    "severity": "SEV-2", "description": "Elevated latency and packet loss.",
}


class StubLLM:
    def __init__(self, *, hypotheses=True, conflict=False):
        self.hypotheses = hypotheses
        self.conflict = conflict

    def with_structured_output(self, schema):
        assert schema is AssessmentDraft
        return self

    def invoke(self, messages):
        ids = list(dict.fromkeys(re.findall(r"ev-[a-f0-9]{16}", messages[-1].content)))
        hypotheses = ([{
            "statement": "Possible backhaul performance degradation.", "confidence": 0.75,
            "supporting_evidence_ids": ids[:1],
        }] if self.hypotheses else [])
        conflicts = ([{"description": "Synthetic sources may require reconciliation.",
                       "evidence_ids": ids[:2]}] if self.conflict else [])
        return AssessmentDraft(
            hypotheses=hypotheses, conflicts=conflicts, confidence=0.75 if hypotheses else 0.2,
            uncertainty="Synthetic evidence does not establish a confirmed root cause.",
            recommended_action="Review current counters.", rationale="Use synthetic evidence cautiously.",
            action_risk="LOW", recommendation_type="investigative", human_approval_required=False,
        )


def run(**kwargs):
    return build_graph(llm=StubLLM(**kwargs)).invoke({"incident": INCIDENT})


def test_full_flow_correlates_alarms_and_follows_declared_topology_path():
    state = run()
    result = state["assessment"]
    assert state["phase2_status"] == "success"
    assert len(state["alarm_correlation"].groups) == 1
    group = state["alarm_correlation"].groups[0]
    assert {m.event_reference.source_event_id for m in group.members} == {
        "SRC-EVT-DUP-1", "SRC-EVT-CORR-2",
    }
    impact = state["topology_analysis"].service_impacts[0]
    assert impact.status == "potentially_affected"
    assert impact.observed_impact == "unknown"
    assert any(path.element_ids == ["RTR-DEN-18", "IF-DEN-18-3", "CELL-DEN-042-A"]
               for path in impact.dependency_paths)
    assert all(f.kind == "observed_fact" for f in result.findings)
    assert any(f.kind == "inference" for f in state["deterministic_findings"])
    assert result.hypotheses


def test_duplicate_alarms_keep_every_source_reference():
    state = run()
    dedup = state["alarm_deduplication"]
    group = next(g for g in dedup.duplicate_groups if "SRC-EVT-DUP-1" in (g.fingerprint or ""))
    assert group.input_count == 2 and group.suppressed_count == 1
    assert {r.source_record_id for r in group.original_event_references} == {
        "PHASE2D-ROW-DUP-1A", "PHASE2D-ROW-DUP-1B",
    }
    corr_member = next(
        member for corr in state["alarm_correlation"].groups for member in corr.members
        if member.event_reference.source_event_id == "SRC-EVT-DUP-1"
    )
    assert corr_member.original_event_references == group.original_event_references


def test_unrelated_alarm_stays_uncorrelated():
    state = run()
    refs = state["alarm_correlation"].uncorrelated_event_references
    assert any(ref.source_event_id == "SRC-EVT-RELATED-3" for ref in refs)


def test_partial_topology_keeps_observed_impact_unknown(monkeypatch):
    original = graph_module.analyze_topology

    def partial(topology, affected):
        topology = topology.model_copy(update={"coverage_status": "partial", "known_gaps": ["unmodeled access segment"]})
        return original(topology, affected)

    monkeypatch.setattr(graph_module, "analyze_topology", partial)
    state = run()
    impact = state["topology_analysis"].service_impacts[0]
    assert impact.context_incomplete is True
    assert impact.observed_impact == "unknown"


def test_insufficient_and_conflicting_model_interpretation_stays_cautious():
    state = run(hypotheses=False, conflict=True)
    assert state["assessment"].status == "inconclusive"
    assert state["assessment"].hypotheses == []
    assert state["assessment"].conflicts[0].verification_status == "unverified_model_proposal"
    assert state["assessment"].confidence == 0.0


@pytest.mark.parametrize("component", [
    "normalize_alarms", "deduplicate_alarms", "correlate_alarms", "analyze_topology",
])
def test_deterministic_component_failure_is_explicit_and_inconclusive(monkeypatch, component):
    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic component failure")

    monkeypatch.setattr(graph_module, component, fail)
    state = run()
    assert state["phase2_status"] == "failure"
    assert state["phase2_error"] == "RuntimeError"
    assert state["assessment"].status == "inconclusive"
    assert state["assessment"].generation_status == "not_attempted"
    failure = next(e for e in state["assessment"].evidence if e.source == "phase2_deterministic_analysis")
    assert failure.collection_status == "failure"


def test_existing_assessment_facts_remain_separate_from_deterministic_inferences():
    state = run()
    assessment = state["assessment"]
    assert assessment.status == "assessed"
    assert assessment.generation_status == "llm_success"
    assert all(f.kind == "observed_fact" for f in assessment.findings)
    assert state["deterministic_findings"]
    assert all(f.kind == "inference" for f in state["deterministic_findings"])
