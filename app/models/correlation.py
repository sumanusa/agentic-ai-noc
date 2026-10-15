"""Validated contracts for deterministic alarm correlation."""

from datetime import datetime, timezone
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.alarm import AlarmDeduplicationResult, AlarmReference

CORRELATION_EXPLANATION = (
    "Distinct source event IDs report the same source, site, element, alarm code, "
    "type, severity, and lifecycle state within the configured anchored time window. "
    "This establishes a recurring alarm-condition relationship only; it does not "
    "establish cause."
)


def expected_group_id(
    attributes: "CorrelationAttributes",
    source_event_ids: list[str],
    first_occurred_at: datetime,
    last_occurred_at: datetime,
) -> str:
    """Derive a stable group identifier without using row order or invented event IDs."""
    canonical = {
        "attributes": attributes.model_dump(mode="json"),
        "source_event_ids": sorted(source_event_ids),
        "first_utc": first_occurred_at.astimezone(timezone.utc).isoformat(),
        "last_utc": last_occurred_at.astimezone(timezone.utc).isoformat(),
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return f"corr-{digest}"


class CorrelationAttributes(BaseModel):
    """Exact shared attributes required by the supported recurrence rule."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    source: str = Field(min_length=1)
    site: str = Field(min_length=1)
    element_id: str = Field(min_length=1)
    event_code: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    lifecycle_state: str = Field(min_length=1)


class CorrelatedEvent(BaseModel):
    """An operational representative and every source row it represents."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    event_reference: AlarmReference
    original_event_references: list[AlarmReference] = Field(min_length=1)

    @model_validator(mode="after")
    def references_are_unique_and_include_representative(self):
        indexes = [reference.input_index for reference in self.original_event_references]
        if len(indexes) != len(set(indexes)):
            raise ValueError("original event references must be unique")
        if self.event_reference not in self.original_event_references:
            raise ValueError("original event references must include the representative")
        return self


class AlarmCorrelationGroup(BaseModel):
    """Explainable relationship between distinct source-identified alarms."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    group_id: str = Field(pattern=r"^corr-[0-9a-f]{24}$")
    rule_id: Literal["same_alarm_condition_distinct_source_events_within_window"]
    explanation: str = Field(min_length=1)
    matching_attributes: CorrelationAttributes
    members: list[CorrelatedEvent] = Field(min_length=2)
    first_occurred_at: datetime
    last_occurred_at: datetime
    time_span_seconds: float = Field(ge=0)
    window_seconds: float = Field(gt=0)
    strength: Literal["deterministic_rule_match"] = "deterministic_rule_match"
    ambiguous: bool = False
    insufficient_evidence: bool = False
    context_incomplete: bool = True

    @model_validator(mode="after")
    def group_members_are_distinct_and_times_are_valid(self):
        if self.explanation != CORRELATION_EXPLANATION:
            raise ValueError("explanation must accurately describe the deterministic rule")
        if self.first_occurred_at.tzinfo is None or self.last_occurred_at.tzinfo is None:
            raise ValueError("correlation timestamps must be timezone-aware")
        if self.first_occurred_at.utcoffset() is None or self.last_occurred_at.utcoffset() is None:
            raise ValueError("correlation timestamps must be timezone-aware")
        first = self.first_occurred_at.astimezone(timezone.utc)
        last = self.last_occurred_at.astimezone(timezone.utc)
        if last < first:
            raise ValueError("last_occurred_at must not precede first_occurred_at")
        if (last - first).total_seconds() != self.time_span_seconds:
            raise ValueError("time_span_seconds must match the group timestamps")
        if self.time_span_seconds > self.window_seconds:
            raise ValueError("group members must fit within the anchored correlation window")
        representative_indexes = [member.event_reference.input_index for member in self.members]
        if len(representative_indexes) != len(set(representative_indexes)):
            raise ValueError("correlation group members must be unique")
        event_ids = [member.event_reference.source_event_id for member in self.members]
        if any(not event_id for event_id in event_ids) or len(event_ids) != len(set(event_ids)):
            raise ValueError("correlation members require distinct source event IDs")
        if self.group_id != expected_group_id(
            self.matching_attributes, event_ids, self.first_occurred_at, self.last_occurred_at,
        ):
            raise ValueError("group_id must be derived from the declared members and attributes")
        return self


class AlarmCorrelationResult(BaseModel):
    """Correlation groups plus an explicit uncorrelated representative view."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    deduplication: AlarmDeduplicationResult
    groups: list[AlarmCorrelationGroup] = Field(default_factory=list)
    uncorrelated_event_references: list[AlarmReference] = Field(default_factory=list)
    input_count: int = Field(ge=0)
    correlated_event_count: int = Field(ge=0)
    uncorrelated_event_count: int = Field(ge=0)

    @model_validator(mode="after")
    def membership_provenance_and_counts_reconcile(self):
        if self.input_count != self.deduplication.operational_count:
            raise ValueError("input_count must match deduplicated operational events")
        if self.uncorrelated_event_count != len(self.uncorrelated_event_references):
            raise ValueError("uncorrelated_event_count must match its references")
        grouped_members = [member for group in self.groups for member in group.members]
        if self.correlated_event_count != len(grouped_members):
            raise ValueError("correlated_event_count must match correlation group members")
        if self.input_count != self.correlated_event_count + self.uncorrelated_event_count:
            raise ValueError("input_count must equal correlated and uncorrelated representative counts")

        operations = {event.input_index: event for event in self.deduplication.operational_events}
        if len(operations) != self.deduplication.operational_count:
            raise ValueError("operational event indexes must be unique")
        expected_originals: dict[int, list[AlarmReference]] = {}
        for event in self.deduplication.operational_events:
            duplicate_group = next((
                group for group in self.deduplication.duplicate_groups
                if group.representative_event_reference.input_index == event.input_index
            ), None)
            expected_originals[event.input_index] = (
                duplicate_group.original_event_references
                if duplicate_group else [event.source_reference()]
            )

        grouped_indexes: list[int] = []
        for group in self.groups:
            if group.context_incomplete is not True:
                raise ValueError("standalone correlation must flag topology/context as incomplete")
            group_events: list[tuple[datetime, str]] = []
            for member in group.members:
                reference = member.event_reference
                event = operations.get(reference.input_index)
                if event is None or event.source_reference() != reference:
                    raise ValueError("correlation member must reference an operational event")
                if member.original_event_references != expected_originals[reference.input_index]:
                    raise ValueError("correlation member must preserve all original source references")
                attrs = group.matching_attributes
                if any(
                    getattr(event, field) != getattr(attrs, field)
                    for field in CorrelationAttributes.model_fields
                ):
                    raise ValueError("correlation member attributes must match the declared rule attributes")
                if event.normalization_status != "complete" or event.occurred_at is None:
                    raise ValueError("correlation members require complete identity and timestamps")
                group_events.append((event.occurred_at.astimezone(timezone.utc), event.source_event_id))
                grouped_indexes.append(reference.input_index)
            times = [time for time, _ in group_events]
            if min(times) != group.first_occurred_at.astimezone(timezone.utc):
                raise ValueError("first_occurred_at must match the earliest member")
            if max(times) != group.last_occurred_at.astimezone(timezone.utc):
                raise ValueError("last_occurred_at must match the latest member")
            ordered_ids = [event_id for _, event_id in sorted(group_events)]
            if len(ordered_ids) != len(set(ordered_ids)):
                raise ValueError("source event IDs must be distinct within a group")

        uncorrelated_indexes = []
        for reference in self.uncorrelated_event_references:
            event = operations.get(reference.input_index)
            if event is None or event.source_reference() != reference:
                raise ValueError("uncorrelated references must point to operational events")
            uncorrelated_indexes.append(reference.input_index)
        all_indexes = grouped_indexes + uncorrelated_indexes
        if len(all_indexes) != len(set(all_indexes)):
            raise ValueError("each operational event must appear in exactly one correlation outcome")
        if set(all_indexes) != set(operations):
            raise ValueError("all operational events must be grouped or explicitly uncorrelated")
        if len({group.group_id for group in self.groups}) != len(self.groups):
            raise ValueError("correlation group IDs must be unique")
        return self
