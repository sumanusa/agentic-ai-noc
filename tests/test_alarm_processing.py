import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.alarm_processing import deduplicate_alarms, normalize_alarms
from app.models.alarm import (
    AlarmDeduplicationResult,
    AlarmNormalizationResult,
    DuplicateGroup,
    NormalizedAlarm,
)


FIXTURE = Path(__file__).parents[1] / "data" / "alarms" / "phase2a_events.json"


def fixture_result():
    return json.loads(FIXTURE.read_text())


def by_record_id(result, record_id):
    return next(event for event in result.normalization.events if event.source_record_id == record_id)


def test_fixture_normalization_preserves_fields_and_is_repeatable():
    raw_events = fixture_result()
    first = normalize_alarms({"alarms": raw_events}, evidence_id="ev-fixture-batch")
    second = normalize_alarms({"alarms": raw_events}, evidence_id="ev-fixture-batch")

    assert first.model_dump_json() == second.model_dump_json()
    assert len(first.events) == 13
    assert len(first.issues) == 2
    assert first.evidence_id == "ev-fixture-batch"
    alarm = by_record_id(deduplicate_alarms(first), "SRC-ROW-100-A")
    assert alarm.source_event_id == "SRC-EVT-100"
    assert alarm.occurred_at.isoformat() == "2026-10-14T10:00:00-06:00"
    assert alarm.raw_event == raw_events[0]
    assert alarm.evidence_id == "ev-fixture-batch"
    assert alarm.normalization_status == "complete"
    assert deduplicate_alarms(first).model_dump_json() == deduplicate_alarms(second).model_dump_json()


def test_source_event_id_duplicates_keep_all_original_event_and_evidence_references():
    result = deduplicate_alarms(
        normalize_alarms(fixture_result(), evidence_id="ev-original-batch")
    )

    group = next(
        group for group in result.duplicate_groups
        if group.rule == "same_source_event_id_and_identity_within_window"
    )
    assert group.input_count == 3
    assert group.suppressed_count == 2
    assert group.window_seconds == 300
    assert group.representative_event_reference.source_event_id == "SRC-EVT-100"
    assert [ref.source_record_id for ref in group.original_event_references] == [
        "SRC-ROW-100-A", "SRC-ROW-100-B", "SRC-ROW-100-C",
    ]
    assert all(ref.evidence_id == "ev-original-batch" for ref in group.original_event_references)
    assert group.representative_event_reference in group.original_event_references
    assert result.input_count == len(result.normalization.events) + len(result.normalization.issues)
    assert result.operational_count == len(result.operational_events)
    assert result.suppressed_count == 3
    assert result.invalid_count == 2
    assert result.input_count == 15
    assert len(result.normalization.events) == 13
    assert len(result.normalization.issues) == 2
    assert by_record_id(result, "SRC-ROW-100-B").raw_event == fixture_result()[1]
    assert "SRC-ROW-100-B" not in {
        event.source_record_id for event in result.operational_events
    }


def test_fallback_fingerprint_deduplicates_when_source_event_id_is_missing():
    result = deduplicate_alarms(normalize_alarms(fixture_result()))
    group = next(
        group for group in result.duplicate_groups
        if group.rule == "same_fallback_fingerprint_within_window"
    )

    assert group.input_count == 2
    assert group.suppressed_count == 1
    assert '"source":"synthetic-alarm-feed"' in group.fingerprint
    assert '"site":"DEN-042"' in group.fingerprint
    assert all(ref.source_event_id is None for ref in group.original_event_references)
    assert [ref.source_record_id for ref in group.original_event_references] == [
        "SRC-ROW-FP-1", "SRC-ROW-FP-2",
    ]


def test_row_evidence_references_override_batch_reference_and_survive_grouping():
    first, second = fixture_result()[:2]
    first["evidence_id"] = "ev-source-row-one"
    second["evidence_id"] = "ev-source-row-two"
    result = deduplicate_alarms(
        normalize_alarms([first, second], evidence_id="ev-batch-fallback")
    )
    group = result.duplicate_groups[0]

    assert [reference.evidence_id for reference in group.original_event_references] == [
        "ev-source-row-one", "ev-source-row-two",
    ]
    assert [event.evidence_id for event in result.normalization.events] == [
        "ev-source-row-one", "ev-source-row-two",
    ]


