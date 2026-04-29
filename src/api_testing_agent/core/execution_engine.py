from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx

from api_testing_agent.core.execution_log_formatter import ExecutionLogFormatter
from api_testing_agent.core.execution_models import (
    ExecutionBatchResult,
    ExecutionCaseResult,
    RuntimeRequest,
)
from api_testing_agent.core.request_runtime_builder import RequestRuntimeBuilder


class ExecutionEngine:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        runtime_builder: RequestRuntimeBuilder | None = None,
        log_formatter: ExecutionLogFormatter | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._runtime_builder = runtime_builder or RequestRuntimeBuilder()
        self._log_formatter = log_formatter or ExecutionLogFormatter()
        self._transport = transport

    def execute_approved_draft(
        self,
        *,
        thread_id: str,
        target: Any,
        target_name: str,
        operation_contexts: list[dict[str, Any]],
        draft_groups: list[dict[str, Any]],
    ) -> ExecutionBatchResult:
        operation_index = self._build_operation_index(operation_contexts)

        results: list[ExecutionCaseResult] = []
        total_cases = 0
        executed_cases = 0
        skipped_cases = 0

        for group in draft_groups:
            operation_context = self._resolve_operation_context(group, operation_index)
            if operation_context is None:
                continue

            for case_index, case in enumerate(group.get("cases", []), start=1):
                total_cases += 1

                runtime_request = self._runtime_builder.build(
                    target=target,
                    target_name=target_name,
                    operation_context=operation_context,
                    case=case,
                    case_index=case_index,
                )

                if runtime_request.skip:
                    skipped_cases += 1
                    results.append(self._build_skipped_result(runtime_request))
                    continue

                executed_cases += 1
                results.append(self.execute_runtime_request(runtime_request))

        return ExecutionBatchResult(
            thread_id=thread_id,
            target_name=target_name,
            total_cases=total_cases,
            executed_cases=executed_cases,
            skipped_cases=skipped_cases,
            results=results,
        )

    def execute_runtime_request(self, runtime_request: RuntimeRequest) -> ExecutionCaseResult:
        started = time.perf_counter()
        executed_at = datetime.now(timezone.utc).isoformat()

        raw_headers = dict(runtime_request.final_headers)

        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                follow_redirects=True,
                transport=self._transport,
            ) as client:
                response = client.request(
                    method=runtime_request.method,
                    url=runtime_request.final_url,
                    params=runtime_request.final_query_params,
                    headers=raw_headers,
                    json=runtime_request.final_json_body,
                )

            elapsed_ms = (time.perf_counter() - started) * 1000

            parsed_json: Any | None = None
            try:
                parsed_json = response.json()
            except Exception:
                parsed_json = None

            return ExecutionCaseResult(
                testcase_id=runtime_request.testcase_id,
                logical_case_name=runtime_request.logical_case_name,
                target_name=runtime_request.target_name,
                operation_id=runtime_request.operation_id,
                method=runtime_request.method,
                path=runtime_request.path,
                final_url=runtime_request.final_url,
                final_headers=self._log_formatter.sanitize_headers(raw_headers),
                final_query_params=runtime_request.final_query_params,
                final_json_body=runtime_request.final_json_body,
                expected_statuses=runtime_request.expected_statuses,
                actual_status=response.status_code,
                response_headers=dict(response.headers),
                response_text=response.text,
                response_json=parsed_json,
                response_time_ms=elapsed_ms,
                network_error=None,
                executed_at=executed_at,
                test_type=runtime_request.test_type,
                skip=False,
                skip_reason=None,
            )

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000

            return ExecutionCaseResult(
                testcase_id=runtime_request.testcase_id,
                logical_case_name=runtime_request.logical_case_name,
                target_name=runtime_request.target_name,
                operation_id=runtime_request.operation_id,
                method=runtime_request.method,
                path=runtime_request.path,
                final_url=runtime_request.final_url,
                final_headers=self._log_formatter.sanitize_headers(raw_headers),
                final_query_params=runtime_request.final_query_params,
                final_json_body=runtime_request.final_json_body,
                expected_statuses=runtime_request.expected_statuses,
                actual_status=None,
                response_headers={},
                response_text=None,
                response_json=None,
                response_time_ms=elapsed_ms,
                network_error=str(exc),
                executed_at=executed_at,
                test_type=runtime_request.test_type,
                skip=False,
                skip_reason=None,
            )

    def _build_skipped_result(self, runtime_request: RuntimeRequest) -> ExecutionCaseResult:
        return ExecutionCaseResult(
            testcase_id=runtime_request.testcase_id,
            logical_case_name=runtime_request.logical_case_name,
            target_name=runtime_request.target_name,
            operation_id=runtime_request.operation_id,
            method=runtime_request.method,
            path=runtime_request.path,
            final_url=runtime_request.final_url,
            final_headers=self._log_formatter.sanitize_headers(runtime_request.final_headers),
            final_query_params=runtime_request.final_query_params,
            final_json_body=runtime_request.final_json_body,
            expected_statuses=runtime_request.expected_statuses,
            actual_status=None,
            response_headers={},
            response_text=None,
            response_json=None,
            response_time_ms=0.0,
            network_error=None,
            executed_at=datetime.now(timezone.utc).isoformat(),
            test_type=runtime_request.test_type,
            skip=True,
            skip_reason=runtime_request.skip_reason,
        )

    def _build_operation_index(
        self,
        operation_contexts: list[dict[str, Any]],
    ) -> dict[tuple[str, str, str], dict[str, Any]]:
        index: dict[tuple[str, str, str], dict[str, Any]] = {}

        for item in operation_contexts:
            operation_id = str(item.get("operation_id", ""))
            method = str(item.get("method", "")).upper()
            path = str(item.get("path", ""))

            index[(operation_id, method, path)] = item

        return index

    def _resolve_operation_context(
        self,
        group: dict[str, Any],
        operation_index: dict[tuple[str, str, str], dict[str, Any]],
    ) -> dict[str, Any] | None:
        operation_id = str(group.get("operation_id", ""))
        method = str(group.get("method", "")).upper()
        path = str(group.get("path", ""))

        return operation_index.get((operation_id, method, path))