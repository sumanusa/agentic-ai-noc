"""Validated records for the deterministic Phase 2A alarm pipeline."""

from datetime import datetime, timedelta, timezone
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


_IDENTITY_FIELDS = (
    "source", "site", "element_id", "event_code", "event_type", "severity",
    "lifecycle_state",
)


def _event_fingerprint(event: "NormalizedAlarm") -> tuple[str, str] | None:
    if any(getattr(event, field) is None for field in _IDENTITY_FIELDS):
        return None
    identity = {field: getattr(event, field) for field in _IDENTITY_FIELDS}
    if event.source_event_id is None:
        mode = "fallback_fingerprint"
    else:
        mode = "source_event_id"
        identity["source_event_id"] = event.source_event_id
    return mode, json.dumps(identity, sort_keys=True, separators=(",", ":"))


class AlarmReference(BaseModel):
    """A source locator; input_index is a row locator, never an event ID."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    input_index: int = Field(ge=0)
    source_event_id: str | None = None
    source_record_id: str | None = None
    evidence_id: str | None = None


class NormalizedAlarm(BaseModel):
    """Normalized alarm attributes plus the untouched source row and provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    source: str | None = None
    source_event_id: str | None = None
    source_record_id: str | None = None
    evidence_id: str | None = None
    site: str | None = None
    element_id: str | None = None
    event_code: str | None = None
    event_type: str | None = None
    severity: str | None = None
    lifecycle_state: str | None = None
    occurred_at: datetime | None = None
    input_index: int = Field(ge=0)
    normalization_status: Literal["complete", "limited"]
    limitations: list[str] = Field(default_factory=list)
    raw_event: dict[str, Any]

    @model_validator(mode="after")
    def timestamp_must_be_aware(self):
        if self.occurred_at is not None and (
            self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None
        ):
            raise ValueError("occurred_at must include a timezone")
        missing = [
            f"missing identity field: {field}"
            for field in _IDENTITY_FIELDS
            if getattr(self, field) is None
        ]
        expected_limitations = missing.copy()
        if self.occurred_at is None:
            expected_limitations.append("timestamp unavailable; time-window deduplication skipped")
        if self.limitations != expected_limitations:
            raise ValueError("limitations must describe missing identity fields and timestamp")
        expected_status = "limited" if expected_limitations else "complete"
        if self.normalization_status != expected_status:
            raise ValueError("normalization_status must match the event limitations")
        for field in (*_IDENTITY_FIELDS, "source_event_id", "source_record_id", "evidence_id"):
            value = getattr(self, field)
            if value is not None and not value.strip():
                raise ValueError(f"{field} must be non-empty when provided")
        return self

    def source_reference(self) -> AlarmReference:
        return AlarmReference(
            input_index=self.input_index,
            source_event_id=self.source_event_id,
            source_record_id=self.source_record_id,
            evidence_id=self.evidence_id,
        )


class AlarmNormalizationIssue(BaseModel):
    """A rejected input row retained for review; no normalized event is fabricated."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    issue_scope: Literal["row", "envelope"]
    input_index: int | None = Field(default=None, ge=0)
    source_event_id: str | None = None
    source_record_id: str | None = None
    evidence_id: str | None = None
    error: str = Field(min_length=1)
    raw_event: Any

    @model_validator(mode="after")
    def locator_matches_issue_scope(self):
        if (self.issue_scope == "row") != (self.input_index is not None):
            raise ValueError("only row-level issues may have an input_index")
        return self


class AlarmNormalizationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    evidence_id: str | None = None
    input_count: int = Field(ge=0)
    events: list[NormalizedAlarm] = Field(default_factory=list)
    issues: list[AlarmNormalizationIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def input_rows_and_locators_match(self):
        row_issues = [issue for issue in self.issues if issue.issue_scope == "row"]
        if self.input_count != len(self.events) + len(row_issues):
            raise ValueError("input_count must match normalized events and row-level issues")
        indexes = [event.input_index for event in self.events]
        indexes.extend(issue.input_index for issue in row_issues)
        if len(indexes) != len(set(indexes)):
            raise ValueError("each source row must have exactly one normalization outcome")
        if any(index >= self.input_count for index in indexes):
            raise ValueError("row input_index must be within the source input count")
        return self


class DuplicateGroup(BaseModel):
    """Repeated source events collapsed to one operational representative."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    rule: Literal[
        "same_source_event_id_and_identity_within_window",
        "same_fallback_fingerprint_within_window",
    ]
    fingerprint: str = Field(min_length=1)
    representative_event_reference: AlarmReference
    original_event_references: list[AlarmReference] = Field(min_length=2)
    input_count: int = Field(ge=2)
    suppressed_count: int = Field(ge=1)
    window_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def group_counts_and_references_match(self):
        references = self.original_event_references
        if self.input_count != len(references):
            raise ValueError("input_count must match original event references")
        if self.suppressed_count != self.input_count - 1:
            raise ValueError("suppressed_count must exclude exactly one representative")
        if len({reference.input_index for reference in references}) != len(references):
            raise ValueError("duplicate group references must be unique")
        if self.representative_event_reference not in references:
            raise ValueError("representative must be one of the original event references")
        return self


