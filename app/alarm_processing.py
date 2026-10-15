"""Pure, deterministic normalization and deduplication of synthetic alarms."""

import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel

from app.models.alarm import (
    AlarmDeduplicationResult,
    AlarmNormalizationIssue,
    AlarmNormalizationResult,
    AlarmReference,
    DuplicateGroup,
    NormalizedAlarm,
)


DEFAULT_DUPLICATE_WINDOW = timedelta(minutes=5)
_IDENTITY_FIELDS = (
    "source", "site", "element_id", "event_code", "event_type", "severity",
    "lifecycle_state",
)
_STRING_FIELDS = (
    "source", "source_event_id", "source_record_id", "site", "element_id",
    "event_code", "event_type", "severity", "lifecycle_state",
)
_ALLOWED_FIELDS = frozenset((*_STRING_FIELDS, "occurred_at", "evidence_id"))


def _safe_reference_value(row: Any, field: str) -> str | None:
    if isinstance(row, Mapping):
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _issue(index: int | None, row: Any, evidence_id: str | None, error: str) -> AlarmNormalizationIssue:
    row_evidence_id = _safe_reference_value(row, "evidence_id")
    return AlarmNormalizationIssue(
        issue_scope="row" if index is not None else "envelope",
        input_index=index,
        source_event_id=_safe_reference_value(row, "source_event_id"),
        source_record_id=_safe_reference_value(row, "source_record_id"),
        evidence_id=row_evidence_id or evidence_id,
        error=error,
        raw_event=row,
    )


def _parse_row(
    row: Any, *, input_index: int, evidence_id: str | None,
) -> NormalizedAlarm | AlarmNormalizationIssue:
    if not isinstance(row, Mapping) or not all(isinstance(key, str) for key in row):
        return _issue(input_index, row, evidence_id, "alarm row must be an object with string keys")
    raw = dict(row)
    unknown = sorted(set(raw) - _ALLOWED_FIELDS)
    if unknown:
        return _issue(input_index, raw, evidence_id, "alarm row contains unsupported fields")

    values: dict[str, Any] = {}
    for field in _STRING_FIELDS:
        value = raw.get(field)
        if value is None:
            values[field] = None
        elif isinstance(value, str):
            values[field] = value.strip() or None
        else:
            return _issue(input_index, raw, evidence_id, f"{field} must be a string or null")

    row_evidence_id = raw.get("evidence_id")
    if row_evidence_id is not None and not isinstance(row_evidence_id, str):
        return _issue(input_index, raw, evidence_id, "evidence_id must be a string or null")
    if isinstance(row_evidence_id, str):
        row_evidence_id = row_evidence_id.strip() or None

    occurred_at = None
    raw_timestamp = raw.get("occurred_at")
    if raw_timestamp is not None:
        if isinstance(raw_timestamp, datetime):
            occurred_at = raw_timestamp
        elif isinstance(raw_timestamp, str) and raw_timestamp.strip():
            try:
                occurred_at = datetime.fromisoformat(raw_timestamp.strip().replace("Z", "+00:00"))
            except ValueError:
                return _issue(input_index, raw, evidence_id, "occurred_at is not a valid ISO timestamp")
        else:
            return _issue(input_index, raw, evidence_id, "occurred_at must be an ISO timestamp or null")
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            return _issue(input_index, raw, evidence_id, "occurred_at must include a timezone")

    missing_identity = [field for field in _IDENTITY_FIELDS if values[field] is None]
    limitations = [f"missing identity field: {field}" for field in missing_identity]
    if occurred_at is None:
        limitations.append("timestamp unavailable; time-window deduplication skipped")
    return NormalizedAlarm(
        **values,
        evidence_id=row_evidence_id or evidence_id,
        occurred_at=occurred_at,
        input_index=input_index,
        normalization_status="limited" if limitations else "complete",
        limitations=limitations,
        raw_event=raw,
    )


def normalize_alarms(
    source_result: Any,
    *,
    evidence_id: str | None = None,
) -> AlarmNormalizationResult:
    """Normalize a successful alarm result without manufacturing missing values.

    Accepts either the source contract ``{"alarms": [...]}`` or its event list.
    Malformed rows are returned as issues with their original input and position.
    """
    if evidence_id is not None and (not isinstance(evidence_id, str) or not evidence_id.strip()):
        raise ValueError("evidence_id must be a non-empty string when provided")
    evidence_id = evidence_id.strip() if evidence_id else None

    if isinstance(source_result, Mapping):
        if "error" in source_result:
            issue = _issue(None, source_result, evidence_id, "source result contains an error")
            return AlarmNormalizationResult(evidence_id=evidence_id, input_count=0, issues=[issue])
        rows = source_result.get("alarms")
        if not isinstance(rows, list):
            issue = _issue(None, source_result, evidence_id, "source result must contain an alarms list")
            return AlarmNormalizationResult(evidence_id=evidence_id, input_count=0, issues=[issue])
    elif isinstance(source_result, list):
        rows = source_result
    else:
        issue = _issue(None, source_result, evidence_id, "alarm input must be an object or list")
        return AlarmNormalizationResult(evidence_id=evidence_id, input_count=0, issues=[issue])

    events: list[NormalizedAlarm] = []
    issues: list[AlarmNormalizationIssue] = []
    for index, row in enumerate(rows):
        parsed = _parse_row(row, input_index=index, evidence_id=evidence_id)
        if isinstance(parsed, AlarmNormalizationIssue):
            issues.append(parsed)
        else:
            events.append(parsed)
    return AlarmNormalizationResult(
        evidence_id=evidence_id, input_count=len(rows), events=events, issues=issues,
    )