def test_same_fingerprint_outside_window_is_not_suppressed():
    result = deduplicate_alarms(normalize_alarms(fixture_result()))
    early = by_record_id(result, "SRC-ROW-FP-1")
    late = by_record_id(result, "SRC-ROW-FP-LATE")

    assert early.input_index != late.input_index
    early_group = next(
        group for group in result.duplicate_groups
        if early.input_index in {ref.input_index for ref in group.original_event_references}
    )
    assert late.input_index not in {
        ref.input_index for ref in early_group.original_event_references
    }
    assert early in result.operational_events
    assert late in result.operational_events


def test_five_minute_window_is_inclusive_and_configurable():
    first = fixture_result()[0]
    exactly_five_minutes = {**first, "source_record_id": "AT-BOUNDARY", "occurred_at": "2026-10-14T10:05:00-06:00"}
    beyond_five_minutes = {**first, "source_record_id": "OUTSIDE-BOUNDARY", "occurred_at": "2026-10-14T10:05:00.001-06:00"}

    inclusive = deduplicate_alarms(normalize_alarms([first, exactly_five_minutes]))
    exclusive = deduplicate_alarms(normalize_alarms([first, beyond_five_minutes]))
    longer = deduplicate_alarms(
        normalize_alarms([first, beyond_five_minutes]), duplicate_window=timedelta(minutes=6)
    )

    assert inclusive.suppressed_count == 1
    assert exclusive.suppressed_count == 0
    assert longer.suppressed_count == 1
    for invalid_window in (timedelta(0), timedelta(seconds=-1)):
        with pytest.raises(ValueError, match="positive timedelta"):
            deduplicate_alarms(normalize_alarms([first]), duplicate_window=invalid_window)


def test_equivalent_timestamps_with_different_offsets_match_in_utc():
    first = {
        key: value for key, value in fixture_result()[0].items()
        if key != "source_event_id"
    }
    second = {
        **first,
        "source_record_id": "UTC-EQUIVALENT",
        "occurred_at": "2026-10-14T16:03:00Z",
    }
    result = deduplicate_alarms(normalize_alarms([first, second]))

    assert result.suppressed_count == 1
    assert result.duplicate_groups[0].representative_event_reference.input_index == 0


def test_anchored_window_does_not_extend_through_chained_arrivals():
    first = {
        key: value for key, value in fixture_result()[0].items()
        if key != "source_event_id"
    }
    second = {**first, "source_record_id": "CHAIN-4M", "occurred_at": "2026-10-14T10:04:00-06:00"}
    third = {**first, "source_record_id": "CHAIN-8M", "occurred_at": "2026-10-14T10:08:00-06:00"}
    result = deduplicate_alarms(normalize_alarms([first, second, third]))

    assert result.suppressed_count == 1
    assert result.operational_count == 2
    assert [reference.source_record_id for reference in result.duplicate_groups[0].original_event_references] == [
        first["source_record_id"], "CHAIN-4M",
    ]
    assert [event.source_record_id for event in result.operational_events] == [
        first["source_record_id"], "CHAIN-8M",
    ]


def test_equal_timestamp_uses_first_input_row_as_representative():
    first = fixture_result()[0]
    second = {**first, "source_record_id": "SAME-TIME-SECOND"}
    result = deduplicate_alarms(normalize_alarms([first, second]))

    assert result.duplicate_groups[0].representative_event_reference.input_index == 0
    assert result.operational_events[0].source_record_id == first["source_record_id"]


def test_empty_input_has_zero_reconciled_counts():
    normalized = normalize_alarms([])
    result = deduplicate_alarms(normalized)

    assert normalized.input_count == 0
    assert normalized.events == []
    assert normalized.issues == []
    assert result.input_count == 0
    assert result.operational_count == result.suppressed_count == result.invalid_count == 0
    assert result.operational_events == []
    assert result.duplicate_groups == []


