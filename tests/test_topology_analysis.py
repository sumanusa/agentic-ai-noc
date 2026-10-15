import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.topology import TopologyAnalysisResult, TopologyPath, TopologySnapshot
from app.topology_analysis import analyze_topology


FIXTURE = Path(__file__).parents[1] / "data" / "topology" / "phase2c_den042.json"


def fixture_data():
    return json.loads(FIXTURE.read_text())


def snapshot(data=None):
    return TopologySnapshot.model_validate(data if data is not None else fixture_data())


def test_fixture_uses_explicit_directed_edges_and_service_mapping_provenance():
    topology = snapshot()

    assert topology.coverage_status == "complete"
    assert len(topology.elements) == 6
    assert len(topology.dependency_edges) == 4
    assert topology.dependency_edges[0].provider_element_id == "BH-7731"
    assert topology.dependency_edges[0].dependent_element_id == "RTR-DEN-18"
    assert topology.service_mappings[0].served_element_id == "CELL-DEN-042-A"
    assert topology.dependency_edges[0].source_record_id == "TOPO-REL-BH7731-RTR18"
    assert topology.dependency_edges[0].evidence_id == "ev-topology-phase2c-den042"


def test_connected_alarm_elements_return_only_declared_directional_path_and_edge_provenance():
    result = analyze_topology(snapshot(), ["IF-DEN-18-3", "RTR-DEN-18"])

    relationship = result.relationships[0]
    assert relationship.status == "connected"
    assert relationship.path.element_ids == ["RTR-DEN-18", "IF-DEN-18-3"]
    assert [edge.edge_id for edge in relationship.path.edges] == ["TOPO-EDGE-002"]
    assert relationship.path.edges[0].source_record_id == "TOPO-REL-RTR18-IF183"
    assert relationship.path.edges[0].evidence_id == "ev-topology-phase2c-den042"


def test_declared_dependency_path_yields_potential_not_observed_service_impact():
    result = analyze_topology(snapshot(), ["RTR-DEN-18"])
    impact = result.service_impacts[0]

    assert impact.service_id == "SVC-DEN-042-5G-ACCESS"
    assert impact.status == "potentially_affected"
    assert impact.observed_impact == "unknown"
    assert impact.dependency_paths[0].element_ids == [
        "RTR-DEN-18", "IF-DEN-18-3", "CELL-DEN-042-A",
    ]
    assert [edge.edge_id for edge in impact.dependency_paths[0].edges] == [
        "TOPO-EDGE-002", "TOPO-EDGE-003",
    ]
    assert impact.mappings[0].source_record_id == "TOPO-MAP-5G-ACCESS-CELLA"


def test_disconnected_elements_in_complete_topology_are_not_claimed_as_related():
    result = analyze_topology(snapshot(), ["RTR-DEN-18", "RTR-DEN-19"])

    assert result.relationships[0].status == "disconnected"
    assert result.relationships[0].path is None
    # The other supplied element (RTR-DEN-18) does have a declared path to this service.
    assert result.service_impacts[0].status == "potentially_affected"
    disconnected_service = analyze_topology(snapshot(), ["RTR-DEN-19"]).service_impacts[0]
    assert disconnected_service.status == "not_on_declared_dependency_path"
    assert result.service_impacts[0].observed_impact == "unknown"


def test_missing_edge_in_partial_topology_produces_unknown_not_disconnected_or_unaffected():
    data = fixture_data()
    data["coverage_status"] = "partial"
    data["known_gaps"] = ["Declared router-to-interface dependency is absent from this fixture view."]
    data["dependency_edges"] = [
        edge for edge in data["dependency_edges"] if edge["edge_id"] != "TOPO-EDGE-002"
    ]
    result = analyze_topology(snapshot(data), ["RTR-DEN-18", "IF-DEN-18-3"])

    assert result.relationships[0].status == "unknown"
    assert result.relationships[0].unknown_reason == "topology_incomplete"
    missing_path_service = analyze_topology(snapshot(data), ["RTR-DEN-18"]).service_impacts[0]
    assert missing_path_service.status == "unknown"
    assert missing_path_service.unknown_reason == "topology_incomplete"
    assert missing_path_service.observed_impact == "unknown"


def test_element_missing_from_snapshot_stays_unknown_even_when_declared_graph_is_complete():
    result = analyze_topology(snapshot(), ["RTR-DEN-18", "UNKNOWN-ELEMENT"])

    assert result.unknown_element_ids == ["UNKNOWN-ELEMENT"]
    assert result.relationships[0].status == "unknown"
    assert result.relationships[0].unknown_reason == "element_not_in_snapshot"
    missing_service = analyze_topology(snapshot(), ["UNKNOWN-ELEMENT"]).service_impacts[0]
    assert missing_service.status == "unknown"
    assert missing_service.unknown_reason == "affected_element_not_in_snapshot"