def _fingerprint(event: NormalizedAlarm) -> tuple[str, str]:
    """Return a canonical identity fingerprint, explicitly not an event ID."""
    if any(getattr(event, field) is None for field in _IDENTITY_FIELDS):
        raise ValueError("incomplete alarm identity has no deduplication fingerprint")
    identity = {field: getattr(event, field) for field in _IDENTITY_FIELDS}
    if event.source_event_id is not None:
        identity_mode = "source_event_id"
        identity["source_event_id"] = event.source_event_id
    else:
        identity_mode = "fallback_fingerprint"
    return identity_mode, json.dumps(identity, sort_keys=True, separators=(",", ":"))


def _plain_model_data(value: Any) -> Any:
    """Recursively convert Pydantic instances to plain data for full revalidation."""
    if isinstance(value, BaseModel):
        return _plain_model_data(value.model_dump(mode="python", warnings=False))
    if isinstance(value, Mapping):
        return {key: _plain_model_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_model_data(item) for item in value]
    return value


def deduplicate_alarms(
    normalized: AlarmNormalizationResult,
    *,
    duplicate_window: timedelta = DEFAULT_DUPLICATE_WINDOW,
) -> AlarmDeduplicationResult:
    """Collapse same-identity events within a timezone-aware, anchored window.

    The representative is the earliest event in each window. Repeated arrivals do
    not extend that window, avoiding transitive suppression of long alarm flaps.
    """
    if not isinstance(duplicate_window, timedelta) or duplicate_window <= timedelta(0):
        raise ValueError("duplicate_window must be a positive timedelta")
    normalized = AlarmNormalizationResult.model_validate(_plain_model_data(normalized))

    eligible = [
        event for event in normalized.events
        if event.normalization_status == "complete" and event.occurred_at is not None
    ]
    ordered = sorted(
        eligible,
        key=lambda event: (event.occurred_at.astimezone(timezone.utc), event.input_index),
    )
    candidates: dict[str, list[list[NormalizedAlarm]]] = {}
    for event in ordered:
        identity_mode, fingerprint = _fingerprint(event)
        by_fingerprint = candidates.setdefault(fingerprint, [])
        event_time = event.occurred_at.astimezone(timezone.utc)
        if by_fingerprint:
            latest_group = by_fingerprint[-1]
            representative_time = latest_group[0].occurred_at.astimezone(timezone.utc)
            if event_time - representative_time <= duplicate_window:
                latest_group.append(event)
                continue
        by_fingerprint.append([event])

    group_models: list[DuplicateGroup] = []
    suppressed_indexes: set[int] = set()
    for fingerprint, matching_groups in candidates.items():
        for matching in matching_groups:
            if len(matching) < 2:
                continue
            representative = matching[0]
            original_events = sorted(matching, key=lambda event: event.input_index)
            identity_mode, _ = _fingerprint(representative)
            rule = (
                "same_source_event_id_and_identity_within_window"
                if identity_mode == "source_event_id"
                else "same_fallback_fingerprint_within_window"
            )
            references = [event.source_reference() for event in original_events]
            group_models.append(DuplicateGroup(
                rule=rule,
                fingerprint=fingerprint,
                representative_event_reference=representative.source_reference(),
                original_event_references=references,
                input_count=len(original_events),
                suppressed_count=len(original_events) - 1,
                window_seconds=duplicate_window.total_seconds(),
            ))
            suppressed_indexes.update(
                event.input_index for event in original_events if event is not representative
            )

    operational = [
        event for event in normalized.events if event.input_index not in suppressed_indexes
    ]
    group_models.sort(key=lambda group: group.representative_event_reference.input_index)
    return AlarmDeduplicationResult(
        normalization=normalized,
        operational_events=operational,
        duplicate_groups=group_models,
        input_count=normalized.input_count,
        operational_count=len(operational),
        suppressed_count=len(suppressed_indexes),
        invalid_count=normalized.input_count - len(normalized.events),
    )
