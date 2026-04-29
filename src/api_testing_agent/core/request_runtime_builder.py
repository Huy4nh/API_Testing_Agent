from __future__ import annotations

import copy
from typing import Any

from api_testing_agent.core.auth_header_builder import AuthHeaderBuilder
from api_testing_agent.core.execution_models import RuntimeRequest


class RequestRuntimeBuilder:
    def __init__(self, auth_header_builder: AuthHeaderBuilder | None = None) -> None:
        self._auth_header_builder = auth_header_builder or AuthHeaderBuilder()

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

        # Nếu case là skip:
        # - không synthesize query/body nữa
        # - chỉ giữ explicit values nếu AI draft đã đưa sẵn
        if skip:
            query_params = (
                copy.deepcopy(explicit_query_params)
                if isinstance(explicit_query_params, dict)
                else {}
            )
            json_body = copy.deepcopy(explicit_json_body) if explicit_json_body is not None else None
        else:
            query_params = self._build_query_params(
                operation_context=operation_context,
                explicit_query_params=explicit_query_params,
            )
            json_body = self._build_json_body(
                operation_context=operation_context,
                case=case,
                explicit_json_body=explicit_json_body,
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

        return RuntimeRequest(
            testcase_id=testcase_id,
            logical_case_name=logical_case_name,
            target_name=target_name,
            operation_id=str(operation_context.get("operation_id", "")),
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
                result[name] = self._example_for_schema(schema)

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
            result[name] = self._example_for_schema(schema)

        return result

    def _build_json_body(
        self,
        *,
        operation_context: dict[str, Any],
        case: dict[str, Any],
        explicit_json_body: Any,
    ) -> Any | None:
        if explicit_json_body is not None:
            return copy.deepcopy(explicit_json_body)

        request_body = operation_context.get("request_body")
        if not isinstance(request_body, dict):
            return None

        content_type = str(request_body.get("content_type", ""))
        if content_type != "application/json":
            return None

        schema = request_body.get("schema") if isinstance(request_body.get("schema"), dict) else {}
        if not schema:
            return None

        test_type = str(case.get("test_type", "")).strip().lower()

        valid_body = self._example_for_schema(schema)

        if test_type == "missing_required" and isinstance(valid_body, dict):
            mutated = copy.deepcopy(valid_body)
            required_fields = schema.get("required") or []
            if isinstance(required_fields, list) and required_fields:
                mutated.pop(str(required_fields[0]), None)
            return mutated

        if test_type == "invalid_type_or_format" and isinstance(valid_body, dict):
            return self._mutate_one_invalid_field(valid_body, schema)

        return valid_body

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

    def _example_for_schema(self, schema: dict[str, Any], depth: int = 0) -> Any:
        if depth > 5:
            return None

        if "example" in schema:
            return schema["example"]
        if "default" in schema:
            return schema["default"]
        if "enum" in schema and isinstance(schema["enum"], list) and schema["enum"]:
            return schema["enum"][0]

        schema_type = schema.get("type")

        if isinstance(schema_type, list):
            non_null = [item for item in schema_type if item != "null"]
            schema_type = non_null[0] if non_null else schema_type[0]

        if schema_type == "object" or (schema_type is None and "properties" in schema):
            result: dict[str, Any] = {}
            properties = schema.get("properties") or {}
            if not isinstance(properties, dict):
                return result

            for field_name, field_schema in properties.items():
                if not isinstance(field_schema, dict):
                    continue
                result[str(field_name)] = self._example_for_schema(field_schema, depth + 1)

            return result

        if schema_type == "array":
            items = schema.get("items")
            if isinstance(items, dict):
                return [self._example_for_schema(items, depth + 1)]
            return []

        if schema_type == "string":
            fmt = schema.get("format")
            if fmt == "email":
                return "user@example.com"
            if fmt == "uuid":
                return "00000000-0000-0000-0000-000000000000"
            if fmt in {"date-time", "datetime"}:
                return "2020-01-01T00:00:00Z"
            if fmt == "date":
                return "2020-01-01"
            if fmt == "uri":
                return "https://example.com/resource"
            return "string"

        if schema_type == "integer":
            minimum = schema.get("minimum")
            if isinstance(minimum, (int, float)):
                return int(minimum)
            return 1

        if schema_type == "number":
            minimum = schema.get("minimum")
            if isinstance(minimum, (int, float)):
                return float(minimum)
            return 1.0

        if schema_type == "boolean":
            return True

        return None

    def _mutate_one_invalid_field(
        self,
        body: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict):
            return body

        mutated = copy.deepcopy(body)

        for field_name, field_schema in properties.items():
            if field_name not in mutated:
                continue
            if not isinstance(field_schema, dict):
                continue

            field_type = field_schema.get("type")

            if field_type == "string":
                mutated[field_name] = 12345
                return mutated

            if field_type == "integer":
                mutated[field_name] = "invalid_integer"
                return mutated

            if field_type == "number":
                mutated[field_name] = "invalid_number"
                return mutated

            if field_type == "boolean":
                mutated[field_name] = "invalid_boolean"
                return mutated

            if field_type == "array":
                mutated[field_name] = "not_an_array"
                return mutated

            if field_type == "object":
                mutated[field_name] = "not_an_object"
                return mutated

        return mutated