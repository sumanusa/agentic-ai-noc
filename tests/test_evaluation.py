import json

from app import evaluation
from app.evaluation import main, run_evaluation


def test_all_seven_labelled_scenarios_pass_repeatably_without_provider_calls():
    first = run_evaluation(runtime=False)
    second = run_evaluation(runtime=False)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["status"] == "passed"
    assert first["scenario_count"] == 7
    assert first["incident_count"] == 8
    assert first["workflow_run_count"] == 8  # Case F has tool and provider failure subcases.
    assert first["failed_check_count"] == 0
    assert all(row["status"] == "passed" for row in first["scenarios"])


def test_evaluation_metrics_are_explicit_and_not_semantic_accuracy_claims():
    report = run_evaluation(runtime=False)
    metrics = report["metrics"]
    assert metrics["alarm_counts"]["input"] == (
        metrics["alarm_counts"]["operational_representatives"]
        + metrics["alarm_counts"]["suppressed"]
    )
    assert metrics["alarm_counts"]["duplicate_suppression_rate"] == (
        metrics["alarm_counts"]["suppressed"] / metrics["alarm_counts"]["input"]
    )
    assert metrics["correlation"]["false_positive_pairs"] == 0
    assert metrics["correlation"]["false_negative_pairs"] == 0
    assert metrics["evidence_grounding"]["semantic_claim_truth_scored"] is False
    assert metrics["triage_runtime"]["is_repeatable_metric"] is False
    assert metrics["triage_runtime"]["is_real_operational_mttr"] is False
    assert metrics["recommendation_safety"]["unsafe_high_risk_or_operational_recommendations"] == 0
    assert metrics["reliability"]["external_actions_executed"] == 0
    assert metrics["reliability"]["tool_error_records"] == 1
    assert metrics["reliability"]["unavailable_evidence_records"] == 2
    assert metrics["diagnosis_support"]["expected_leading_hypothesis_support_checks"] == 1
    assert metrics["diagnosis_support"]["passed_expected_leading_hypothesis_support_checks"] == 1
    assert metrics["diagnosis_support"]["semantic_diagnosis_quality_scored"] is False


def test_conflicting_ticket_case_is_labeled_as_evaluation_only_injection():
    report = run_evaluation(runtime=False)
    case = next(row for row in report["scenarios"] if row["scenario_id"] == "E")
    assert case["status"] == "passed"
    assert any("evaluation-only injected evidence" in item for item in case["limitations"])
    assert case["assessment"]["conflict_count"] == 1
    assert case["assessment"]["status"] == "inconclusive"


def test_evaluation_cli_emits_machine_readable_json(capsys):
    assert main(["--no-runtime"]) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["suite_id"] == "agentic_noc_core_scenarios_v1"
    assert report["status"] == "passed"


def test_unhandled_graph_error_is_reported_as_a_failed_case(monkeypatch):
    suite = json.loads(evaluation.SCENARIO_FILE.read_text(encoding="utf-8"))
    case = suite["cases"][0]

    def broken_graph(**_kwargs):
        raise RuntimeError("details deliberately omitted")

    monkeypatch.setattr(evaluation.graph_module, "build_graph", broken_graph)
    row = evaluation._run_one(case, mode="standard", ticket_text=None, runtime=False)
    assert row["status"] == "failed"
    assert row["workflow"]["error_type"] == "RuntimeError"
    assert row["assessment"]["status"] is None
    assert "details deliberately omitted" not in json.dumps(row)
