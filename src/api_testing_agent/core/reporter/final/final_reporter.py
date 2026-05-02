from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from api_testing_agent.core.reporter.final.final_report_models import (
    FinalReportCaseSummary,
    FinalReportFinding,
    FinalReportLinks,
    FinalWorkflowReport,
    FinalWorkflowSummary,
)
from api_testing_agent.logging_config import bind_logger, get_logger


class FinalWorkflowReporter:
    def __init__(self, output_dir: str) -> None:
        self._output_dir = Path(output_dir)
        self._logger = get_logger(__name__)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def write_staged(
        self,
        *,
        review_payload: dict[str, Any],
        execution_batch_result: Any,
        validation_batch_result: Any,
        original_request: str | None = None,
        review_trace: dict[str, Any] | None = None,
    ) -> FinalWorkflowReport:
        thread_id = str(self._safe_get(execution_batch_result, "thread_id", review_payload.get("thread_id", "")))
        target_name = str(self._safe_get(execution_batch_result, "target_name", review_payload.get("target_name", "")))

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="final_report_write_staged",
        )
        logger.info("Building staged final workflow report.")

        run_id = uuid4().hex

        case_summaries = self._build_case_summaries(
            execution_batch_result=execution_batch_result,
            validation_batch_result=validation_batch_result,
        )
        findings = self._build_notable_findings(
            execution_batch_result=execution_batch_result,
            validation_batch_result=validation_batch_result,
        )

        links = FinalReportLinks(
            draft_report_json_path=self._safe_str(review_payload.get("draft_report_json_path")),
            draft_report_md_path=self._safe_str(review_payload.get("draft_report_md_path")),
            execution_report_json_path=self._safe_str(review_payload.get("execution_report_json_path")),
            execution_report_md_path=self._safe_str(review_payload.get("execution_report_md_path")),
            validation_report_json_path=self._safe_str(review_payload.get("validation_report_json_path")),
            validation_report_md_path=self._safe_str(review_payload.get("validation_report_md_path")),
        )

        summary = FinalWorkflowSummary(
            run_id=run_id,
            thread_id=thread_id,
            target_name=target_name,
            original_request=original_request,
            canonical_command=self._safe_str(review_payload.get("canonical_command")),
            understanding_explanation=self._safe_str(review_payload.get("understanding_explanation")),
            selected_target=target_name,
            candidate_targets=list((review_trace or {}).get("candidate_targets", []) or []),
            target_selection_question=self._safe_str((review_trace or {}).get("target_selection_question")),
            feedback_history=list((review_trace or {}).get("feedback_history", []) or []),
            approved=True,
            total_cases=int(self._safe_get(execution_batch_result, "total_cases", 0) or 0),
            executed_cases=int(self._safe_get(execution_batch_result, "executed_cases", 0) or 0),
            skipped_cases=int(self._safe_get(execution_batch_result, "skipped_cases", 0) or 0),
            pass_cases=int(self._safe_get(validation_batch_result, "pass_cases", 0) or 0),
            fail_cases=int(self._safe_get(validation_batch_result, "fail_cases", 0) or 0),
            skip_cases_validation=int(self._safe_get(validation_batch_result, "skip_cases", 0) or 0),
            error_cases=int(self._safe_get(validation_batch_result, "error_cases", 0) or 0),
            report_stage="staged",
        )

        report = FinalWorkflowReport(
            summary=summary,
            links=links,
            case_summaries=case_summaries,
            notable_findings=findings,
        )

        stage_dir = self._output_dir / "_staging" / "final_runs" / target_name / thread_id
        stage_dir.mkdir(parents=True, exist_ok=True)

        json_path = stage_dir / "final_summary.json"
        md_path = stage_dir / "final_summary.md"

        links = replace(
            links,
            final_report_json_path=str(json_path),
            final_report_md_path=str(md_path),
        )
        report = FinalWorkflowReport(
            summary=summary,
            links=links,
            case_summaries=case_summaries,
            notable_findings=findings,
        )

        json_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(self._build_markdown(report), encoding="utf-8")

        logger.info("Staged final workflow report written successfully.")
        return report

    def finalize_from_staged(self, report: FinalWorkflowReport) -> FinalWorkflowReport:
        summary = report.summary
        links = report.links

        logger = bind_logger(
            self._logger,
            thread_id=summary.thread_id,
            target_name=summary.target_name,
            payload_source="final_report_finalize_from_staged",
        )
        logger.info("Finalizing staged final report.")

        staged_json = Path(str(links.final_report_json_path))
        staged_md = Path(str(links.final_report_md_path))

        final_dir = self._output_dir / "final_runs" / summary.target_name / summary.thread_id
        final_dir.mkdir(parents=True, exist_ok=True)

        final_json = final_dir / "final_summary.json"
        final_md = final_dir / "final_summary.md"

        if staged_json.exists():
            final_json.write_text(staged_json.read_text(encoding="utf-8"), encoding="utf-8")
        if staged_md.exists():
            final_md.write_text(staged_md.read_text(encoding="utf-8"), encoding="utf-8")

        finalized_links = replace(
            links,
            final_report_json_path=str(final_json),
            final_report_md_path=str(final_md),
        )
        finalized_summary = replace(summary, report_stage="finalized")

        finalized_report = FinalWorkflowReport(
            summary=finalized_summary,
            links=finalized_links,
            case_summaries=report.case_summaries,
            notable_findings=report.notable_findings,
        )

        final_json.write_text(json.dumps(asdict(finalized_report), ensure_ascii=False, indent=2), encoding="utf-8")
        final_md.write_text(self._build_markdown(finalized_report), encoding="utf-8")

        logger.info("Final report finalized successfully.")
        return finalized_report

    def _build_case_summaries(
        self,
        *,
        execution_batch_result: Any,
        validation_batch_result: Any,
    ) -> list[FinalReportCaseSummary]:
        execution_results = list(self._safe_get(execution_batch_result, "results", []) or [])
        validation_results = list(self._safe_get(validation_batch_result, "results", []) or [])

        validation_map: dict[str, Any] = {}
        for item in validation_results:
            testcase_id = str(self._safe_get(item, "testcase_id", ""))
            if testcase_id:
                validation_map[testcase_id] = item

        summaries: list[FinalReportCaseSummary] = []

        for execution_item in execution_results:
            testcase_id = str(self._safe_get(execution_item, "testcase_id", ""))
            validation_item = validation_map.get(testcase_id)

            expected_statuses = list(self._safe_get(execution_item, "expected_statuses", []) or [])
            issues = self._normalize_issues(self._safe_get(validation_item, "issues", []) if validation_item else [])

            summaries.append(
                FinalReportCaseSummary(
                    testcase_id=testcase_id,
                    logical_case_name=self._safe_str(self._safe_get(execution_item, "logical_case_name")),
                    operation_id=str(self._safe_get(execution_item, "operation_id", "")),
                    method=str(self._safe_get(execution_item, "method", "")),
                    path=str(self._safe_get(execution_item, "path", "")),
                    test_type=self._safe_str(self._safe_get(execution_item, "test_type")),
                    expected_statuses=[int(item) for item in expected_statuses if self._is_int_like(item)],
                    actual_status=self._to_int_or_none(self._safe_get(execution_item, "actual_status")),
                    response_time_ms=self._to_float_or_none(self._safe_get(execution_item, "response_time_ms")),
                    skipped=bool(self._safe_get(execution_item, "skip", False)),
                    skip_reason=self._safe_str(self._safe_get(execution_item, "skip_reason")),
                    network_error=self._safe_str(self._safe_get(execution_item, "network_error")),
                    verdict=str(self._safe_get(validation_item, "verdict", "unknown")) if validation_item else "unknown",
                    summary_message=str(self._safe_get(validation_item, "summary_message", "")) if validation_item else "",
                    issues=issues,
                )
            )

        return summaries

    def _build_notable_findings(self, *, execution_batch_result: Any, validation_batch_result: Any) -> list[FinalReportFinding]:
        findings: list[FinalReportFinding] = []

        execution_results = list(self._safe_get(execution_batch_result, "results", []) or [])
        validation_results = list(self._safe_get(validation_batch_result, "results", []) or [])

        validation_map: dict[str, Any] = {}
        for item in validation_results:
            testcase_id = str(self._safe_get(item, "testcase_id", ""))
            if testcase_id:
                validation_map[testcase_id] = item

        for execution_item in execution_results:
            testcase_id = str(self._safe_get(execution_item, "testcase_id", ""))
            validation_item = validation_map.get(testcase_id)

            verdict = str(self._safe_get(validation_item, "verdict", "")).lower() if validation_item else ""
            if verdict in {"fail", "error"}:
                findings.append(
                    FinalReportFinding(
                        severity="high",
                        title="Case fail/error",
                        detail=str(self._safe_get(validation_item, "summary_message", "Validation failed.")),
                        testcase_id=testcase_id,
                        operation_id=self._safe_str(self._safe_get(execution_item, "operation_id")),
                        method=self._safe_str(self._safe_get(execution_item, "method")),
                        path=self._safe_str(self._safe_get(execution_item, "path")),
                    )
                )

        for execution_item in execution_results:
            elapsed = self._to_float_or_none(self._safe_get(execution_item, "response_time_ms"))
            if elapsed is not None and elapsed >= 5000:
                findings.append(
                    FinalReportFinding(
                        severity="medium",
                        title="Slow response",
                        detail=f"Case có response_time_ms={elapsed:.2f}, vượt ngưỡng cảnh báo 5000 ms.",
                        testcase_id=self._safe_str(self._safe_get(execution_item, "testcase_id")),
                        operation_id=self._safe_str(self._safe_get(execution_item, "operation_id")),
                        method=self._safe_str(self._safe_get(execution_item, "method")),
                        path=self._safe_str(self._safe_get(execution_item, "path")),
                    )
                )

        skip_count = int(self._safe_get(validation_batch_result, "skip_cases", 0) or 0)
        if skip_count > 0:
            findings.append(
                FinalReportFinding(
                    severity="info",
                    title="Skipped cases",
                    detail=f"Có {skip_count} case bị skip vì không áp dụng theo spec/runtime.",
                )
            )

        return findings

    def _build_markdown(self, report: FinalWorkflowReport) -> str:
        summary = report.summary
        links = report.links

        lines: list[str] = []
        lines.append("# Final Workflow Report")
        lines.append("")
        lines.append(f"- Run ID: `{summary.run_id}`")
        lines.append(f"- Thread ID: `{summary.thread_id}`")
        lines.append(f"- Target: `{summary.target_name}`")
        lines.append(f"- Report stage: `{summary.report_stage}`")
        lines.append("")
        lines.append("## Request Trace")
        if summary.original_request:
            lines.append(f"- Original request: {summary.original_request}")
        if summary.selected_target:
            lines.append(f"- Selected target: `{summary.selected_target}`")
        if summary.candidate_targets:
            lines.append(f"- Candidate targets: `{summary.candidate_targets}`")
        if summary.target_selection_question:
            lines.append(f"- Target question: {summary.target_selection_question}")
        if summary.canonical_command:
            lines.append(f"- Canonical command: `{summary.canonical_command}`")
        if summary.understanding_explanation:
            lines.append(f"- Understanding explanation: {summary.understanding_explanation}")
        lines.append("")
        lines.append("## Review Trace")
        if summary.feedback_history:
            lines.append("- Feedback history:")
            for idx, item in enumerate(summary.feedback_history, start=1):
                lines.append(f"  - {idx}. {item}")
        else:
            lines.append("- No feedback history.")
        lines.append("")
        lines.append("## Execution Summary")
        lines.append(f"- Total cases: `{summary.total_cases}`")
        lines.append(f"- Executed cases: `{summary.executed_cases}`")
        lines.append(f"- Skipped cases (execution): `{summary.skipped_cases}`")
        lines.append("")
        lines.append("## Validation Summary")
        lines.append(f"- Pass: `{summary.pass_cases}`")
        lines.append(f"- Fail: `{summary.fail_cases}`")
        lines.append(f"- Skip: `{summary.skip_cases_validation}`")
        lines.append(f"- Error: `{summary.error_cases}`")
        lines.append("")
        lines.append("## Notable Findings")
        if report.notable_findings:
            for finding in report.notable_findings:
                lines.append(f"- [{finding.severity.upper()}] {finding.title}: {finding.detail}")
        else:
            lines.append("- Không có finding nổi bật.")
        lines.append("")
        lines.append("## Linked Reports")
        if links.draft_report_md_path:
            lines.append(f"- Draft report: `{links.draft_report_md_path}`")
        if links.execution_report_md_path:
            lines.append(f"- Execution report: `{links.execution_report_md_path}`")
        if links.validation_report_md_path:
            lines.append(f"- Validation report: `{links.validation_report_md_path}`")
        lines.append("")
        lines.append("## Case Summaries")
        if not report.case_summaries:
            lines.append("- Không có case nào trong final summary.")
            return "\n".join(lines)

        for index, case in enumerate(report.case_summaries, start=1):
            lines.append(f"### {index}. {case.method} {case.path}")
            if case.logical_case_name:
                lines.append(f"- Logical case: {case.logical_case_name}")
            if case.test_type:
                lines.append(f"- Test type: `{case.test_type}`")
            if case.expected_statuses:
                lines.append(f"- Expected statuses: `{case.expected_statuses}`")
            if case.actual_status is not None:
                lines.append(f"- Actual status: `{case.actual_status}`")
            if case.response_time_ms is not None:
                lines.append(f"- Response time: `{case.response_time_ms:.2f} ms`")
            lines.append(f"- Verdict: `{case.verdict}`")
            if case.skipped:
                lines.append("- Skipped: `True`")
            if case.skip_reason:
                lines.append(f"- Skip reason: {case.skip_reason}")
            if case.network_error:
                lines.append(f"- Network error: {case.network_error}")
            if case.summary_message:
                lines.append(f"- Summary: {case.summary_message}")
            if case.issues:
                lines.append("- Issues:")
                for issue in case.issues:
                    code = str(issue.get("code", "UNKNOWN"))
                    message = str(issue.get("message", ""))
                    field = issue.get("field")
                    lines.append(f"  - [{code}] {message}" + (f" (field={field})" if field else ""))
            lines.append("")
        return "\n".join(lines)

    def _normalize_issues(self, issues: Any) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in list(issues or []):
            if isinstance(item, dict):
                normalized.append(item)
            else:
                normalized.append(
                    {
                        "code": self._safe_str(self._safe_get(item, "code")) or "UNKNOWN",
                        "message": self._safe_str(self._safe_get(item, "message")) or str(item),
                        "field": self._safe_str(self._safe_get(item, "field")),
                    }
                )
        return normalized

    def _safe_get(self, source: Any, key: str, default: Any = None) -> Any:
        if source is None:
            return default
        if isinstance(source, dict):
            return source.get(key, default)
        return getattr(source, key, default)

    def _safe_str(self, value: Any) -> str | None:
        return None if value is None else str(value)

    def _to_int_or_none(self, value: Any) -> int | None:
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None

    def _to_float_or_none(self, value: Any) -> float | None:
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    def _is_int_like(self, value: Any) -> bool:
        try:
            int(value)
            return True
        except (TypeError, ValueError):
            return False