class AlarmDeduplicationResult(BaseModel):
    """Full source retention and its smaller operational representative view."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    normalization: AlarmNormalizationResult
    operational_events: list[NormalizedAlarm]
    duplicate_groups: list[DuplicateGroup] = Field(default_factory=list)
    input_count: int = Field(ge=0)
    operational_count: int = Field(ge=0)
    suppressed_count: int = Field(ge=0)
    invalid_count: int = Field(ge=0)

    @model_validator(mode="after")
    def counts_and_event_references_match(self):
        if self.input_count != self.normalization.input_count:
            raise ValueError("input_count must match original source rows")
        if self.operational_count != len(self.operational_events):
            raise ValueError("operational_count must match operational events")
        if self.invalid_count != self.input_count - len(self.normalization.events):
            raise ValueError("invalid_count must match rows that failed normalization")
        if self.input_count != self.operational_count + self.suppressed_count + self.invalid_count:
            raise ValueError("input_count must equal operational, suppressed, and invalid rows")

        all_events = {event.input_index: event for event in self.normalization.events}
        if len(all_events) != len(self.normalization.events):
            raise ValueError("normalized input indexes must be unique")
        operational_indexes = [event.input_index for event in self.operational_events]
        if len(operational_indexes) != len(set(operational_indexes)):
            raise ValueError("operational event references must be unique")
        if any(index not in all_events for index in operational_indexes):
            raise ValueError("operational events must come from normalized input events")
        if any(all_events[event.input_index] != event for event in self.operational_events):
            raise ValueError("operational events must match their normalized source rows")

        grouped_indexes: set[int] = set()
        for group in self.duplicate_groups:
            indexes = {reference.input_index for reference in group.original_event_references}
            if not indexes <= all_events.keys():
                raise ValueError("duplicate group references must exist in normalized input")
            if grouped_indexes & indexes:
                raise ValueError("an event cannot occur in multiple duplicate groups")
            grouped_indexes.update(indexes)
            group_events = [all_events[index] for index in indexes]
            for reference in group.original_event_references:
                if all_events[reference.input_index].source_reference() != reference:
                    raise ValueError("duplicate group references must match normalized source references")
            fingerprints = {_event_fingerprint(event) for event in group_events}
            if len(fingerprints) != 1 or None in fingerprints:
                raise ValueError("duplicate group events must share a complete identity fingerprint")
            identity_mode, fingerprint = next(iter(fingerprints))
            if group.fingerprint != fingerprint:
                raise ValueError("duplicate group fingerprint must match its source events")
            expected_rule = (
                "same_source_event_id_and_identity_within_window"
                if identity_mode == "source_event_id"
                else "same_fallback_fingerprint_within_window"
            )
            if group.rule != expected_rule:
                raise ValueError("duplicate group rule must match its identity mode")
            representative = all_events[group.representative_event_reference.input_index]
            if any(event.normalization_status != "complete" or event.occurred_at is None for event in group_events):
                raise ValueError("duplicate group events must have complete identity and timestamps")
            representative_time = representative.occurred_at.astimezone(timezone.utc)
            for event in group_events:
                event_time = event.occurred_at.astimezone(timezone.utc)
                if event_time < representative_time or event_time - representative_time > timedelta(seconds=group.window_seconds):
                    raise ValueError("duplicate group events must fall within the representative window")
            earliest = min(
                group_events,
                key=lambda event: (event.occurred_at.astimezone(timezone.utc), event.input_index),
            )
            if earliest.input_index != representative.input_index:
                raise ValueError("duplicate representative must be the earliest event")
            if group.representative_event_reference.input_index not in operational_indexes:
                raise ValueError("each duplicate representative must remain operational")
            if any(index in operational_indexes for index in indexes - {group.representative_event_reference.input_index}):
                raise ValueError("suppressed events cannot remain operational representatives")

        if sum(group.suppressed_count for group in self.duplicate_groups) != self.suppressed_count:
            raise ValueError("duplicate group suppression counts must match result count")

        represented = grouped_indexes | set(operational_indexes)
        if represented != set(all_events):
            raise ValueError("every normalized input event must remain represented")
        return self