@pytest.mark.parametrize("mutate", [
    lambda data: data["dependency_edges"].append({
        **data["dependency_edges"][0],
        "edge_id": "BAD-MISSING-ENDPOINT",
        "dependent_element_id": "NOT-DECLARED",
    }),
    lambda data: data["dependency_edges"].append({
        **data["dependency_edges"][0],
        "edge_id": "BAD-CYCLE",
        "provider_element_id": "RTR-DEN-18",
        "dependent_element_id": "BH-7731",
    }),
    lambda data: data["service_mappings"][0].update(served_element_id="NOT-DECLARED"),
])
def test_invalid_topology_paths_and_service_endpoints_are_rejected(mutate):
    data = fixture_data()
    mutate(data)

    with pytest.raises(ValidationError):
        snapshot(data)


def test_invalid_path_edge_order_is_rejected():
    with pytest.raises(ValidationError, match="directed element sequence"):
        TopologyPath(
            element_ids=["RTR-DEN-18", "IF-DEN-18-3"],
            edges=[{
                "edge_id": "TOPO-EDGE-002",
                "provider_element_id": "IF-DEN-18-3",
                "dependent_element_id": "RTR-DEN-18",
                "source_record_id": "TOPO-REL-RTR18-IF183",
                "evidence_id": "ev-topology-phase2c-den042",
            }],
        )


def test_analysis_rejects_path_edge_reference_with_fabricated_provenance():
    result = analyze_topology(snapshot(), ["RTR-DEN-18", "IF-DEN-18-3"])
    malformed_data = result.model_dump(mode="python")
    malformed_data["relationships"][0]["path"]["edges"][0]["source_record_id"] = "INVENTED-RECORD"

    with pytest.raises(ValidationError, match="edge references must match"):
        TopologyAnalysisResult.model_validate(malformed_data)


@pytest.mark.parametrize("claim", ["disconnected", "unknown"])
def test_result_revalidation_rejects_no_path_claim_when_declared_edge_connects_elements(claim):
    result = analyze_topology(snapshot(), ["RTR-DEN-18", "IF-DEN-18-3"])
    malformed_data = result.model_dump(mode="python")
    malformed_data["relationships"][0].update(
        status=claim,
        path=None,
        unknown_reason="topology_incomplete" if claim == "unknown" else None,
    )

    with pytest.raises(ValidationError, match="relationship status must match"):
        TopologyAnalysisResult.model_validate(malformed_data)

    malformed_instance = TopologyAnalysisResult.model_construct(**malformed_data)
    with pytest.raises(ValidationError, match="relationship status must match"):
        TopologyAnalysisResult.model_validate(malformed_instance)


@pytest.mark.parametrize(
    ("claim", "reason"),
    [
        ("not_on_declared_dependency_path", None),
        ("unknown", "topology_incomplete"),
    ],
)
def test_result_revalidation_rejects_no_service_path_claim_when_declared_path_exists(claim, reason):
    result = analyze_topology(snapshot(), ["RTR-DEN-18"])
    malformed_data = result.model_dump(mode="python")
    malformed_data["service_impacts"][0].update(
        status=claim,
        dependency_paths=[],
        unknown_reason=reason,
    )

    with pytest.raises(ValidationError, match="service impact status must match"):
        TopologyAnalysisResult.model_validate(malformed_data)


def test_partial_coverage_without_gap_declaration_and_nonpositive_inputs_fail():
    data = fixture_data()
    data["coverage_status"] = "partial"
    with pytest.raises(ValidationError, match="known gap"):
        snapshot(data)
    with pytest.raises(ValueError, match="non-empty strings"):
        analyze_topology(snapshot(), [""])
    with pytest.raises(ValueError, match="non-empty strings"):
        analyze_topology(snapshot(), "RTR-DEN-18")


def test_empty_input_and_no_service_mappings_keep_impact_explicitly_unknown():
    empty = analyze_topology(snapshot(), [])
    assert empty.relationships == []
    assert empty.service_impacts[0].status == "unknown"
    assert empty.service_impacts[0].unknown_reason == "no_affected_elements"
    assert empty.service_impact_status == "based_on_declared_mappings"

    data = fixture_data()
    data["service_mappings"] = []
    no_mappings = analyze_topology(snapshot(data), ["RTR-DEN-18"])
    assert no_mappings.service_impacts == []
    assert no_mappings.service_impact_status == "unknown_no_service_mappings"