def test_all_invalid_rows_reconcile_as_invalid_not_suppressed():
    normalized = normalize_alarms(["not-an-event", {"severity": 3}])
    result = deduplicate_alarms(normalized)

    assert normalized.input_count == 2
    assert normalized.events == []
    assert len(normalized.issues) == 2
    assert result.input_count == 2
    assert result.operational_count == result.suppressed_count == 0
    assert result.invalid_count == 2
    assert result.input_count == (
        result.operational_count + result.suppressed_count + result.invalid_count
    )


@pytest.mark.parametrize(("field", "value"), [
    ("site", "SLC-001"),
    ("element_id", "OTHER-ELEMENT"),
    ("event_code", "OTHER-CODE"),
    ("severity", "critical"),
    ("event_type", "communication"),
    ("lifecycle_state", "cleared"),
    ("source", "another-source"),
])
def test_different_identity_attributes_remain_distinct(field, value):
    first = {
        key: item for key, item in fixture_result()[0].items()
        if key != "source_event_id"
    }
    second = {**first, "source_record_id": "DISTINCT", field: value}
    result = deduplicate_alarms(normalize_alarms([first, second]))

    assert result.suppressed_count == 0
    assert result.operational_count == 2
    assert result.duplicate_groups == []


def test_distinct_source_event_ids_do_not_fallback_deduplicate():
    first = fixture_result()[0]
    second = {**first, "source_event_id": "SRC-EVT-OTHER", "source_record_id": "OTHER-ID"}
    result = deduplicate_alarms(normalize_alarms([first, second]))

    assert result.operational_count == 2
    assert result.suppressed_count == 0
    assert result.duplicate_groups == []


def test_related_but_distinct_alarm_events_are_not_correlated_or_deduplicated():
    result = deduplicate_alarms(normalize_alarms(fixture_result()))
    first = by_record_id(result, "SRC-ROW-RELATED-1")
    second = by_record_id(result, "SRC-ROW-RELATED-2")

    assert first.event_code != second.event_code
    assert first.element_id != second.element_id
    assert first in result.operational_events
    assert second in result.operational_events
    assert not any(
        {first.input_index, second.input_index} <= {
            reference.input_index for reference in group.original_event_references
        }
        for group in result.duplicate_groups
    )


def test_missing_timestamps_or_identity_fields_are_retained_separately():
    result = deduplicate_alarms(normalize_alarms(fixture_result()))
    missing_times = [
        event for event in result.normalization.events
        if event.source_record_id in {"SRC-ROW-NO-TIME-1", "SRC-ROW-NO-TIME-2"}
    ]
    missing_identity = by_record_id(result, "SRC-ROW-NO-ELEMENT")

    assert len(missing_times) == 2
    assert all(event.occurred_at is None for event in missing_times)
    assert all(event.normalization_status == "limited" for event in missing_times)
    assert all("timestamp unavailable" in event.limitations[-1] for event in missing_times)
    assert missing_identity.normalization_status == "limited"
    assert "missing identity field: element_id" in missing_identity.limitations
    assert all(event in result.operational_events for event in (*missing_times, missing_identity))
    assert not any(
        ref.input_index in {event.input_index for event in (*missing_times, missing_identity)}
        for group in result.duplicate_groups for ref in group.original_event_references
    )

    missing_element = {
        key: value for key, value in fixture_result()[0].items()
        if key != "element_id"
    }
    duplicate_missing_element = {
        **missing_element, "source_event_id": "", "source_record_id": "ANOTHER-NO-ELEMENT",
    }
    incomplete_pair = deduplicate_alarms(
        normalize_alarms([missing_element, duplicate_missing_element])
    )
    assert incomplete_pair.operational_count == 2
    assert incomplete_pair.duplicate_groups == []


