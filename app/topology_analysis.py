"""Deterministic traversal of explicit synthetic topology dependencies."""

from collections import deque
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from app.models.topology import (
    ServiceImpactAssessment,
    TopologyAnalysisResult,
    TopologyDependencyEdge,
    TopologyEdgeReference,
    TopologyPath,
    TopologyRelationship,
    TopologyServiceMapping,
    TopologySnapshot,
)


def _plain_data(value: Any) -> Any:
    """Convert model instances to plain data before recursively validating them."""
    if isinstance(value, BaseModel):
        return _plain_data(value.model_dump(mode="python", warnings=False))
    if isinstance(value, Mapping):
        return {key: _plain_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_data(item) for item in value]
    return value


def _edge_reference(edge: TopologyDependencyEdge) -> TopologyEdgeReference:
    return TopologyEdgeReference(
        edge_id=edge.edge_id,
        provider_element_id=edge.provider_element_id,
        dependent_element_id=edge.dependent_element_id,
        source_record_id=edge.source_record_id,
        evidence_id=edge.evidence_id,
    )


def _find_path(
    topology: TopologySnapshot,
    source_id: str,
    target_id: str,
) -> TopologyPath | None:
    element_ids = {element.element_id for element in topology.elements}
    if source_id not in element_ids or target_id not in element_ids:
        return None
    if source_id == target_id:
        return TopologyPath(element_ids=[source_id], edges=[])

    adjacency: dict[str, list[TopologyDependencyEdge]] = {element_id: [] for element_id in element_ids}
    for edge in topology.dependency_edges:
        adjacency[edge.provider_element_id].append(edge)
    for edges in adjacency.values():
        edges.sort(key=lambda edge: edge.edge_id)

    queue = deque([(source_id, [source_id], [])])
    visited = {source_id}
    while queue:
        current, path_elements, path_edges = queue.popleft()
        for edge in adjacency[current]:
            dependent = edge.dependent_element_id
            if dependent in visited:
                continue
            next_elements = [*path_elements, dependent]
            next_edges = [*path_edges, _edge_reference(edge)]
            if dependent == target_id:
                return TopologyPath(element_ids=next_elements, edges=next_edges)
            visited.add(dependent)
            queue.append((dependent, next_elements, next_edges))
    return None


def _service_assessments(
    topology: TopologySnapshot,
    affected_element_ids: list[str],
    unknown_element_ids: list[str],
) -> list[ServiceImpactAssessment]:
    mappings_by_service: dict[str, list[TopologyServiceMapping]] = {}
    for mapping in topology.service_mappings:
        mappings_by_service.setdefault(mapping.service_id, []).append(mapping)

    results = []
    for service_id in sorted(mappings_by_service):
        mappings = mappings_by_service[service_id]
        paths: list[TopologyPath] = []
        for affected_id in affected_element_ids:
            for mapping in mappings:
                path = _find_path(topology, affected_id, mapping.served_element_id)
                if path is not None:
                    paths.append(path)
        if paths:
            results.append(ServiceImpactAssessment(
                service_id=service_id,
                mappings=mappings,
                status="potentially_affected",
                observed_impact="unknown",
                context_incomplete=(
                    topology.coverage_status == "partial"
                    or bool(unknown_element_ids)
                    or not affected_element_ids
                ),
                dependency_paths=paths,
            ))
            continue

        if not affected_element_ids:
            reason = "no_affected_elements"
        elif unknown_element_ids:
            reason = "affected_element_not_in_snapshot"
        elif topology.coverage_status == "partial":
            reason = "topology_incomplete"
        else:
            results.append(ServiceImpactAssessment(
                service_id=service_id,
                mappings=mappings,
                status="not_on_declared_dependency_path",
                observed_impact="unknown",
                context_incomplete=False,
                dependency_paths=[],
            ))
            continue
        results.append(ServiceImpactAssessment(
            service_id=service_id,
            mappings=mappings,
            status="unknown",
            observed_impact="unknown",
            context_incomplete=True,
            dependency_paths=[],
            unknown_reason=reason,
        ))
    return results


def analyze_topology(
    topology: TopologySnapshot,
    affected_element_ids: list[str],
) -> TopologyAnalysisResult:
    """Explain declared element relationships and possible service dependencies.

    Edges point from provider to dependent elements. A service is reported as
    potentially dependent only when a directed declared path reaches one of its
    explicitly mapped elements. This does not establish observed service impact.
    """
    topology = TopologySnapshot.model_validate(_plain_data(topology))
    if not isinstance(affected_element_ids, list) or any(
        not isinstance(element_id, str) or not element_id.strip()
        for element_id in affected_element_ids
    ):
        raise ValueError("affected_element_ids must be a list of non-empty strings")
    unique_ids = sorted({element_id.strip() for element_id in affected_element_ids})
    known = {element.element_id for element in topology.elements}
    unknown = sorted(set(unique_ids) - known)

    relationships: list[TopologyRelationship] = []
    for index, first_id in enumerate(unique_ids):
        for second_id in unique_ids[index + 1:]:
            path = _find_path(topology, first_id, second_id)
            if path is None:
                path = _find_path(topology, second_id, first_id)
            if path is not None:
                relationships.append(TopologyRelationship(
                    element_a_id=first_id,
                    element_b_id=second_id,
                    status="connected",
                    path=path,
                ))
            elif first_id not in known or second_id not in known:
                relationships.append(TopologyRelationship(
                    element_a_id=first_id,
                    element_b_id=second_id,
                    status="unknown",
                    unknown_reason="element_not_in_snapshot",
                ))
            elif topology.coverage_status == "partial":
                relationships.append(TopologyRelationship(
                    element_a_id=first_id,
                    element_b_id=second_id,
                    status="unknown",
                    unknown_reason="topology_incomplete",
                ))
            else:
                relationships.append(TopologyRelationship(
                    element_a_id=first_id,
                    element_b_id=second_id,
                    status="disconnected",
                ))

    service_impacts = _service_assessments(topology, unique_ids, unknown)
    return TopologyAnalysisResult(
        topology=topology,
        affected_element_ids=unique_ids,
        unknown_element_ids=unknown,
        relationships=relationships,
        service_impacts=service_impacts,
        service_impact_status=(
            "based_on_declared_mappings"
            if topology.service_mappings else "unknown_no_service_mappings"
        ),
    )
