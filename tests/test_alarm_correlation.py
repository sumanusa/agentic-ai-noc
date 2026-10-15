import json
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from app.alarm_correlation import correlate_alarms
from app.alarm_processing import deduplicate_alarms, normalize_alarms
from app.models.alarm import AlarmDeduplicationResult, AlarmNormalizationResult, NormalizedAlarm
from app.models.correlation import AlarmCorrelationGroup, AlarmCorrelationResult


FIXTURE = Path(__file__).parents[1] / "data" / "alarms" / "phase2b_correlation_events.json"


def fixture_rows():
    return json.loads(FIXTURE.read_text())


def correlate(rows, *, window=timedelta(minutes=15)):
    return correlate_alarms(deduplicate_alarms(normalize_alarms(rows)), correlation_window=window)


def test_distinct_events_with_same_explicit_alarm_condition_form_explainable_group():
    result = correlate(fixture_rows())

    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.rule_id == "same_alarm_condition_distinct_source_events_within_window"
    assert [member.event_reference.source_event_id for member in group.members] == [
        "SRC-CORR-201", "SRC-CORR-202",
    ]
    assert group.matching_attributes.element_id == "RTR-DEN-18"
    assert group.matching_attributes.event_code == "BACKHAUL_LATENCY_HIGH"
    assert group.time_span_seconds == 720
    assert group.window_seconds == 900
    assert group.strength == "deterministic_rule_match"
    assert group.ambiguous is False
    assert group.insufficient_evidence is False
    assert group.context_incomplete is True
    assert "does not establish cause" in group.explanation
    assert result.correlated_event_count == 2
    assert result.uncorrelated_event_count == 2


def test_same_site_nearby_different_condition_or_element_stays_uncorrelated():
    result = correlate(fixture_rows())
    by_id = {
        event.source_event_id: event.input_index
        for event in result.deduplication.operational_events
    }
    uncorrelated = {reference.input_index for reference in result.uncorrelated_event_references}

    assert by_id["SRC-CORR-203"] in uncorrelated  # same site/time, different alarm condition
    assert by_id["SRC-CORR-204"] in uncorrelated  # same site/code/time, different element


def test_missing_timestamp_or_identity_is_not_correlated():
    rows = fixture_rows()[:2]
    missing_time = {**rows[1], "source_event_id": "SRC-NO-TIME", "source_record_id": "ROW-NO-TIME"}
    del missing_time["occurred_at"]
    missing_identity = {**rows[1], "source_event_id": "SRC-NO-ELEMENT", "element_id": None}
    result = correlate([rows[0], missing_time, missing_identity])

    assert result.groups == []
    assert result.correlated_event_count == 0
    assert result.uncorrelated_event_count == 3
    assert all(event.normalization_status == "limited" for event in result.deduplication.operational_events[1:])


def test_events_outside_configured_window_stay_separate():
    first, second = fixture_rows()[:2]
    second["occurred_at"] = "2026-10-14T12:16:00-06:00"
    result = correlate([first, second])

    assert result.groups == []
    assert result.uncorrelated_event_count == 2


def test_correlation_window_boundary_is_inclusive():
    first, second = fixture_rows()[:2]
    second["occurred_at"] = "2026-10-14T12:15:00-06:00"
    at_boundary = correlate([first, second])
    second["occurred_at"] = "2026-10-14T12:15:00.001-06:00"
    beyond_boundary = correlate([first, second])

    assert len(at_boundary.groups) == 1
    assert at_boundary.groups[0].time_span_seconds == 900
    assert beyond_boundary.groups == []