def test_genuinely_empty_topology_graph_has_no_fabricated_paths():
    empty_topology = TopologySnapshot(
        topology_id="empty-topology",
        source="synthetic-test",
        coverage_status="complete",
        elements=[],
        dependency_edges=[],
        service_mappings=[],
    )
    no_events = analyze_topology(empty_topology, [])
    unknown_event = analyze_topology(empty_topology, ["MISSING-ELEMENT"])

    assert no_events.relationships == []
    assert no_events.service_impacts == []
    assert no_events.service_impact_status == "unknown_no_service_mappings"
    assert unknown_event.relationships == []
    assert unknown_event.unknown_element_ids == ["MISSING-ELEMENT"]
    assert unknown_event.service_impact_status == "unknown_no_service_mappings"


def test_elements_with_no_incident_edges_are_disconnected_in_complete_graph():
    isolated_topology = TopologySnapshot(
        topology_id="two-isolated-elements",
        source="synthetic-test",
        coverage_status="complete",
        elements=[
            {"element_id": "ELEMENT-A", "element_type": "router", "site_id": "SITE-A"},
            {"element_id": "ELEMENT-B", "element_type": "cell", "site_id": "SITE-A"},
        ],
        dependency_edges=[],
        service_mappings=[{
            "mapping_id": "MAP-B",
            "service_id": "SERVICE-B",
            "served_element_id": "ELEMENT-B",
            "source_record_id": "MAP-RECORD-B",
        }],
    )
    result = analyze_topology(isolated_topology, ["ELEMENT-A", "ELEMENT-B"])

    assert result.relationships[0].status == "disconnected"
    assert result.relationships[0].path is None
    impact_from_isolated_a = analyze_topology(isolated_topology, ["ELEMENT-A"]).service_impacts[0]
    assert impact_from_isolated_a.status == "not_on_declared_dependency_path"
    assert impact_from_isolated_a.dependency_paths == []


def test_equal_length_paths_choose_lexicographically_first_edge_id_sequence():
    data = fixture_data()
    data["elements"].append({
        "element_id": "RTR-ALT",
        "element_type": "router",
        "site_id": "DEN-042",
        "source_record_id": "TOPO-ELEMENT-RTR-ALT",
        "evidence_id": "ev-topology-phase2c-den042",
    })
    data["dependency_edges"].extend([
        {
            "edge_id": "TOPO-EDGE-000",
            "provider_element_id": "BH-7731",
            "dependent_element_id": "RTR-ALT",
            "relation": "provides_dependency_to",
            "source_record_id": "TOPO-REL-BH7731-ALT",
            "evidence_id": "ev-topology-phase2c-den042",
        },
        {
            "edge_id": "TOPO-EDGE-999",
            "provider_element_id": "RTR-ALT",
            "dependent_element_id": "IF-DEN-18-3",
            "relation": "provides_dependency_to",
            "source_record_id": "TOPO-REL-ALT-IF183",
            "evidence_id": "ev-topology-phase2c-den042",
        },
    ])
    normal = analyze_topology(snapshot(data), ["BH-7731", "IF-DEN-18-3"])
    reordered_data = {**data, "dependency_edges": list(reversed(data["dependency_edges"]))}
    reordered = analyze_topology(snapshot(reordered_data), ["BH-7731", "IF-DEN-18-3"])

    assert normal.relationships[0].path.element_ids == ["BH-7731", "RTR-ALT", "IF-DEN-18-3"]
    assert [edge.edge_id for edge in normal.relationships[0].path.edges] == [
        "TOPO-EDGE-000", "TOPO-EDGE-999",
    ]
    assert normal.relationships == reordered.relationships


def test_deterministic_paths_across_repeated_runs_and_input_order():
    topology = snapshot()
    first = analyze_topology(topology, ["IF-DEN-18-3", "RTR-DEN-18"])
    second = analyze_topology(topology, ["IF-DEN-18-3", "RTR-DEN-18"])
    reordered = analyze_topology(topology, ["RTR-DEN-18", "IF-DEN-18-3"])

    assert first.model_dump_json() == second.model_dump_json()
    assert first.relationships == reordered.relationships


def test_preconstructed_malformed_topology_is_revalidated_at_analysis_boundary():
    valid_data = fixture_data()
    valid = snapshot(valid_data)
    malformed = TopologySnapshot.model_construct(**{
        **valid.model_dump(),
        "dependency_edges": [
            {**valid.model_dump()["dependency_edges"][0], "dependent_element_id": "NOT-DECLARED"},
            *valid.model_dump()["dependency_edges"][1:],
        ],
    })

    with pytest.raises(ValidationError, match="endpoints"):
        analyze_topology(malformed, ["RTR-DEN-18"])
