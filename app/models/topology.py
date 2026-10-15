"""Validated synthetic topology, dependency, and service-mapping contracts."""

from collections import deque
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TopologyElement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    element_id: str = Field(min_length=1)
    element_type: Literal["backhaul", "router", "interface", "cell"]
    site_id: str = Field(min_length=1)
    source_record_id: str | None = None
    evidence_id: str | None = None


class TopologyDependencyEdge(BaseModel):
    """Directed support relation: provider -> dependent element."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    edge_id: str = Field(min_length=1)
    provider_element_id: str = Field(min_length=1)
    dependent_element_id: str = Field(min_length=1)
    relation: Literal["provides_dependency_to"] = "provides_dependency_to"
    source_record_id: str = Field(min_length=1)
    evidence_id: str | None = None

    @model_validator(mode="after")
    def no_self_dependency(self):
        if self.provider_element_id == self.dependent_element_id:
            raise ValueError("dependency edge cannot point from an element to itself")
        return self


class TopologyServiceMapping(BaseModel):
    """Explicit service-to-supporting-element mapping, not an observed outage."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    mapping_id: str = Field(min_length=1)
    service_id: str = Field(min_length=1)
    served_element_id: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    evidence_id: str | None = None


class TopologySnapshot(BaseModel):
    """One explicit fixture snapshot with declared coverage limitations."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    topology_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    coverage_status: Literal["complete", "partial"]
    known_gaps: list[str] = Field(default_factory=list)
    elements: list[TopologyElement] = Field(default_factory=list)
    dependency_edges: list[TopologyDependencyEdge] = Field(default_factory=list)
    service_mappings: list[TopologyServiceMapping] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_and_coverage_are_valid(self):
        if len({element.element_id for element in self.elements}) != len(self.elements):
            raise ValueError("topology element IDs must be unique")
        if len({edge.edge_id for edge in self.dependency_edges}) != len(self.dependency_edges):
            raise ValueError("topology edge IDs must be unique")
        pairs = [(edge.provider_element_id, edge.dependent_element_id) for edge in self.dependency_edges]
        if len(set(pairs)) != len(pairs):
            raise ValueError("duplicate directed dependency edges are not allowed")
        if len({mapping.mapping_id for mapping in self.service_mappings}) != len(self.service_mappings):
            raise ValueError("service mapping IDs must be unique")
        if len(set(self.known_gaps)) != len(self.known_gaps):
            raise ValueError("known topology gaps must be unique")
        if any(not gap.strip() for gap in self.known_gaps):
            raise ValueError("known topology gaps must be non-empty")
        if self.coverage_status == "partial" and not self.known_gaps:
            raise ValueError("partial topology must declare at least one known gap")
        if self.coverage_status == "complete" and self.known_gaps:
            raise ValueError("complete topology cannot declare unresolved coverage gaps")

        element_ids = {element.element_id for element in self.elements}
        for edge in self.dependency_edges:
            if edge.provider_element_id not in element_ids or edge.dependent_element_id not in element_ids:
                raise ValueError("dependency edge endpoints must reference declared elements")
        for mapping in self.service_mappings:
            if mapping.served_element_id not in element_ids:
                raise ValueError("service mappings must reference declared elements")

        # Dependency relationships in this increment describe a hierarchy. Reject
        # cycles so every reported path has an unambiguous directed interpretation.
        adjacency: dict[str, list[str]] = {element_id: [] for element_id in element_ids}
        for edge in self.dependency_edges:
            adjacency[edge.provider_element_id].append(edge.dependent_element_id)
        states: dict[str, int] = {}

        def visit(element_id: str) -> None:
            state = states.get(element_id, 0)
            if state == 1:
                raise ValueError("topology dependency graph must be acyclic")
            if state == 2:
                return
            states[element_id] = 1
            for dependent_id in adjacency[element_id]:
                visit(dependent_id)
            states[element_id] = 2

        for element_id in sorted(element_ids):
            visit(element_id)
        return self


class TopologyEdgeReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    edge_id: str = Field(min_length=1)
    provider_element_id: str = Field(min_length=1)
    dependent_element_id: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    evidence_id: str | None = None


class TopologyPath(BaseModel):
    """A directed declared path with references to every traversed source edge."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    element_ids: list[str] = Field(min_length=1)
    edges: list[TopologyEdgeReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def edge_sequence_matches_element_sequence(self):
        if len(self.edges) != len(self.element_ids) - 1:
            raise ValueError("path must contain exactly one fewer edge than elements")
        if any(not element_id for element_id in self.element_ids):
            raise ValueError("path element IDs must be non-empty")
        for index, edge in enumerate(self.edges):
            if (
                edge.provider_element_id != self.element_ids[index]
                or edge.dependent_element_id != self.element_ids[index + 1]
            ):
                raise ValueError("path edges must follow the declared directed element sequence")
        if len({edge.edge_id for edge in self.edges}) != len(self.edges):
            raise ValueError("path cannot repeat an edge")
        if len(set(self.element_ids)) != len(self.element_ids):
            raise ValueError("path cannot repeat an element")
        return self


class TopologyRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    element_a_id: str = Field(min_length=1)
    element_b_id: str = Field(min_length=1)
    status: Literal["connected", "disconnected", "unknown"]
    path: TopologyPath | None = None
    unknown_reason: Literal["element_not_in_snapshot", "topology_incomplete"] | None = None

    @model_validator(mode="after")
    def status_matches_path_and_reason(self):
        if self.element_a_id >= self.element_b_id:
            raise ValueError("relationship element IDs must use canonical sorted order")
        if self.status == "connected":
            if self.path is None or self.unknown_reason is not None:
                raise ValueError("connected relationship requires a path and no unknown reason")
            if {self.path.element_ids[0], self.path.element_ids[-1]} != {
                self.element_a_id, self.element_b_id,
            }:
                raise ValueError("relationship path must connect its declared elements")
        elif self.path is not None:
            raise ValueError("disconnected or unknown relationship cannot contain a path")
        elif self.status == "disconnected" and self.unknown_reason is not None:
            raise ValueError("disconnected relationship cannot have an unknown reason")
        elif self.status == "unknown" and self.unknown_reason is None:
            raise ValueError("unknown relationship must state why it is unresolved")
        return self


class ServiceImpactAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    service_id: str = Field(min_length=1)
    mappings: list[TopologyServiceMapping] = Field(min_length=1)
    status: Literal["potentially_affected", "not_on_declared_dependency_path", "unknown"]
    observed_impact: Literal["unknown"] = "unknown"
    context_incomplete: bool
    dependency_paths: list[TopologyPath] = Field(default_factory=list)
    unknown_reason: Literal[
        "no_affected_elements", "affected_element_not_in_snapshot", "topology_incomplete",
    ] | None = None

    @model_validator(mode="after")
    def impact_status_matches_paths_and_mappings(self):
        if not self.mappings or any(mapping.service_id != self.service_id for mapping in self.mappings):
            raise ValueError("service impact mappings must belong to the declared service")
        if self.status == "potentially_affected":
            if not self.dependency_paths or self.unknown_reason is not None:
                raise ValueError("potential impact requires a declared path and no unknown reason")
        elif self.dependency_paths:
            raise ValueError("unknown or not-connected service result cannot contain paths")
        elif self.status == "not_on_declared_dependency_path" and self.unknown_reason is not None:
            raise ValueError("not-connected service result cannot have an unknown reason")
        elif self.status == "unknown" and self.unknown_reason is None:
            raise ValueError("unknown service impact must state why it is unresolved")
        return self


class TopologyAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    topology: TopologySnapshot
    affected_element_ids: list[str]
    unknown_element_ids: list[str]
    relationships: list[TopologyRelationship]
    service_impacts: list[ServiceImpactAssessment]
    service_impact_status: Literal["based_on_declared_mappings", "unknown_no_service_mappings"]

    @model_validator(mode="after")
    def analysis_is_consistent_with_snapshot(self):
        if len(self.affected_element_ids) != len(set(self.affected_element_ids)):
            raise ValueError("affected element IDs must be unique")
        if self.affected_element_ids != sorted(self.affected_element_ids):
            raise ValueError("affected element IDs must use canonical sorted order")
        if any(not element_id for element_id in self.affected_element_ids):
            raise ValueError("affected element IDs must be non-empty")
        known = {element.element_id for element in self.topology.elements}
        expected_unknown = sorted(set(self.affected_element_ids) - known)
        if self.unknown_element_ids != expected_unknown:
            raise ValueError("unknown element IDs must match elements absent from the snapshot")

        expected_pairs = {
            (a, b) for index, a in enumerate(self.affected_element_ids)
            for b in self.affected_element_ids[index + 1:]
        }
        actual_pairs = [(item.element_a_id, item.element_b_id) for item in self.relationships]
        if len(actual_pairs) != len(set(actual_pairs)) or set(actual_pairs) != expected_pairs:
            raise ValueError("relationships must cover each affected-element pair exactly once")
        edge_lookup = {edge.edge_id: edge for edge in self.topology.dependency_edges}
        for relationship in self.relationships:
            if relationship.path is not None:
                self._validate_path(relationship.path, edge_lookup, known)
            a_id, b_id = relationship.element_a_id, relationship.element_b_id
            path_exists = (
                self._has_declared_path(self.topology, a_id, b_id)
                or self._has_declared_path(self.topology, b_id, a_id)
            )
            if path_exists:
                expected_status, expected_reason = "connected", None
            elif a_id not in known or b_id not in known:
                expected_status, expected_reason = "unknown", "element_not_in_snapshot"
            elif self.topology.coverage_status == "partial":
                expected_status, expected_reason = "unknown", "topology_incomplete"
            else:
                expected_status, expected_reason = "disconnected", None
            if relationship.status != expected_status or relationship.unknown_reason != expected_reason:
                raise ValueError("relationship status must match declared topology reachability and coverage")

        mapping_groups: dict[str, list[TopologyServiceMapping]] = {}
        for mapping in self.topology.service_mappings:
            mapping_groups.setdefault(mapping.service_id, []).append(mapping)
        if self.service_impact_status == "unknown_no_service_mappings":
            if mapping_groups or self.service_impacts:
                raise ValueError("empty service mapping status must have no mappings or assessments")
        else:
            if not mapping_groups or {impact.service_id for impact in self.service_impacts} != set(mapping_groups):
                raise ValueError("service impact assessments must cover each declared service")
        if len({impact.service_id for impact in self.service_impacts}) != len(self.service_impacts):
            raise ValueError("service impact assessments must be unique by service")

        for impact in self.service_impacts:
            expected_incomplete = (
                self.topology.coverage_status == "partial"
                or bool(self.unknown_element_ids)
                or not self.affected_element_ids
            )
            if impact.context_incomplete != expected_incomplete:
                raise ValueError("service context flag must match topology and affected-element coverage")
            expected_mappings = mapping_groups[impact.service_id]
            if impact.mappings != expected_mappings:
                raise ValueError("service impact must preserve exact mapping provenance")
            for path in impact.dependency_paths:
                self._validate_path(path, edge_lookup, known)
                if path.element_ids[0] not in self.affected_element_ids:
                    raise ValueError("service paths must start at an affected element")
                if path.element_ids[-1] not in {mapping.served_element_id for mapping in expected_mappings}:
                    raise ValueError("service paths must terminate at a declared service mapping")
            service_path_exists = any(
                self._has_declared_path(self.topology, affected_id, mapping.served_element_id)
                for affected_id in self.affected_element_ids
                for mapping in expected_mappings
            )
            if service_path_exists:
                expected_status, expected_reason = "potentially_affected", None
            elif not self.affected_element_ids:
                expected_status, expected_reason = "unknown", "no_affected_elements"
            elif self.unknown_element_ids:
                expected_status, expected_reason = "unknown", "affected_element_not_in_snapshot"
            elif self.topology.coverage_status == "partial":
                expected_status, expected_reason = "unknown", "topology_incomplete"
            else:
                expected_status, expected_reason = "not_on_declared_dependency_path", None
            if impact.status != expected_status or impact.unknown_reason != expected_reason:
                raise ValueError("service impact status must match declared reachability and topology coverage")
        if not self.topology.service_mappings:
            if self.service_impact_status != "unknown_no_service_mappings":
                raise ValueError("absence of service mappings must remain explicitly unknown")
        elif self.service_impact_status != "based_on_declared_mappings":
            raise ValueError("declared service mappings must be assessed explicitly")
        return self

    @staticmethod
    def _validate_path(
        path: TopologyPath,
        edge_lookup: dict[str, TopologyDependencyEdge],
        known_element_ids: set[str],
    ) -> None:
        if not set(path.element_ids) <= known_element_ids:
            raise ValueError("path elements must exist in the topology snapshot")
        for reference in path.edges:
            edge = edge_lookup.get(reference.edge_id)
            if edge is None or reference != TopologyEdgeReference(
                edge_id=edge.edge_id,
                provider_element_id=edge.provider_element_id,
                dependent_element_id=edge.dependent_element_id,
                source_record_id=edge.source_record_id,
                evidence_id=edge.evidence_id,
            ):
                raise ValueError("path edge references must match declared edge provenance")

    @staticmethod
    def _has_declared_path(topology: TopologySnapshot, source_id: str, target_id: str) -> bool:
        """Check directed reachability independently of result-supplied paths."""
        element_ids = {element.element_id for element in topology.elements}
        if source_id not in element_ids or target_id not in element_ids:
            return False
        if source_id == target_id:
            return True
        adjacency: dict[str, list[str]] = {element_id: [] for element_id in element_ids}
        for edge in topology.dependency_edges:
            adjacency[edge.provider_element_id].append(edge.dependent_element_id)
        pending = deque([source_id])
        visited = {source_id}
        while pending:
            current = pending.popleft()
            for dependent_id in adjacency[current]:
                if dependent_id == target_id:
                    return True
                if dependent_id not in visited:
                    visited.add(dependent_id)
                    pending.append(dependent_id)
        return False