def test_duplicate_representative_keeps_every_original_event_and_evidence_reference():
    original_rows = json.loads(
        (Path(__file__).parents[1] / "data" / "alarms" / "phase2a_events.json").read_text()
    )[:3]
    followup = {
        **original_rows[0],
        "source_event_id": "SRC-EVT-100-FOLLOWUP",
        "source_record_id": "SRC-ROW-100-D",
        "evidence_id": "ev-followup",
        "occurred_at": "2026-10-14T10:12:00-06:00",
    }
    result = correlate_alarms(deduplicate_alarms(normalize_alarms(
        [*original_rows, followup], evidence_id="ev-original"
    )))
    group = result.groups[0]

    assert [member.event_reference.source_event_id for member in group.members] == [
        "SRC-EVT-100", "SRC-EVT-100-FOLLOWUP",
    ]
    first_member = group.members[0]
    assert [reference.source_record_id for reference in first_member.original_event_references] == [
        "SRC-ROW-100-A", "SRC-ROW-100-B", "SRC-ROW-100-C",
    ]
    assert [reference.evidence_id for reference in first_member.original_event_references] == [
        "ev-original", "ev-original", "ev-original",
    ]
    assert group.members[1].original_event_references[0].evidence_id == "ev-followup"
    assert result.deduplication.normalization.events[1].raw_event == original_rows[1]


@pytest.mark.parametrize("field,value", [
    ("source", "other-feed"),
    ("site", "SLC-010"),
    ("element_id", "OTHER-ROUTER"),
    ("event_code", "INTERFACE_ERRORS"),
    ("event_type", "state-change"),
    ("severity", "critical"),
    ("lifecycle_state", "cleared"),
])
def test_contradictory_alarm_attributes_prevent_grouping(field, value):
    first, second = fixture_rows()[:2]
    second[field] = value
    result = correlate([first, second])

    assert result.groups == []
    assert result.uncorrelated_event_count == 2


def test_deterministic_result_and_group_id_across_repeated_runs():
    rows = fixture_rows()
    first = correlate(rows)
    second = correlate(rows)

    assert first.model_dump_json() == second.model_dump_json()
    assert [group.group_id for group in first.groups] == [group.group_id for group in second.groups]

    reordered = correlate(list(reversed(rows)))
    assert [group.group_id for group in reordered.groups] == [group.group_id for group in first.groups]


def test_empty_and_all_unrelated_inputs_have_explicit_reconciled_outcomes():
    empty = correlate([])
    unrelated = correlate([fixture_rows()[0], {**fixture_rows()[2], "source_event_id": "UNRELATED"}])

    assert empty.input_count == empty.correlated_event_count == empty.uncorrelated_event_count == 0
    assert empty.groups == []
    assert unrelated.groups == []
    assert unrelated.input_count == 2
    assert unrelated.uncorrelated_event_count == 2
    assert unrelated.correlated_event_count == 0


def test_invalid_window_and_malformed_preconstructed_deduplication_fail_validation():
    with pytest.raises(ValueError, match="positive timedelta"):
        correlate_alarms(deduplicate_alarms(normalize_alarms([])), correlation_window=timedelta(0))

    normalized = normalize_alarms([fixture_rows()[0]])
    valid = deduplicate_alarms(normalized)
    event = normalized.events[0]
    malformed_event = NormalizedAlarm.model_construct(**{**event.model_dump(), "site": 42})
    malformed_normalization = AlarmNormalizationResult.model_construct(**{
        **normalized.model_dump(), "events": [malformed_event],
    })
    malformed_deduplication = AlarmDeduplicationResult.model_construct(**{
        **valid.model_dump(),
        "normalization": malformed_normalization,
        "operational_events": [malformed_event],
    })

    with pytest.raises(ValidationError):
        correlate_alarms(malformed_deduplication)

    with pytest.raises(ValidationError):
        correlate_alarms({"unexpected": "shape"})


def plain_model_data(value):
    if isinstance(value, BaseModel):
        return {key: plain_model_data(item) for key, item in value.__dict__.items()}
    if isinstance(value, dict):
        return {key: plain_model_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain_model_data(item) for item in value]
    return value


def test_malformed_preconstructed_group_and_result_invariants_revalidate():
    result = correlate(fixture_rows())
    valid_group = result.groups[0]
    malformed_group = AlarmCorrelationGroup.model_construct(**{
        **valid_group.model_dump(), "time_span_seconds": 1,
    })
    with pytest.raises(ValidationError, match="time_span_seconds"):
        AlarmCorrelationGroup.model_validate(plain_model_data(malformed_group))

    malformed_result = AlarmCorrelationResult.model_construct(**{
        **result.model_dump(), "input_count": result.input_count + 1,
    })
    with pytest.raises(ValidationError, match="input_count"):
        AlarmCorrelationResult.model_validate(plain_model_data(malformed_result))
