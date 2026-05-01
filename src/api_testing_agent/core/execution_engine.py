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
from api_testing_agent.core.unknown_output_description_service import (
    UnknownOutputDescriptionService,
)
from api_testing_agent.logging_config import bind_logger, get_logger


class ExecutionEngine:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        runtime_builder: RequestRuntimeBuilder | None = None,
        log_formatter: ExecutionLogFormatter | None = None,
        transport: httpx.BaseTransport | None = None,
        unknown_output_description_service: UnknownOutputDescriptionService | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._runtime_builder = runtime_builder or RequestRuntimeBuilder()
        self._log_formatter = log_formatter or ExecutionLogFormatter()
        self._transport = transport
        self._unknown_output_description_service = unknown_output_description_service
        self._logger = get_logger(__name__)

        self._logger.info(
            f"Initialized ExecutionEngine. timeout_seconds={self._timeout_seconds}",
            extra={"payload_source": "execution_engine_init"},
        )

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

        batch_logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="execution_batch",
        )
        batch_logger.info("Starting approved draft execution.")

        results: list[ExecutionCaseResult] = []
        total_cases = 0
        executed_cases = 0
        skipped_cases = 0

        for group in draft_groups:
            operation_context = self._resolve_operation_context(group, operation_index)
            if operation_context is None:
                batch_logger.warning(
                    "Could not resolve operation context for draft group.",
                    extra={
                        "operation_id": str(group.get("operation_id", "-")),
                    },
                )
                continue

            for case_index, case in enumerate(group.get("cases", []), start=1):
                total_cases += 1

                batch_logger.info(
                    "Preparing runtime request for case.",
                    extra={
                        "operation_id": str(operation_context.get("operation_id", "-")),
                        "testcase_id": str(
                            case.get("testcase_id")
                            or case.get("id")
                            or f"case_{case_index}"
                        ),
                    },
                )

                runtime_request = self._runtime_builder.build(
                    target=target,
                    target_name=target_name,
                    operation_context=operation_context,
                    case=case,
                    case_index=case_index,
                )

                if runtime_request.skip:
                    skipped_cases += 1
                    case_logger = bind_logger(
                        self._logger,
                        thread_id=thread_id,
                        target_name=target_name,
                        operation_id=runtime_request.operation_id,
                        testcase_id=runtime_request.testcase_id,
                        payload_source=runtime_request.payload_source or "-",
                    )
                    case_logger.info("Skipping runtime request.")
                    results.append(self._build_skipped_result(runtime_request))
                    continue

                executed_cases += 1
                results.append(
                    self.execute_runtime_request(
                        runtime_request=runtime_request,
                        thread_id=thread_id,
                    )
                )

        batch_logger.info(
            f"Execution batch finished. total_cases={total_cases}, executed_cases={executed_cases}, skipped_cases={skipped_cases}"
        )

        return ExecutionBatchResult(
            thread_id=thread_id,
            target_name=target_name,
            total_cases=total_cases,
            executed_cases=executed_cases,
            skipped_cases=skipped_cases,
            results=results,
        )

    def execute_runtime_request(
        self,
        runtime_request: RuntimeRequest,
        thread_id: str = "-",
    ) -> ExecutionCaseResult:
        started = time.perf_counter()
        executed_at = datetime.now(timezone.utc).isoformat()

        raw_headers = dict(runtime_request.final_headers)

        case_logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=runtime_request.target_name,
            operation_id=runtime_request.operation_id,
            testcase_id=runtime_request.testcase_id,
            payload_source=runtime_request.payload_source or "-",
        )

        case_logger.info("Sending HTTP request.")

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

            response_json, response_text = self._extract_response_payload(
                response=response,
                case_logger=case_logger,
            )

            case_logger.info(
                f"Received HTTP response status={response.status_code} time_ms={elapsed_ms:.2f}"
            )

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
                response_text=response_text,
                response_json=response_json,
                response_time_ms=elapsed_ms,
                network_error=None,
                executed_at=executed_at,
                test_type=runtime_request.test_type,
                skip=False,
                skip_reason=None,
                planner_reason=runtime_request.planner_reason,
                planner_confidence=runtime_request.planner_confidence,
                payload_source=runtime_request.payload_source,
            )

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            case_logger.exception("Runtime request failed with exception.")

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
                planner_reason=runtime_request.planner_reason,
                planner_confidence=runtime_request.planner_confidence,
                payload_source=runtime_request.payload_source,
            )

    def _extract_response_payload(
        self,
        response: httpx.Response,
        case_logger=None,
    ) -> tuple[Any | None, str | None]:
        response_headers = dict(response.headers)
        content_type = str(response_headers.get("content-type", "")).lower().strip()
        raw_bytes = response.content
        status_code = response.status_code

        if self._looks_like_json_content_type(content_type):
            if case_logger is not None:
                case_logger.info("Response detected as JSON content type.")
            try:
                return response.json(), None
            except Exception:
                if case_logger is not None:
                    case_logger.warning("JSON response parsing failed. Falling back to safe text decode.")
                return None, self._safe_decode_text(raw_bytes)

        if self._looks_like_known_binary_content_type(content_type) or self._looks_like_known_binary_bytes(raw_bytes):
            if case_logger is not None:
                case_logger.info("Response detected as known binary payload.")
            return None, self._binary_summary(
                content_type=content_type,
                raw_bytes=raw_bytes,
            )

        if self._looks_like_known_text_content_type(content_type):
            if case_logger is not None:
                case_logger.info("Response detected as known text payload.")
            return None, self._safe_decode_text(raw_bytes)

        if 200 <= status_code < 300 and raw_bytes:
            if self._unknown_output_description_service is not None:
                if case_logger is not None:
                    case_logger.info("Response type unknown but successful. Delegating to UnknownOutputDescriptionService.")
                ai_summary = self._unknown_output_description_service.describe(
                    status_code=status_code,
                    headers=response_headers,
                    raw_bytes=raw_bytes,
                )
                return None, ai_summary

        if case_logger is not None:
            case_logger.info("Response type not confidently identified. Falling back to safe text decode.")
        return None, self._safe_decode_text(raw_bytes)

    def _looks_like_json_content_type(self, content_type: str) -> bool:
        if not content_type:
            return False

        return (
            "application/json" in content_type
            or content_type.endswith("+json")
        )

    def _looks_like_known_text_content_type(self, content_type: str) -> bool:
        if not content_type:
            return False

        if content_type.startswith("text/"):
            return True

        known_text_like = (
            "application/xml",
            "text/xml",
            "application/javascript",
            "application/x-www-form-urlencoded",
            "application/graphql",
            "application/yaml",
            "application/x-yaml",
        )

        for item in known_text_like:
            if item in content_type:
                return True

        return False

    def _looks_like_known_binary_content_type(self, content_type: str) -> bool:
        if not content_type:
            return False

        binary_prefixes = (
            "image/",
            "audio/",
            "video/",
            "font/",
        )

        binary_exact_or_contains = (
            "application/octet-stream",
            "application/pdf",
            "application/zip",
            "application/x-zip-compressed",
            "application/vnd",
            "multipart/",
        )

        if content_type.startswith(binary_prefixes):
            return True

        for item in binary_exact_or_contains:
            if item in content_type:
                return True

        return False

    def _looks_like_known_binary_bytes(self, raw_bytes: bytes) -> bool:
        if not raw_bytes:
            return False

        if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return True

        if raw_bytes.startswith(b"\xff\xd8\xff"):
            return True

        if raw_bytes.startswith((b"GIF87a", b"GIF89a")):
            return True

        if raw_bytes.startswith(b"%PDF"):
            return True

        if b"\x00" in raw_bytes[:1024]:
            return True

        return False

    def _binary_summary(self, *, content_type: str, raw_bytes: bytes) -> str:
        safe_type = content_type or "unknown"
        return f"<binary response omitted: content_type={safe_type}, size_bytes={len(raw_bytes)}>"

    def _safe_decode_text(self, raw_bytes: bytes) -> str:
        if not raw_bytes:
            return ""

        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return raw_bytes.decode("utf-8", errors="replace")

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
            planner_reason=runtime_request.planner_reason,
            planner_confidence=runtime_request.planner_confidence,
            payload_source=runtime_request.payload_source,
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