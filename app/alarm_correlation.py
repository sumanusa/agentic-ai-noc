"""Standalone deterministic correlation for explicitly repeated alarm conditions."""

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel

from app.models.alarm import AlarmDeduplicationResult, NormalizedAlarm
from app.models.correlation import (
    AlarmCorrelationGroup,
    AlarmCorrelationResult,
    CORRELATION_EXPLANATION,
    CorrelatedEvent,
    CorrelationAttributes,
    expected_group_id,
)


DEFAULT_CORRELATION_WINDOW = timedelta(minutes=15)
RULE_ID = "same_alarm_condition_distinct_source_events_within_window"
_MATCH_FIELDS = (
    "source", "site", "element_id", "event_code", "event_type", "severity",
    "lifecycle_state",
)


def _plain_data(value: Any) -> Any:
    """Recursively dump models so constructed instances are fully revalidated."""
    if isinstance(value, BaseModel):
        return _plain_data(value.model_dump(mode="python", warnings=False))
    if isinstance(value, Mapping):
        return {key: _plain_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_data(item) for item in value]
    return value


def _identity(event: NormalizedAlarm) -> tuple[str, ...] | None:
    values = tuple(getattr(event, field) for field in _MATCH_FIELDS)
    if any(value is None for value in values):
        return None
    return values


def _attributes(event: NormalizedAlarm) -> CorrelationAttributes:
    return CorrelationAttributes(**{field: getattr(event, field) for field in _MATCH_FIELDS})


def correlate_alarms(
    deduplication: AlarmDeduplicationResult,
    *,
    correlation_window: timedelta = DEFAULT_CORRELATION_WINDOW,
) -> AlarmCorrelationResult:
    """Group distinct source events reporting one exact alarm condition.

    Only complete, timezone-aware events with distinct source event IDs qualify.
    Each cluster is anchored to its earliest event; shared site/time alone is never
    a matching rule. The result is an event relationship, not a cause assessment.
    """
    if not isinstance(correlation_window, timedelta) or correlation_window <= timedelta(0):
        raise ValueError("correlation_window must be a positive timedelta")
    deduplication = AlarmDeduplicationResult.model_validate(_plain_data(deduplication))

    eligible: dict[tuple[str, ...], list[NormalizedAlarm]] = defaultdict(list)
    for event in deduplication.operational_events:
        identity = _identity(event)
        if (
            identity is not None
            and event.normalization_status == "complete"
            and event.occurred_at is not None
            and event.source_event_id is not None
        ):
            eligible[identity].append(event)

    provenance: dict[int, list] = {}
    for event in deduplication.operational_events:
        duplicate = next((
            group for group in deduplication.duplicate_groups
            if group.representative_event_reference.input_index == event.input_index
        ), None)
        provenance[event.input_index] = (
            duplicate.original_event_references if duplicate else [event.source_reference()]
        )

    groups: list[AlarmCorrelationGroup] = []
    grouped_indexes: set[int] = set()
    for events in eligible.values():
        ordered = sorted(
            events,
            key=lambda event: (
                event.occurred_at.astimezone(timezone.utc), event.source_event_id,
            ),
        )
        clusters: list[list[NormalizedAlarm]] = []
        for event in ordered:
            event_time = event.occurred_at.astimezone(timezone.utc)
            if clusters:
                first_time = clusters[-1][0].occurred_at.astimezone(timezone.utc)
                if event_time - first_time <= correlation_window:
                    clusters[-1].append(event)
                    continue
            clusters.append([event])

        for cluster in clusters:
            if len(cluster) < 2:
                continue
            attrs = _attributes(cluster[0])
            first = cluster[0].occurred_at.astimezone(timezone.utc)
            last = cluster[-1].occurred_at.astimezone(timezone.utc)
            members = [
                CorrelatedEvent(
                    event_reference=event.source_reference(),
                    original_event_references=provenance[event.input_index],
                )
                for event in cluster
            ]
            event_ids = [event.source_event_id for event in cluster]
            groups.append(AlarmCorrelationGroup(
                group_id=expected_group_id(attrs, event_ids, first, last),
                rule_id=RULE_ID,
                explanation=CORRELATION_EXPLANATION,
                matching_attributes=attrs,
                members=members,
                first_occurred_at=first,
                last_occurred_at=last,
                time_span_seconds=(last - first).total_seconds(),
                window_seconds=correlation_window.total_seconds(),
                context_incomplete=True,
            ))
            grouped_indexes.update(event.input_index for event in cluster)

    groups.sort(key=lambda group: (group.first_occurred_at.astimezone(timezone.utc), group.group_id))
    uncorrelated = [
        event.source_reference() for event in deduplication.operational_events
        if event.input_index not in grouped_indexes
    ]
    correlated_count = sum(len(group.members) for group in groups)
    return AlarmCorrelationResult(
        deduplication=deduplication,
        groups=groups,
        uncorrelated_event_references=uncorrelated,
        input_count=deduplication.operational_count,
        correlated_event_count=correlated_count,
        uncorrelated_event_count=len(uncorrelated),
    )
