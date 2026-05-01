from __future__ import annotations

import copy
from typing import Any

from api_testing_agent.core.auth_header_builder import AuthHeaderBuilder
from api_testing_agent.core.execution_models import RuntimeRequest
from api_testing_agent.core.runtime_json_body_resolver import RuntimeJsonBodyResolver
from api_testing_agent.core.schema_faker import SchemaFaker
from api_testing_agent.logging_config import bind_logger, get_logger


class RequestRuntimeBuilder:
    def __init__(
        self,
        auth_header_builder: AuthHeaderBuilder | None = None,
        json_body_resolver: RuntimeJsonBodyResolver | None = None,
        schema_faker: SchemaFaker | None = None,
    ) -> None:
        self._auth_header_builder = auth_header_builder or AuthHeaderBuilder()
        self._json_body_resolver = json_body_resolver or RuntimeJsonBodyResolver()
        self._faker = schema_faker or SchemaFaker()
        self._logger = get_logger(__name__)

        self._logger.info(
            "Initialized RequestRuntimeBuilder.",
            extra={"payload_source": "request_runtime_builder_init"},
        )

    def build(
        self,
        *,
        target: Any,
        target_name: str,
        operation_context: dict[str, Any],
        case: dict[str, Any],
        case_index: int,
    ) -> RuntimeRequest:
        testcase_id = self._extract_testcase_id(
            case=case,
            operation_context=operation_context,
            case_index=case_index,
        )
        operation_id = str(operation_context.get("operation_id", ""))
        logger = bind_logger(
            self._logger,
            target_name=target_name,
            operation_id=operation_id,
            testcase_id=testcase_id,
            payload_source="request_runtime_build",
        )
        logger.info("Starting runtime request build.")

        logical_case_name = str(case.get("description") or f"case_{case_index}")

        skip = bool(case.get("skip", False))
        skip_reason = str(case.get("skip_reason", "")).strip() or None

        explicit_path_params = case.get("path_params")
        explicit_query_params = case.get("query_params")
        explicit_json_body = case.get("json_body")

        path_params = self._build_path_params(
            operation_context=operation_context,
            case=case,
            explicit_path_params=explicit_path_params,
        )

        planner_reason: str | None = None
        planner_confidence: float | None = None
        payload_source: str | None = None

        if skip:
            logger.info("Case marked as skip. Using explicit payload/query values only.")
            query_params = (
                copy.deepcopy(explicit_query_params)
                if isinstance(explicit_query_params, dict)
                else {}
            )
            json_body = copy.deepcopy(explicit_json_body) if explicit_json_body is not None else None
            payload_source = "skipped_case"
        else:
            query_params = self._build_query_params(
                operation_context=operation_context,
                explicit_query_params=explicit_query_params,
            )

            resolved_json_body = self._json_body_resolver.resolve(
                operation_context=operation_context,
                case=case,
                explicit_json_body=explicit_json_body,
            )
            json_body = resolved_json_body.value
            planner_reason = resolved_json_body.planner_reason
            planner_confidence = resolved_json_body.planner_confidence
            payload_source = resolved_json_body.source

            logger.info(
                f"Resolved JSON body. payload_source={payload_source}, planner_confidence={planner_confidence}"
            )

        headers = self._auth_header_builder.build(
            target=target,
            operation_context=operation_context,
            case=case,
        )

        final_url = self._build_url(
            base_url=self._extract_base_url(target),
            path_template=str(operation_context.get("path", "")),
            path_params=path_params,
        )

        expected_statuses = self._normalize_expected_statuses(case.get("expected_status_codes"))
        test_type = str(case.get("test_type", "")).strip().lower()

        logger.info(
            f"Runtime request build completed. skip={skip}, final_url={final_url}, query_params_count={len(query_params)}, header_count={len(headers)}"
        )

        return RuntimeRequest(
            testcase_id=testcase_id,
            logical_case_name=logical_case_name,
            target_name=target_name,
            operation_id=operation_id,
            method=str(operation_context.get("method", "")).upper(),
            path=str(operation_context.get("path", "")),
            final_url=final_url,
            final_headers=headers,
            final_query_params=query_params,
            final_json_body=json_body,
            expected_statuses=expected_statuses,
            test_type=test_type,
            skip=skip,
            skip_reason=skip_reason,
            planner_reason=planner_reason,
            planner_confidence=planner_confidence,
            payload_source=payload_source,
        )

    def _extract_testcase_id(
        self,
        *,
        case: dict[str, Any],
        operation_context: dict[str, Any],
        case_index: int,
    ) -> str:
        for key in ("testcase_id", "id", "logical_case_name"):
            value = case.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        operation_id = str(operation_context.get("operation_id", "operation"))
        return f"{operation_id}__case_{case_index:02d}"

    def _extract_base_url(self, target: Any) -> str:
        if isinstance(target, dict):
            base_url = target.get("base_url")
        else:
            base_url = getattr(target, "base_url", None)

        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("Target is missing base_url.")

        return base_url.strip()

    def _build_url(
        self,
        *,
        base_url: str,
        path_template: str,
        path_params: dict[str, Any],
    ) -> str:
        path = path_template
        for key, value in path_params.items():
            path = path.replace("{" + key + "}", str(value))
        return f"{base_url.rstrip('/')}{path}"

    def _build_path_params(
        self,
        *,
        operation_context: dict[str, Any],
        case: dict[str, Any],
        explicit_path_params: Any,
    ) -> dict[str, Any]:
        if isinstance(explicit_path_params, dict):
            return copy.deepcopy(explicit_path_params)

        result: dict[str, Any] = {}
        test_type = str(case.get("test_type", "")).strip().lower()

        for parameter in operation_context.get("parameters", []) or []:
            if str(parameter.get("location", "")).lower() != "path":
                continue

            name = str(parameter.get("name", ""))
            schema = parameter.get("schema") if isinstance(parameter.get("schema"), dict) else {}

            if test_type == "resource_not_found" and self._looks_like_resource_identifier(name):
                result[name] = self._not_found_value_for_schema(schema)
            else:
                result[name] = self._faker.example_for_schema(schema)

        return result

    def _build_query_params(
        self,
        *,
        operation_context: dict[str, Any],
        explicit_query_params: Any,
    ) -> dict[str, Any]:
        if isinstance(explicit_query_params, dict):
            return copy.deepcopy(explicit_query_params)

        result: dict[str, Any] = {}

        for parameter in operation_context.get("parameters", []) or []:
            if str(parameter.get("location", "")).lower() != "query":
                continue

            required = bool(parameter.get("required", False))
            if not required:
                continue

            name = str(parameter.get("name", ""))
            schema = parameter.get("schema") if isinstance(parameter.get("schema"), dict) else {}
            result[name] = self._faker.example_for_schema(schema)

        return result

    def _normalize_expected_statuses(self, raw: Any) -> list[int]:
        if not isinstance(raw, list):
            return []

        result: list[int] = []
        for item in raw:
            try:
                result.append(int(item))
            except Exception:
                continue
        return result

    def _looks_like_resource_identifier(self, name: str) -> bool:
        lowered = name.lower()
        return (
            lowered == "id"
            or lowered.endswith("_id")
            or lowered.endswith("id")
            or lowered in {"uuid", "slug", "post_id", "user_id"}
        )

    def _not_found_value_for_schema(self, schema: dict[str, Any]) -> Any:
        schema_type = schema.get("type")

        if schema_type == "integer":
            return 999999999
        if schema_type == "number":
            return 999999999
        if schema_type == "string":
            if schema.get("format") == "uuid":
                return "ffffffff-ffff-ffff-ffff-ffffffffffff"
            return "non-existent-resource"
        return 999999999