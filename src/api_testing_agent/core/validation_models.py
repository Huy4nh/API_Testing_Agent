from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(_json_safe(item) for item in value)
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    return value


class ValidationVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    level: str = "error"
    path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "level": self.level,
            "path": self.path,
            "details": _json_safe(self.details),
        }


@dataclass(frozen=True)
class ValidationCaseResult:
    testcase_id: str | None = None
    logical_case_name: str | None = None
    target_name: str | None = None
    operation_id: str | None = None
    method: str | None = None
    path: str | None = None
    final_url: str | None = None
    test_type: str | None = None

    skip: bool = False
    skip_reason: str | None = None
    network_error: str | None = None

    expected_statuses: list[int] = field(default_factory=list)
    actual_status: int | None = None

    status_check_passed: bool | None = None
    schema_check_passed: bool | None = None
    required_fields_check_passed: bool | None = None

    expected_required_fields: list[str] = field(default_factory=list)
    missing_required_fields: list[str] = field(default_factory=list)

    response_time_ms: float | None = None
    payload_source: str | None = None
    planner_reason: str | None = None
    planner_confidence: float | None = None

    verdict: ValidationVerdict = ValidationVerdict.FAIL
    summary_message: str = ""
    issues: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "testcase_id": self.testcase_id,
            "logical_case_name": self.logical_case_name,
            "target_name": self.target_name,
            "operation_id": self.operation_id,
            "method": self.method,
            "path": self.path,
            "final_url": self.final_url,
            "test_type": self.test_type,
            "skip": self.skip,
            "skip_reason": self.skip_reason,
            "network_error": self.network_error,
            "expected_statuses": self.expected_statuses,
            "actual_status": self.actual_status,
            "status_check_passed": self.status_check_passed,
            "schema_check_passed": self.schema_check_passed,
            "required_fields_check_passed": self.required_fields_check_passed,
            "expected_required_fields": self.expected_required_fields,
            "missing_required_fields": self.missing_required_fields,
            "response_time_ms": self.response_time_ms,
            "payload_source": self.payload_source,
            "planner_reason": self.planner_reason,
            "planner_confidence": self.planner_confidence,
            "verdict": self.verdict.value,
            "summary_message": self.summary_message,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class ValidationBatchResult:
    thread_id: str | None = None
    target_name: str | None = None

    total_cases: int = 0
    validated_cases: int = 0
    pass_cases: int = 0
    fail_cases: int = 0
    skip_cases: int = 0
    error_cases: int = 0

    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    results: list[ValidationCaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "target_name": self.target_name,
            "total_cases": self.total_cases,
            "validated_cases": self.validated_cases,
            "pass_cases": self.pass_cases,
            "fail_cases": self.fail_cases,
            "skip_cases": self.skip_cases,
            "error_cases": self.error_cases,
            "generated_at": self.generated_at,
            "results": [result.to_dict() for result in self.results],
        }