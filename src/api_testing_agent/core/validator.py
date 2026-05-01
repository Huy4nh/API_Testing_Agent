from __future__ import annotations

import logging
from typing import Any, Callable, cast

from api_testing_agent.core.validation_models import (
    ValidationBatchResult,
    ValidationCaseResult,
    ValidationIssue,
    ValidationVerdict,
)

try:
    from api_testing_agent.logging_config import bind_logger as _project_bind_logger
    from api_testing_agent.logging_config import get_logger as _project_get_logger
except Exception:  # pragma: no cover
    _project_bind_logger = None
    _project_get_logger = None


def get_logger(name: str) -> Any:
    if _project_get_logger is not None:
        return _project_get_logger(name)
    return logging.getLogger(name)


def bind_logger(logger: Any, **context: Any) -> Any:
    if _project_bind_logger is not None:
        return _project_bind_logger(logger, **context)
    return logger


_MISSING = object()


class Validator:
    def __init__(self) -> None:
        self._logger = get_logger(__name__)

    def validate_batch(self, execution_batch_result: Any) -> ValidationBatchResult:
        thread_id = self._get_first(
            execution_batch_result,
            ["thread_id", "batch.thread_id"],
            default=None,
        )
        target_name = self._get_first(
            execution_batch_result,
            ["target_name", "batch.target_name"],
            default=None,
        )

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
        )
        logger.info("Starting validation batch.")

        raw_results = self._get_first(
            execution_batch_result,
            ["results", "execution_results", "batch.results"],
            default=[],
        )
        if not isinstance(raw_results, list):
            raw_results = []

        validation_results = [self.validate_case(case) for case in raw_results]

        pass_cases = sum(1 for item in validation_results if item.verdict == ValidationVerdict.PASS)
        fail_cases = sum(1 for item in validation_results if item.verdict == ValidationVerdict.FAIL)
        skip_cases = sum(1 for item in validation_results if item.verdict == ValidationVerdict.SKIP)
        error_cases = sum(1 for item in validation_results if item.verdict == ValidationVerdict.ERROR)

        batch_result = ValidationBatchResult(
            thread_id=thread_id,
            target_name=target_name,
            total_cases=len(raw_results),
            validated_cases=len(validation_results),
            pass_cases=pass_cases,
            fail_cases=fail_cases,
            skip_cases=skip_cases,
            error_cases=error_cases,
            results=validation_results,
        )

        logger.info(
            "Finished validation batch.",
            extra={
                "pass_cases": pass_cases,
                "fail_cases": fail_cases,
                "skip_cases": skip_cases,
                "error_cases": error_cases,
            },
        )
        return batch_result

    def validate_case(self, execution_case_result: Any) -> ValidationCaseResult:
        testcase_id = self._get_first(
            execution_case_result,
            ["testcase_id", "testcase.id"],
            default=None,
        )
        operation_id = self._get_first(
            execution_case_result,
            ["operation_id", "testcase.operation_id", "operation.operation_id"],
            default=None,
        )
        target_name = self._get_first(
            execution_case_result,
            ["target_name", "testcase.target_name"],
            default=None,
        )

        logger = bind_logger(
            self._logger,
            testcase_id=testcase_id,
            operation_id=operation_id,
            target_name=target_name,
        )
        logger.info("Starting validation case.")

        logical_case_name = self._get_first(
            execution_case_result,
            ["logical_case_name", "testcase.logical_case_name", "logical_name"],
            default=None,
        )
        method = self._get_first(
            execution_case_result,
            ["method", "testcase.method", "operation.method"],
            default=None,
        )
        path = self._get_first(
            execution_case_result,
            ["path", "testcase.path", "operation.path"],
            default=None,
        )
        final_url = self._get_first(
            execution_case_result,
            ["final_url", "request.final_url"],
            default=None,
        )
        test_type = self._get_first(
            execution_case_result,
            ["test_type", "testcase.test_type"],
            default=None,
        )
        skip = bool(self._get_first(execution_case_result, ["skip"], default=False))
        skip_reason = self._get_first(execution_case_result, ["skip_reason"], default=None)
        network_error = self._get_first(execution_case_result, ["network_error"], default=None)
        actual_status = self._normalize_int(
            self._get_first(execution_case_result, ["actual_status", "status_code"], default=None)
        )
        response_time_ms = self._normalize_float(
            self._get_first(execution_case_result, ["response_time_ms"], default=None)
        )
        payload_source = self._get_first(execution_case_result, ["payload_source"], default=None)
        planner_reason = self._get_first(execution_case_result, ["planner_reason"], default=None)
        planner_confidence = self._normalize_float(
            self._get_first(execution_case_result, ["planner_confidence"], default=None)
        )

        expected_statuses = self._normalize_expected_statuses(
            self._get_first(
                execution_case_result,
                ["expected_statuses", "testcase.expected_statuses", "expected_status_codes"],
                default=[],
            )
        )

        response_json = self._get_first(
            execution_case_result,
            ["response_json"],
            default=None,
        )

        issues: list[ValidationIssue] = []
        status_check_passed: bool | None = None
        schema_check_passed: bool | None = None
        required_fields_check_passed: bool | None = None
        expected_required_fields: list[str] = []
        missing_required_fields: list[str] = []

        if skip:
            if skip_reason:
                issues.append(
                    ValidationIssue(
                        code="case_skipped",
                        message=f"Case skipped: {skip_reason}",
                        level="info",
                    )
                )
            result = ValidationCaseResult(
                testcase_id=testcase_id,
                logical_case_name=logical_case_name,
                target_name=target_name,
                operation_id=operation_id,
                method=method,
                path=path,
                final_url=final_url,
                test_type=test_type,
                skip=True,
                skip_reason=skip_reason,
                network_error=network_error,
                expected_statuses=expected_statuses,
                actual_status=actual_status,
                status_check_passed=None,
                schema_check_passed=None,
                required_fields_check_passed=None,
                expected_required_fields=[],
                missing_required_fields=[],
                response_time_ms=response_time_ms,
                payload_source=payload_source,
                planner_reason=planner_reason,
                planner_confidence=planner_confidence,
                verdict=ValidationVerdict.SKIP,
                summary_message=skip_reason or "Case skipped.",
                issues=issues,
            )
            logger.info("Finished validation case with skip verdict.")
            return result

        if expected_statuses:
            status_check_passed = actual_status in expected_statuses
            if not status_check_passed:
                issues.append(
                    ValidationIssue(
                        code="status_mismatch",
                        message=f"Expected status in {expected_statuses}, got {actual_status}.",
                        details={
                            "expected_statuses": expected_statuses,
                            "actual_status": actual_status,
                        },
                    )
                )
        else:
            status_check_passed = None
            issues.append(
                ValidationIssue(
                    code="missing_expected_statuses",
                    message="No expected statuses found on execution case.",
                    level="warning",
                )
            )

        if network_error:
            issues.append(
                ValidationIssue(
                    code="execution_error",
                    message=f"Execution error: {network_error}",
                    details={"network_error": network_error},
                )
            )
            result = ValidationCaseResult(
                testcase_id=testcase_id,
                logical_case_name=logical_case_name,
                target_name=target_name,
                operation_id=operation_id,
                method=method,
                path=path,
                final_url=final_url,
                test_type=test_type,
                skip=False,
                skip_reason=skip_reason,
                network_error=network_error,
                expected_statuses=expected_statuses,
                actual_status=actual_status,
                status_check_passed=status_check_passed,
                schema_check_passed=None,
                required_fields_check_passed=None,
                expected_required_fields=[],
                missing_required_fields=[],
                response_time_ms=response_time_ms,
                payload_source=payload_source,
                planner_reason=planner_reason,
                planner_confidence=planner_confidence,
                verdict=ValidationVerdict.ERROR,
                summary_message=f"Execution error: {network_error}",
                issues=issues,
            )
            logger.info("Finished validation case with error verdict.")
            return result

        expected_response_schema = self._resolve_expected_response_schema(execution_case_result)

        if isinstance(expected_response_schema, dict) and "$ref" in expected_response_schema and len(expected_response_schema) == 1:
            issues.append(
                ValidationIssue(
                    code="unresolved_schema_ref",
                    message=f"Skipping schema validation because schema contains unresolved $ref: {expected_response_schema['$ref']}",
                    level="warning",
                )
            )
            expected_response_schema = None

        if expected_response_schema is not None:
            if response_json is None:
                schema_check_passed = False
                issues.append(
                    ValidationIssue(
                        code="missing_response_json",
                        message="Expected JSON response body for validation, but response_json is None.",
                    )
                )
            else:
                schema_issues, required_issues, missing_required_fields = self._validate_payload_against_schema(
                    payload=response_json,
                    schema=expected_response_schema,
                    path="$",
                )

                if schema_issues:
                    schema_check_passed = False
                    issues.extend(schema_issues)
                else:
                    schema_check_passed = True

                inferred_required = self._extract_required_fields_from_schema(expected_response_schema)
                direct_required = self._resolve_expected_required_fields(execution_case_result)
                expected_required_fields = direct_required or inferred_required

                if expected_required_fields:
                    required_fields_check_passed = len(missing_required_fields) == 0
                    issues.extend(required_issues)
                else:
                    required_fields_check_passed = None
        else:
            schema_check_passed = None
            expected_required_fields = self._resolve_expected_required_fields(execution_case_result)
            if expected_required_fields and response_json is None:
                required_fields_check_passed = False
                issues.append(
                    ValidationIssue(
                        code="missing_response_json",
                        message="Expected JSON response body to validate required fields, but response_json is None.",
                    )
                )
            elif expected_required_fields and isinstance(response_json, dict):
                missing_required_fields = [
                    field_name
                    for field_name in expected_required_fields
                    if field_name not in response_json
                ]
                if missing_required_fields:
                    required_fields_check_passed = False
                    for field_name in missing_required_fields:
                        issues.append(
                            ValidationIssue(
                                code="missing_required_field",
                                message=f"Missing required response field: {field_name}",
                                path=f"$.{field_name}",
                            )
                        )
                else:
                    required_fields_check_passed = True
            else:
                required_fields_check_passed = None

        verdict = self._compute_verdict(
            status_check_passed=status_check_passed,
            schema_check_passed=schema_check_passed,
            required_fields_check_passed=required_fields_check_passed,
        )

        summary_message = self._build_summary_message(
            verdict=verdict,
            issues=issues,
            status_check_passed=status_check_passed,
            schema_check_passed=schema_check_passed,
            required_fields_check_passed=required_fields_check_passed,
        )

        result = ValidationCaseResult(
            testcase_id=testcase_id,
            logical_case_name=logical_case_name,
            target_name=target_name,
            operation_id=operation_id,
            method=method,
            path=path,
            final_url=final_url,
            test_type=test_type,
            skip=False,
            skip_reason=skip_reason,
            network_error=network_error,
            expected_statuses=expected_statuses,
            actual_status=actual_status,
            status_check_passed=status_check_passed,
            schema_check_passed=schema_check_passed,
            required_fields_check_passed=required_fields_check_passed,
            expected_required_fields=expected_required_fields,
            missing_required_fields=missing_required_fields,
            response_time_ms=response_time_ms,
            payload_source=payload_source,
            planner_reason=planner_reason,
            planner_confidence=planner_confidence,
            verdict=verdict,
            summary_message=summary_message,
            issues=issues,
        )

        logger.info(
            "Finished validation case.",
            extra={
                "verdict": verdict.value,
                "status_check_passed": status_check_passed,
                "schema_check_passed": schema_check_passed,
                "required_fields_check_passed": required_fields_check_passed,
            },
        )
        return result

    def _compute_verdict(
        self,
        *,
        status_check_passed: bool | None,
        schema_check_passed: bool | None,
        required_fields_check_passed: bool | None,
    ) -> ValidationVerdict:
        failed_checks = [
            check
            for check in [
                status_check_passed,
                schema_check_passed,
                required_fields_check_passed,
            ]
            if check is False
        ]
        if failed_checks:
            return ValidationVerdict.FAIL
        return ValidationVerdict.PASS

    def _build_summary_message(
        self,
        *,
        verdict: ValidationVerdict,
        issues: list[ValidationIssue],
        status_check_passed: bool | None,
        schema_check_passed: bool | None,
        required_fields_check_passed: bool | None,
    ) -> str:
        if verdict == ValidationVerdict.PASS:
            return "Validation passed."

        if verdict == ValidationVerdict.FAIL:
            failed_parts: list[str] = []
            if status_check_passed is False:
                failed_parts.append("status")
            if schema_check_passed is False:
                failed_parts.append("schema")
            if required_fields_check_passed is False:
                failed_parts.append("required_fields")

            if failed_parts:
                return f"Validation failed on: {', '.join(failed_parts)}."

            if issues:
                return f"Validation failed: {issues[0].message}"

            return "Validation failed."

        if verdict == ValidationVerdict.ERROR:
            return "Validation ended with execution error."

        return "Validation skipped."

    def _resolve_expected_response_schema(self, source: Any) -> dict[str, Any] | None:
        candidates = [
            "expected_response_schema",
            "response_schema",
            "expected_schema",
            "expected_output_schema",
            "testcase.expected_response_schema",
            "testcase.response_schema",
            "testcase.expected_schema",
            "testcase.expected_output_schema",
        ]

        for key in candidates:
            value = self._resolve_path(source, key)
            if isinstance(value, dict):
                return value

        return None

    def _resolve_expected_required_fields(self, source: Any) -> list[str]:
        candidates = [
            "expected_required_fields",
            "required_response_fields",
            "testcase.expected_required_fields",
            "testcase.required_response_fields",
            "testcase.required_fields",
        ]

        for key in candidates:
            value = self._resolve_path(source, key)
            normalized = self._normalize_string_list(value)
            if normalized:
                return normalized

        return []

    def _extract_required_fields_from_schema(self, schema: dict[str, Any]) -> list[str]:
        required = schema.get("required")
        if isinstance(required, list):
            return [str(item) for item in required]
        return []

    def _validate_payload_against_schema(
        self,
        payload: Any,
        schema: dict[str, Any],
        path: str,
    ) -> tuple[list[ValidationIssue], list[ValidationIssue], list[str]]:
        schema_issues: list[ValidationIssue] = []
        required_issues: list[ValidationIssue] = []
        missing_required_fields: list[str] = []

        if "$ref" in schema and len(schema) == 1:
            schema_issues.append(
                ValidationIssue(
                    code="unresolved_schema_ref",
                    message=f"Cannot validate unresolved $ref at {path}: {schema['$ref']}",
                    level="warning",
                    path=path,
                )
            )
            return schema_issues, required_issues, missing_required_fields

        if "allOf" in schema and isinstance(schema["allOf"], list):
            for sub_schema in schema["allOf"]:
                if isinstance(sub_schema, dict):
                    sub_schema_issues, sub_required_issues, sub_missing = self._validate_payload_against_schema(
                        payload=payload,
                        schema=sub_schema,
                        path=path,
                    )
                    schema_issues.extend(sub_schema_issues)
                    required_issues.extend(sub_required_issues)
                    missing_required_fields.extend(sub_missing)
            return schema_issues, required_issues, missing_required_fields

        if "oneOf" in schema and isinstance(schema["oneOf"], list):
            if self._matches_any_schema(payload, schema["oneOf"], path):
                return schema_issues, required_issues, missing_required_fields
            schema_issues.append(
                ValidationIssue(
                    code="schema_oneof_mismatch",
                    message=f"Payload at {path} does not match any schema in oneOf.",
                    path=path,
                )
            )
            return schema_issues, required_issues, missing_required_fields

        if "anyOf" in schema and isinstance(schema["anyOf"], list):
            if self._matches_any_schema(payload, schema["anyOf"], path):
                return schema_issues, required_issues, missing_required_fields
            schema_issues.append(
                ValidationIssue(
                    code="schema_anyof_mismatch",
                    message=f"Payload at {path} does not match any schema in anyOf.",
                    path=path,
                )
            )
            return schema_issues, required_issues, missing_required_fields

        expected_type = schema.get("type")
        if expected_type is None:
            if "properties" in schema:
                expected_type = "object"
            elif "items" in schema:
                expected_type = "array"

        if expected_type == "object":
            if not isinstance(payload, dict):
                schema_issues.append(
                    ValidationIssue(
                        code="schema_type_mismatch",
                        message=f"Expected object at {path}, got {type(payload).__name__}.",
                        path=path,
                    )
                )
                return schema_issues, required_issues, missing_required_fields

            required = schema.get("required")
            required_fields = required if isinstance(required, list) else []
            for field_name in required_fields:
                if field_name not in payload:
                    field_path = f"{path}.{field_name}" if path != "$" else f"$.{field_name}"
                    missing_required_fields.append(field_name)
                    required_issues.append(
                        ValidationIssue(
                            code="missing_required_field",
                            message=f"Missing required response field: {field_name}",
                            path=field_path,
                        )
                    )

            properties = schema.get("properties")
            if isinstance(properties, dict):
                for field_name, field_schema in properties.items():
                    if field_name not in payload:
                        continue
                    if not isinstance(field_schema, dict):
                        continue

                    nested_path = f"{path}.{field_name}" if path != "$" else f"$.{field_name}"
                    nested_schema_issues, nested_required_issues, nested_missing = self._validate_payload_against_schema(
                        payload=payload[field_name],
                        schema=field_schema,
                        path=nested_path,
                    )
                    schema_issues.extend(nested_schema_issues)
                    required_issues.extend(nested_required_issues)
                    missing_required_fields.extend(nested_missing)

            return schema_issues, required_issues, missing_required_fields

        if expected_type == "array":
            if not isinstance(payload, list):
                schema_issues.append(
                    ValidationIssue(
                        code="schema_type_mismatch",
                        message=f"Expected array at {path}, got {type(payload).__name__}.",
                        path=path,
                    )
                )
                return schema_issues, required_issues, missing_required_fields

            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(payload):
                    nested_path = f"{path}[{index}]"
                    nested_schema_issues, nested_required_issues, nested_missing = self._validate_payload_against_schema(
                        payload=item,
                        schema=item_schema,
                        path=nested_path,
                    )
                    schema_issues.extend(nested_schema_issues)
                    required_issues.extend(nested_required_issues)
                    missing_required_fields.extend(nested_missing)

            return schema_issues, required_issues, missing_required_fields

        if expected_type == "string":
            if not isinstance(payload, str):
                schema_issues.append(
                    ValidationIssue(
                        code="schema_type_mismatch",
                        message=f"Expected string at {path}, got {type(payload).__name__}.",
                        path=path,
                    )
                )
            return schema_issues, required_issues, missing_required_fields

        if expected_type == "integer":
            if not isinstance(payload, int) or isinstance(payload, bool):
                schema_issues.append(
                    ValidationIssue(
                        code="schema_type_mismatch",
                        message=f"Expected integer at {path}, got {type(payload).__name__}.",
                        path=path,
                    )
                )
            return schema_issues, required_issues, missing_required_fields

        if expected_type == "number":
            if not isinstance(payload, (int, float)) or isinstance(payload, bool):
                schema_issues.append(
                    ValidationIssue(
                        code="schema_type_mismatch",
                        message=f"Expected number at {path}, got {type(payload).__name__}.",
                        path=path,
                    )
                )
            return schema_issues, required_issues, missing_required_fields

        if expected_type == "boolean":
            if not isinstance(payload, bool):
                schema_issues.append(
                    ValidationIssue(
                        code="schema_type_mismatch",
                        message=f"Expected boolean at {path}, got {type(payload).__name__}.",
                        path=path,
                    )
                )
            return schema_issues, required_issues, missing_required_fields

        if expected_type == "null":
            if payload is not None:
                schema_issues.append(
                    ValidationIssue(
                        code="schema_type_mismatch",
                        message=f"Expected null at {path}, got {type(payload).__name__}.",
                        path=path,
                    )
                )
            return schema_issues, required_issues, missing_required_fields

        return schema_issues, required_issues, missing_required_fields

    def _matches_any_schema(self, payload: Any, candidate_schemas: list[Any], path: str) -> bool:
        for candidate in candidate_schemas:
            if not isinstance(candidate, dict):
                continue
            schema_issues, required_issues, _ = self._validate_payload_against_schema(
                payload=payload,
                schema=candidate,
                path=path,
            )
            only_warnings = all(issue.level == "warning" for issue in schema_issues + required_issues)
            if not schema_issues and not required_issues:
                return True
            if only_warnings:
                return True
        return False

    def _get_first(self, source: Any, keys: list[str], default: Any = None) -> Any:
        for key in keys:
            value = self._resolve_path(source, key)
            if value is not _MISSING:
                return value
        return default

    def _resolve_path(self, source: Any, path: str) -> Any:
        current = source
        for segment in path.split("."):
            if current is _MISSING:
                return _MISSING
            if isinstance(current, dict):
                if segment in current:
                    current = current[segment]
                    continue
                return _MISSING
            if hasattr(current, segment):
                current = getattr(current, segment)
                continue
            return _MISSING
        return current

    def _normalize_expected_statuses(self, value: Any) -> list[int]:
        if value is None:
            return []

        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",") if part.strip()]
            out: list[int] = []
            for part in parts:
                try:
                    out.append(int(part))
                except ValueError:
                    continue
            return sorted(set(out))

        if isinstance(value, (list, tuple, set)):
            out = []
            for item in value:
                normalized = self._normalize_int(item)
                if normalized is not None:
                    out.append(normalized)
            return sorted(set(out))

        normalized_single = self._normalize_int(value)
        if normalized_single is None:
            return []

        return [normalized_single]

    def _normalize_string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            stripped = value.strip()
            return [stripped] if stripped else []
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value]
        return []

    def _normalize_int(self, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return None
        return None

    def _normalize_float(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return None
        return None