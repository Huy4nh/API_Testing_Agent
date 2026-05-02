from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FinalReportFinding:
    severity: str
    title: str
    detail: str
    testcase_id: str | None = None
    operation_id: str | None = None
    method: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class FinalReportCaseSummary:
    testcase_id: str
    logical_case_name: str | None
    operation_id: str
    method: str
    path: str
    test_type: str | None

    expected_statuses: list[int] = field(default_factory=list)
    actual_status: int | None = None
    response_time_ms: float | None = None

    skipped: bool = False
    skip_reason: str | None = None
    network_error: str | None = None

    verdict: str = "unknown"
    summary_message: str = ""
    issues: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class FinalReportLinks:
    draft_report_json_path: str | None = None
    draft_report_md_path: str | None = None
    execution_report_json_path: str | None = None
    execution_report_md_path: str | None = None
    validation_report_json_path: str | None = None
    validation_report_md_path: str | None = None
    final_report_json_path: str | None = None
    final_report_md_path: str | None = None


@dataclass(frozen=True)
class FinalWorkflowSummary:
    run_id: str
    thread_id: str
    target_name: str

    original_request: str | None = None
    canonical_command: str | None = None
    understanding_explanation: str | None = None

    selected_target: str | None = None
    candidate_targets: list[str] = field(default_factory=list)
    target_selection_question: str | None = None

    feedback_history: list[str] = field(default_factory=list)
    approved: bool = True

    total_cases: int = 0
    executed_cases: int = 0
    skipped_cases: int = 0

    pass_cases: int = 0
    fail_cases: int = 0
    skip_cases_validation: int = 0
    error_cases: int = 0

    report_stage: str = "staged"
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))


@dataclass(frozen=True)
class FinalWorkflowReport:
    summary: FinalWorkflowSummary
    links: FinalReportLinks
    case_summaries: list[FinalReportCaseSummary] = field(default_factory=list)
    notable_findings: list[FinalReportFinding] = field(default_factory=list)