from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuntimeRequest:
    testcase_id: str
    logical_case_name: str
    target_name: str
    operation_id: str
    method: str
    path: str
    final_url: str
    final_headers: dict[str, str]
    final_query_params: dict[str, Any]
    final_json_body: Any | None
    expected_statuses: list[int]
    test_type: str
    skip: bool = False
    skip_reason: str | None = None

    # Nâng cấp mới
    planner_reason: str | None = None
    planner_confidence: float | None = None
    payload_source: str | None = None


@dataclass(frozen=True)
class ExecutionCaseResult:
    testcase_id: str
    logical_case_name: str
    target_name: str
    operation_id: str
    method: str
    path: str
    final_url: str
    final_headers: dict[str, str]
    final_query_params: dict[str, Any]
    final_json_body: Any | None
    expected_statuses: list[int]
    actual_status: int | None
    response_headers: dict[str, str]
    response_text: str | None
    response_json: Any | None
    response_time_ms: float
    network_error: str | None
    executed_at: str
    test_type: str
    skip: bool = False
    skip_reason: str | None = None

    # Nâng cấp mới
    planner_reason: str | None = None
    planner_confidence: float | None = None
    payload_source: str | None = None


@dataclass(frozen=True)
class ExecutionBatchResult:
    thread_id: str
    target_name: str
    total_cases: int
    executed_cases: int
    skipped_cases: int
    results: list[ExecutionCaseResult] = field(default_factory=list)