def test_malformed_rows_are_explicit_issues_and_never_normalized():
    raw_events = fixture_result()
    result = normalize_alarms(raw_events)
    issues_by_record = {issue.source_record_id: issue for issue in result.issues}

    assert set(issues_by_record) == {"SRC-ROW-NAIVE-TIME", "SRC-ROW-BAD-SEVERITY"}
    assert "timezone" in issues_by_record["SRC-ROW-NAIVE-TIME"].error
    assert issues_by_record["SRC-ROW-NAIVE-TIME"].raw_event == raw_events[13]
    assert "severity" in issues_by_record["SRC-ROW-BAD-SEVERITY"].error
    assert all(event.source_record_id not in issues_by_record for event in result.events)

    legacy = normalize_alarms({"alarms": ["CELL_UNAVAILABLE"]})
    assert legacy.events == []
    assert legacy.issues[0].raw_event == "CELL_UNAVAILABLE"
    assert legacy.issues[0].input_index == 0


def test_existing_alarm_source_lacks_fields_required_for_normalization():
    from app.tools.alarms import get_site_alarms_data

    result = normalize_alarms(get_site_alarms_data("DEN-042"))

    assert result.events == []
    assert [issue.raw_event for issue in result.issues] == [
        "CELL_UNAVAILABLE", "HIGH_PACKET_LOSS", "BACKHAUL_LATENCY_HIGH",
    ]


@pytest.mark.parametrize("invalid", [
    {"alarms": "not-a-list"},
    {"error": "source unavailable"},
    "not-an-alarm-result",
])
def test_malformed_source_result_has_validation_issue(invalid):
    result = normalize_alarms(invalid)
    assert result.events == []
    assert len(result.issues) == 1
    assert result.issues[0].raw_event == invalid
    assert result.issues[0].issue_scope == "envelope"
    assert result.issues[0].input_index is None


def test_only_malformed_rows_inside_a_valid_list_receive_row_locators():
    valid = fixture_result()[0]
    result = normalize_alarms([valid, "malformed row"])

    assert [(issue.issue_scope, issue.input_index) for issue in result.issues] == [("row", 1)]
    assert result.issues[0].raw_event == "malformed row"
    for top_level in ("not-an-alarm-result", {"alarms": "not-a-list"}):
        issue = normalize_alarms(top_level).issues[0]
        assert issue.issue_scope == "envelope"
        assert issue.input_index is None


def test_deduplication_revalidates_preconstructed_malformed_models():
    event = normalize_alarms([fixture_result()[0]]).events[0]
    malformed_event = NormalizedAlarm.model_construct(**{
        **event.model_dump(), "site": 42,
    })
    malformed_event_result = AlarmNormalizationResult.model_construct(
        evidence_id=None, input_count=1, events=[malformed_event], issues=[],
    )
    with pytest.raises(ValidationError):
        deduplicate_alarms(malformed_event_result)

    inconsistent_result = AlarmNormalizationResult.model_construct(
        evidence_id=None, input_count=4, events=[event], issues=[],
    )
    with pytest.raises(ValidationError, match="input_count"):
        deduplicate_alarms(inconsistent_result)


def test_malformed_preconstructed_duplicate_group_and_result_are_revalidated():
    raw = fixture_result()[:2]
    valid = deduplicate_alarms(normalize_alarms(raw))
    group = valid.duplicate_groups[0]
    malformed_group = DuplicateGroup.model_construct(
        **{**group.model_dump(), "suppressed_count": 99},
    )
    malformed_result = AlarmDeduplicationResult.model_construct(
        normalization=valid.normalization,
        operational_events=valid.operational_events,
        duplicate_groups=[malformed_group],
        input_count=valid.input_count,
        operational_count=valid.operational_count,
        suppressed_count=valid.suppressed_count,
        invalid_count=valid.invalid_count,
    )

    with pytest.raises(ValidationError, match="suppressed_count"):
        AlarmDeduplicationResult.model_validate(
            malformed_result.model_dump(mode="python", warnings=False)
        )


def test_normalized_model_rejects_naive_datetime():
    with pytest.raises(ValidationError, match="timezone"):
        NormalizedAlarm(
            source="source", site="site", element_id="element", event_code="code",
            event_type="threshold", severity="major", lifecycle_state="raised",
            occurred_at=datetime(2026, 10, 14, 10), input_index=0,
            normalization_status="complete", raw_event={},
        )
