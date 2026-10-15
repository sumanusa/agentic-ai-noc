"""Repeatable synthetic evaluation runner; diagnosis semantics remain human-reviewed."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from itertools import combinations
import json
from pathlib import Path
import re
from time import perf_counter
from typing import Any
from unittest.mock import patch

from app import graph as graph_module
from app.evidence import collect_evidence
from app.models.assessment import AssessmentDraft
from app.models.evidence import EvidenceRecord, make_evidence_record
from app.models.incident import Incident

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_FILE = ROOT / "data/evaluation/scenarios.json"
EVIDENCE_ID_PATTERN = re.compile(r"ev-[a-f0-9]{16}")
EVIDENCE_SOURCE_PATTERN = re.compile(
    r"'evidence_id': '(ev-[a-f0-9]{16})'.*?'source': '([^']+)'"
)


class EvaluationLLM:
    """Fixed structured-output test double; never calls a provider."""

    def __init__(self, mode: str):
        self.mode = mode

    def with_structured_output(self, schema):
        if schema is not AssessmentDraft:
            raise TypeError("evaluation stub only supports AssessmentDraft")
        return self

    def invoke(self, messages):
        if self.mode == "provider_unavailable":
            raise TimeoutError("synthetic evaluation provider timeout")
        content = messages[-1].content
        ids = list(dict.fromkeys(EVIDENCE_ID_PATTERN.findall(content)))
        evidence_by_source = {
            source: evidence_id for evidence_id, source in EVIDENCE_SOURCE_PATTERN.findall(content)
        }
        hypotheses = []
        confidence = 0.2
        conflicts = []
        uncertainty = "Synthetic evaluation signals are insufficient to establish cause."
        next_steps = ["Collect an independent service-health sample and review the event window."]
        if self.mode in {"supported", "low_confidence"}:
            support_id = evidence_by_source.get("phase2d_alarm_fixture") or (ids[0] if ids else "")
            hypotheses = [{
                "statement": "Possible backhaul performance degradation; validate with current counters.",
                "confidence": 0.78 if self.mode == "supported" else 0.35,
                "supporting_evidence_ids": [support_id],
            }]
            confidence = 0.78 if self.mode == "supported" else 0.35
            uncertainty = "This is a synthetic, uncalibrated hypothesis requiring operational verification."
        if self.mode == "conflict":
            conflict_ids = [evidence_by_source[source] for source in (
                "phase2d_alarm_fixture", "telemetry", "evaluation_ticket_fixture",
            ) if source in evidence_by_source]
            conflicts = [{
                "description": "Alarm and telemetry disagree with the synthetic ticket's normal-service note.",
                "evidence_ids": conflict_ids,
            }]
            next_steps = ["Request a fresh service-health measurement and reconcile its time window with the ticket."]
        return AssessmentDraft(
            hypotheses=hypotheses,
            conflicts=conflicts,
            unresolved_questions=(["Does a fresh independent service-health measurement confirm impact?"]
                                 if self.mode in {"conflict", "low_confidence"} else []),
            confidence=confidence,
            uncertainty=uncertainty,
            recommended_action=("Collect additional evidence before diagnosing."
                                if not hypotheses or self.mode == "low_confidence"
                                else "Review current backhaul counters."),
            rationale="Fixed offline evaluation response; not a diagnosis-quality judgment.",
            action_risk="LOW",
            recommendation_type="investigative",
            human_approval_required=False,
            recommended_next_steps=next_steps,
        )


def _scenario_path(value: str) -> Path:
    return (SCENARIO_FILE.parent / value).resolve()


def _actual_pairs(state: dict[str, Any]) -> set[tuple[str, str]]:
    pairs = set()
    correlation = state.get("alarm_correlation")
    if correlation is None:
        return pairs
    for group in correlation.groups:
        event_ids = sorted({
            member.event_reference.source_event_id
            for member in group.members if member.event_reference.source_event_id
        })
        pairs.update(combinations(event_ids, 2))
    return pairs


def _expected_pairs(case: dict[str, Any]) -> set[tuple[str, str]]:
    return {tuple(sorted(pair)) for pair in case.get("expected_correlated_pairs", [])}


def _replace_record(record: EvidenceRecord, *, value: Any, status: str, limitation: str) -> EvidenceRecord:
    return make_evidence_record(
        source=record.source,
        evidence_type=record.evidence_type,
        incident_id=record.incident_id,
        site=record.site,
        value=value,
        collection_status=status,
        limitation=limitation,
        observed_at=record.observed_at,
    )


def _evaluation_evidence_collector(mode: str, ticket_text: str | None):
    def collect(incident: Incident) -> list[EvidenceRecord]:
        records = collect_evidence(incident)
        updated = []
        for record in records:
            if mode == "tool_timeout" and record.source == "telemetry":
                updated.append(_replace_record(
                    record, value={"error_type": "TimeoutError"}, status="failure",
                    limitation="Synthetic evaluation timeout; no live tool was called.",
                ))
            elif mode == "conflict" and record.source == "telemetry":
                updated.append(_replace_record(
                    record,
                    value={"packet_loss": 0.0, "latency_ms": 20, "cpu_percent": 24,
                            "memory_percent": 35, "active_users": 187},
                    status="success",
                    limitation="Synthetic evaluation override; intentionally conflicts with alarm and ticket fixtures.",
                ))
            elif mode == "insufficient" and record.source in {"telemetry", "inventory"}:
                updated.append(_replace_record(
                    record, value={"error_type": "Unavailable"}, status="missing",
                    limitation="Synthetic evaluation source is unavailable for this low-evidence case.",
                ))
            else:
                updated.append(record)
        if ticket_text is not None:
            updated.append(make_evidence_record(
                source="evaluation_ticket_fixture",
                evidence_type="synthetic_ticket_context",
                incident_id=incident.incident_id,
                site=incident.site,
                value={"note": ticket_text},
                collection_status="success",
                limitation="Evaluation-only synthetic ticket context injected by the test harness; no ticket adapter exists.",
            ))
        return updated
    return collect


def _metric_checks(case: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    checks = []
    assessment = state["assessment"]
    actual_pairs = _actual_pairs(state)
    expected_pairs = _expected_pairs(case)

    def add(name: str, expected: Any, actual: Any, passed: bool):
        checks.append({"name": name, "expected": expected, "actual": actual, "passed": bool(passed)})

    add("correlation_pairs", sorted(expected_pairs), sorted(actual_pairs), expected_pairs == actual_pairs)
    dedup = state["alarm_deduplication"]
    expected_group_count = case.get("expected_correlation_group_count")
    if expected_group_count is not None:
        actual_group_count = len(state["alarm_correlation"].groups)
        add("correlation_group_count", expected_group_count, actual_group_count,
            expected_group_count == actual_group_count)
    expected_suppressed = case.get("expected_duplicate_suppressed")
    if expected_suppressed is not None:
        add("duplicate_suppressed_count", expected_suppressed, dedup.suppressed_count,
            expected_suppressed == dedup.suppressed_count)
        if expected_suppressed > 0:
            refs = [ref for group in dedup.duplicate_groups for ref in group.original_event_references]
            minimum_refs = expected_suppressed + len(dedup.duplicate_groups)
            add("duplicate_source_references_retained", minimum_refs, len(refs), len(refs) >= minimum_refs)
    expected_status = case.get("expected_assessment_status")
    if expected_status:
        add("assessment_status", expected_status, assessment.status, expected_status == assessment.status)
    if "expected_hypothesis_count" in case:
        actual = len(assessment.hypotheses)
        add("hypothesis_count", case["expected_hypothesis_count"], actual,
            actual == case["expected_hypothesis_count"])
    if "expected_conflict" in case:
        actual = bool(assessment.conflicts)
        add("conflict_exposed", case["expected_conflict"], actual,
            actual == case["expected_conflict"] and all(
                conflict.verification_status == "unverified_model_proposal"
                for conflict in assessment.conflicts
            ))
        evidence_by_id = {item.evidence_id: item for item in assessment.evidence}
        conflict_sources = {
            evidence_by_id[evidence_id].source
            for conflict in assessment.conflicts for evidence_id in conflict.evidence_ids
            if evidence_id in evidence_by_id
        }
        required_sources_present = {"telemetry", "evaluation_ticket_fixture"} <= conflict_sources
        add("conflict_cites_telemetry_and_ticket_context", True, required_sources_present,
            required_sources_present)
        next_step_present = bool(assessment.recommended_next_steps)
        add("conflict_has_discriminating_next_step", True, next_step_present, next_step_present)
    if "expected_path" in case:
        paths = [path.element_ids for impact in state["topology_analysis"].service_impacts
                 for path in impact.dependency_paths]
        actual = case["expected_path"] in paths
        add("declared_dependency_path", True, actual, actual)
        if case["id"] == "A":
            groups = state["alarm_correlation"].groups
            explained = bool(groups and groups[0].rule_id and groups[0].explanation)
            add("correlation_rule_explained", True, explained, explained)
            telemetry = next((item for item in assessment.evidence
                              if item.source == "telemetry" and item.collection_status == "success"), None)
            symptom_present = bool(telemetry and telemetry.value.get("latency_ms", 0) > 0)
            add("synthetic_service_symptom_evidence", True, symptom_present, symptom_present)
            valid_ids = {item.evidence_id for item in assessment.evidence
                         if item.collection_status == "success"}
            expected_support_ids = {
                item.evidence_id for item in assessment.evidence
                if item.source in {"phase2d_alarm_fixture", "telemetry"}
                and item.collection_status == "success"
            }
            supported = [item for item in assessment.hypotheses if item.supporting_evidence_ids]
            grounded = bool(supported and all(set(item.supporting_evidence_ids) <= valid_ids
                                              and set(item.supporting_evidence_ids) & expected_support_ids
                                              for item in supported))
            add("leading_hypothesis_has_successful_support_refs", True, grounded, grounded)
            ticket = any(item.source == "evaluation_ticket_fixture" for item in assessment.evidence)
            add("ticket_context_present_as_eval_injection", True, ticket, ticket)
    if "expected_service_impact_status" in case:
        impacts = state["topology_analysis"].service_impacts
        actual_statuses = sorted({impact.status for impact in impacts})
        actual_reason = sorted({impact.unknown_reason for impact in impacts if impact.unknown_reason})
        passed = case["expected_service_impact_status"] in actual_statuses
        if case.get("expected_service_impact_reason"):
            passed = passed and case["expected_service_impact_reason"] in actual_reason
        add("incomplete_topology_is_unknown", case["expected_service_impact_status"],
            {"statuses": actual_statuses, "unknown_reasons": actual_reason}, passed)
    if case["id"] == "D":
        actual = assessment.confidence < 0.5 and assessment.recommendation_type == "investigative"
        add("cautious_incomplete_topology_response", "confidence<0.5 and investigative recommendation",
            {"confidence": assessment.confidence, "recommendation_type": assessment.recommendation_type}, actual)
    if case["id"] == "G":
        actual = (assessment.status == "inconclusive" and not assessment.hypotheses
                  and assessment.recommendation_type == "investigative"
                  and bool(assessment.recommended_next_steps))
        add("low_evidence_stays_uncertain", True, actual, actual)
    approval_safe = (
        assessment.action_risk in {"LOW", "MEDIUM", "HIGH"}
        and not ((assessment.action_risk != "LOW" or assessment.recommendation_type == "operational")
                 and not assessment.human_approval_required)
    )
    add("recommendation_risk_and_approval_contract", True, approval_safe, approval_safe)
    return checks


def _run_one(case: dict[str, Any], *, mode: str, ticket_text: str | None,
             runtime: bool = True) -> dict[str, Any]:
    alarm_path = _scenario_path(case["alarm_fixture"])
    topology_path = _scenario_path(case["topology_fixture"])
    llm_mode = case.get("model_mode", "supported")
    if mode == "provider_unavailable":
        llm_mode = mode
    elif mode == "tool_timeout":
        llm_mode = "insufficient"

    incident = {
        "incident_id": f"EVAL-{case['id']}-{mode.upper()}",
        "site": "DEN-042", "technology": "5G", "severity": "SEV-2",
        "description": f"Synthetic evaluation scenario {case['id']}: {case['name']}.",
    }
    evidence_mode = ("tool_timeout" if case["id"] == "F" and mode == "tool_timeout"
                     else case.get("evidence_mode", "standard"))
    collector = _evaluation_evidence_collector(evidence_mode, ticket_text)
    started = perf_counter()
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(graph_module, "_ALARM_FIXTURE", alarm_path))
            stack.enter_context(patch.object(graph_module, "_TOPOLOGY_FIXTURE", topology_path))
            stack.enter_context(patch.object(graph_module, "collect_evidence", collector))
            graph = graph_module.build_graph(llm=EvaluationLLM(llm_mode))
            state = graph.invoke({"incident": incident})
    except Exception as exc:
        elapsed_ms = (perf_counter() - started) * 1000
        return {
            "run_id": f"{case['id']}-{mode}", "status": "failed",
            "checks": [{"name": "workflow_terminates_with_assessment", "expected": "assessment result",
                        "actual": {"error_type": type(exc).__name__}, "passed": False}],
            "counts": {"input_alarms": 0, "operational_representatives": 0,
                       "duplicates_suppressed": 0, "duplicate_suppression_rate": None,
                       "correlated_event_pairs_expected": len(_expected_pairs(case)),
                       "correlated_event_pairs_actual": 0, "correlated_group_count": 0},
            "assessment": {"status": None, "generation_status": None,
                           "uncalibrated_confidence": None, "confidence_interpretation": None,
                           "hypothesis_count": 0, "conflict_count": 0,
                           "hypotheses_with_valid_successful_support_refs": 0,
                           "material_claim_count": 0, "claims_with_valid_evidence_refs": 0,
                           "claims_without_valid_evidence_refs": 0,
                           "recommendation_type": None, "risk": None,
                           "human_approval_required": False, "semantic_diagnosis_quality_scored": False},
            "workflow": {"phase2_status": "graph_execution_failure",
                         "failed_or_missing_evidence_sources": [], "failed_evidence_sources": [],
                         "missing_evidence_sources": [], "error_type": type(exc).__name__,
                         "external_actions_executed": 0},
            "runtime_ms_observed_not_repeatable": round(elapsed_ms, 3) if runtime else None,
            "limitations": ["Graph raised before producing a terminal assessment; error type is reported without exception text."],
        }
    elapsed_ms = (perf_counter() - started) * 1000

    if state.get("phase2_status") != "success":
        # Component errors are an expected terminal outcome for future injected cases;
        # current labelled scenarios F inject source/provider failures, not pipeline faults.
        checks = [{"name": "phase2_analysis_completed", "expected": "success",
                   "actual": state.get("phase2_status"), "passed": False}]
    else:
        checks = _metric_checks(case, state)
    assessment = state["assessment"]
    evidence_by_id = {item.evidence_id: item for item in assessment.evidence}
    claims = [*assessment.findings, *assessment.hypotheses, *assessment.conflicts]
    grounded_claims = 0
    for claim in claims:
        if hasattr(claim, "evidence_ids"):
            refs = claim.evidence_ids
        else:
            refs = [*claim.supporting_evidence_ids, *claim.contradicting_evidence_ids]
        if refs and all(ref in evidence_by_id and evidence_by_id[ref].collection_status == "success" for ref in refs):
            grounded_claims += 1

    normalized_count = state.get("alarm_normalization").input_count if state.get("alarm_normalization") else 0
    representative_count = state.get("alarm_deduplication").operational_count if state.get("alarm_deduplication") else 0
    suppressed_count = state.get("alarm_deduplication").suppressed_count if state.get("alarm_deduplication") else 0
    failed_evidence = [item.source for item in assessment.evidence if item.collection_status == "failure"]
    missing_evidence = [item.source for item in assessment.evidence if item.collection_status == "missing"]
    failed_or_missing_evidence = [item.source for item in assessment.evidence
                                  if item.collection_status != "success"]
    expected_pairs = _expected_pairs(case)
    actual_pairs = _actual_pairs(state) if state.get("alarm_correlation") else set()
    check_passed = all(item["passed"] for item in checks)
    if mode == "tool_timeout":
        check_passed = check_passed and "telemetry" in failed_evidence and assessment.status == "inconclusive"
        checks.append({"name": "tool_timeout_is_visible", "expected": "telemetry failure retained",
                       "actual": {"failed_sources": failed_evidence, "assessment_status": assessment.status},
                       "passed": "telemetry" in failed_evidence and assessment.status == "inconclusive"})
    elif mode == "provider_unavailable":
        check_passed = check_passed and assessment.status == "inconclusive" and assessment.generation_status == "llm_failure"
        checks.append({"name": "provider_failure_terminates_inconclusively", "expected": "inconclusive/llm_failure",
                       "actual": {"status": assessment.status, "generation_status": assessment.generation_status},
                       "passed": assessment.status == "inconclusive" and assessment.generation_status == "llm_failure"})
    return {
        "run_id": f"{case['id']}-{mode}",
        "status": "passed" if check_passed else "failed",
        "checks": checks,
        "counts": {"input_alarms": normalized_count, "operational_representatives": representative_count,
                   "duplicates_suppressed": suppressed_count,
                   "duplicate_suppression_rate": suppressed_count / normalized_count if normalized_count else None,
                   "correlated_event_pairs_expected": len(expected_pairs),
                   "correlated_event_pairs_actual": len(actual_pairs),
                   "correlated_group_count": len(state["alarm_correlation"].groups)
                   if state.get("alarm_correlation") else 0},
        "assessment": {
            "status": assessment.status, "generation_status": assessment.generation_status,
            "uncalibrated_confidence": assessment.confidence,
            "confidence_interpretation": assessment.confidence_interpretation,
            "hypothesis_count": len(assessment.hypotheses), "conflict_count": len(assessment.conflicts),
            "hypotheses_with_valid_successful_support_refs": sum(
                bool(hypothesis.supporting_evidence_ids)
                and set(hypothesis.supporting_evidence_ids) <= {
                    item.evidence_id for item in assessment.evidence
                    if item.collection_status == "success"
                }
                for hypothesis in assessment.hypotheses
            ),
            "material_claim_count": len(claims), "claims_with_valid_evidence_refs": grounded_claims,
            "claims_without_valid_evidence_refs": len(claims) - grounded_claims,
            "recommendation_type": assessment.recommendation_type,
            "risk": assessment.action_risk, "human_approval_required": assessment.human_approval_required,
            "semantic_diagnosis_quality_scored": False,
        },
        "workflow": {"phase2_status": state.get("phase2_status"),
                     "failed_or_missing_evidence_sources": failed_or_missing_evidence,
                     "failed_evidence_sources": failed_evidence,
                     "missing_evidence_sources": missing_evidence,
                     "external_actions_executed": 0},
        "runtime_ms_observed_not_repeatable": round(elapsed_ms, 3) if runtime else None,
        "limitations": (["Ticket context is evaluation-only injected evidence; the graph has no ticket adapter."]
                        if ticket_text else []),
    }


def _pair_metrics(run_rows: list[dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, Any]:
    expected = set()
    predicted = set()
    for row in run_rows:
        case_id = row["run_id"].split("-", 1)[0]
        case = next(item for item in cases if item["id"] == case_id)
        expected.update((case_id, *pair) for pair in _expected_pairs(case))
        # Pair identities are included in checks for exact, auditable aggregation.
        check = next((item for item in row["checks"] if item["name"] == "correlation_pairs"), None)
        if check:
            predicted.update((case_id, *pair) for pair in check["actual"])
    true_positive = len(expected & predicted)
    false_positive = len(predicted - expected)
    false_negative = len(expected - predicted)
    return {
        "true_positive_pairs": true_positive, "false_positive_pairs": false_positive,
        "false_negative_pairs": false_negative,
        "pair_precision": true_positive / (true_positive + false_positive) if true_positive + false_positive else None,
        "pair_recall": true_positive / (true_positive + false_negative) if true_positive + false_negative else None,
        "interpretation": "Labelled synthetic case-pair checks only; not a general correlation accuracy estimate.",
    }


def run_evaluation(*, runtime: bool = True) -> dict[str, Any]:
    suite = json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))
    cases = suite["cases"]
    rows = []
    for case in cases:
        modes = case.get("subcases", ["standard"])
        for mode in modes:
            ticket_text = case.get("ticket_fixture")
            row = _run_one(case, mode=mode, ticket_text=ticket_text, runtime=runtime)
            row["scenario_id"] = case["id"]
            row["scenario_name"] = case["name"]
            rows.append(row)

    pair_metrics = _pair_metrics(rows, cases)
    alarms_in = sum(row["counts"]["input_alarms"] for row in rows)
    suppressed = sum(row["counts"]["duplicates_suppressed"] for row in rows)
    claim_count = sum(row["assessment"]["material_claim_count"] for row in rows)
    grounded_count = sum(row["assessment"]["claims_with_valid_evidence_refs"] for row in rows)
    ungrounded_count = sum(row["assessment"]["claims_without_valid_evidence_refs"] for row in rows)
    assessed_risky = sum(
        row["assessment"]["status"] is not None and (
            row["assessment"]["recommendation_type"] == "operational"
            or row["assessment"]["risk"] != "LOW"
        )
        for row in rows
    )
    unsafe_recs = sum(
        row["assessment"]["status"] is not None and (
        (row["assessment"]["recommendation_type"] == "operational"
         or row["assessment"]["risk"] != "LOW")
        and not row["assessment"]["human_approval_required"]
        )
        for row in rows
    )
    failed_checks = sum(not check["passed"] for row in rows for check in row["checks"])
    diagnosis_support_checks = [check for row in rows for check in row["checks"]
                                if check["name"] == "leading_hypothesis_has_successful_support_refs"]
    return {
        "suite_id": suite["suite_id"], "data_classification": suite["data_classification"],
        "status": "passed" if failed_checks == 0 else "failed",
        "scenario_count": len(cases), "incident_count": len(rows),
        "workflow_run_count": len(rows), "failed_check_count": failed_checks,
        "scenarios": rows,
        "metrics": {
            "alarm_counts": {"input": alarms_in,
                             "operational_representatives": sum(row["counts"]["operational_representatives"] for row in rows),
                             "suppressed": suppressed,
                             "duplicate_suppression_rate": suppressed / alarms_in if alarms_in else None,
                             "denominator_definition": "All normalized alarm fixture rows across workflow runs, including repeated scenario executions."},
            "correlation": {
                **pair_metrics,
                "expected_group_count": sum(
                    case.get("expected_correlation_group_count", 0)
                    * len(case.get("subcases", ["standard"])) for case in cases
                ),
                "actual_group_count": sum(row["counts"]["correlated_group_count"] for row in rows),
            },
            "evidence_grounding": {"material_claims": claim_count, "claims_with_valid_successful_evidence_refs": grounded_count,
                                    "claims_without_valid_successful_evidence_refs": ungrounded_count,
                                    "structural_reference_coverage": grounded_count / claim_count if claim_count else None,
                                    "semantic_claim_truth_scored": False},
            "diagnosis_support": {
                "expected_leading_hypothesis_support_checks": len(diagnosis_support_checks),
                "passed_expected_leading_hypothesis_support_checks": sum(
                    check["passed"] for check in diagnosis_support_checks
                ),
                "failed_expected_leading_hypothesis_support_checks": sum(
                    not check["passed"] for check in diagnosis_support_checks
                ),
                "semantic_diagnosis_quality_scored": False,
                "interpretation": "Case-specific deterministic checks that a leading hypothesis cites expected successful fixture evidence; not a judgment of diagnosis truth or general quality.",
            },
            "uncertainty": {"inconclusive_assessment_runs": sum(row["assessment"]["status"] == "inconclusive" for row in rows),
                            "low_confidence_or_missing_evidence_assertions": sum(
                                check["passed"] for row in rows for check in row["checks"]
                                if check["name"] in {"cautious_incomplete_topology_response", "low_evidence_stays_uncertain"}),
                            "assessment_confidence_is_uncalibrated": True},
            "reliability": {"terminal_assessments": sum(row["assessment"]["status"] is not None for row in rows),
                            "failed_or_missing_evidence_records": sum(len(row["workflow"]["failed_or_missing_evidence_sources"]) for row in rows),
                            "tool_error_records": sum(len(row["workflow"]["failed_evidence_sources"]) for row in rows),
                            "unavailable_evidence_records": sum(len(row["workflow"]["missing_evidence_sources"]) for row in rows),
                            "provider_failure_runs": sum(row["assessment"]["generation_status"] == "llm_failure" for row in rows),
                            "validation_failure_runs": sum(row["assessment"]["generation_status"] == "invalid_llm_output" for row in rows),
                            "workflow_completion_rate": sum(row["assessment"]["status"] is not None for row in rows) / len(rows) if rows else None,
                            "external_actions_executed": 0},
            "recommendation_safety": {"recommendation_count": sum(row["assessment"]["status"] is not None for row in rows),
                                      "recommendations_requiring_approval": assessed_risky,
                                      "unsafe_high_risk_or_operational_recommendations": unsafe_recs},
            "triage_runtime": {"measurements_ms": [row["runtime_ms_observed_not_repeatable"] for row in rows],
                               "is_repeatable_metric": False,
                               "is_real_operational_mttr": False},
        },
        "limitations": [
            "LLM responses are fixed offline test doubles; semantic diagnosis quality is not scored.",
            "Ticket evidence is injected by the evaluation harness because no ticket adapter is implemented.",
            "Runtime measurements vary by machine and run; deterministic scenario checks and counts are the comparable outputs.",
            "The seven synthetic scenarios are a test set, not evidence of production accuracy or operational savings.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline synthetic Agentic AI NOC evaluation suite.")
    parser.add_argument("--output", type=Path, help="also write the JSON report to this path")
    parser.add_argument("--no-runtime", action="store_true", help="omit machine-dependent runtime measurements")
    args = parser.parse_args(argv)
    report = run_evaluation(runtime=not args.no_runtime)
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
