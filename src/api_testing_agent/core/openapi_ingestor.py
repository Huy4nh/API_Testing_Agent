from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import yaml

from api_testing_agent.core.models import (
    ApiTarget,
    HttpMethod,
    OpenApiOperation,
    OpenApiParameter,
    OpenApiRequestBody,
    ParamLocation,
)


class OpenApiIngestError(ValueError):
    pass


class OpenApiIngestor:
    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self._timeout_seconds = timeout_seconds

    def load_for_target(self, target: ApiTarget) -> list[OpenApiOperation]:
        spec = self._load_raw_spec(target)
        return self._parse_operations(spec)

    def _load_raw_spec(self, target: ApiTarget) -> dict[str, Any]:
        if target.openapi_spec_path:
            path = Path(target.openapi_spec_path)
            if not path.exists():
                raise OpenApiIngestError(
                    f"OpenAPI spec path not found: {target.openapi_spec_path}"
                )
            text = path.read_text(encoding="utf-8")
            return self._parse_text(text)

        if target.openapi_spec_url:
            with httpx.Client(timeout=self._timeout_seconds, follow_redirects=True) as client:
                response = client.get(target.openapi_spec_url)
                response.raise_for_status()
                return self._parse_text(response.text)

        raise OpenApiIngestError(
            f"Target '{target.name}' has neither openapi_spec_path nor openapi_spec_url."
        )

    def _parse_text(self, text: str) -> dict[str, Any]:
        stripped = text.strip()
        if not stripped:
            raise OpenApiIngestError("OpenAPI spec content is empty.")

        try:
            if stripped.startswith("{"):
                data = json.loads(stripped)
            else:
                data = yaml.safe_load(stripped)
        except Exception as exc:
            raise OpenApiIngestError(f"Failed to parse OpenAPI content: {exc}") from exc

        if not isinstance(data, dict):
            raise OpenApiIngestError("OpenAPI content must be a JSON/YAML object.")

        return data

    def _parse_operations(self, spec: dict[str, Any]) -> list[OpenApiOperation]:
        paths = spec.get("paths")
        if not isinstance(paths, dict):
            raise OpenApiIngestError("Invalid OpenAPI spec: missing 'paths'.")

        operations: list[OpenApiOperation] = []

        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue

            for method_key, operation_data in path_item.items():
                if method_key.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                if not isinstance(operation_data, dict):
                    continue

                method = HttpMethod(method_key.lower())

                operation = OpenApiOperation(
                    operation_id=operation_data.get("operationId") or f"{method.value}_{path}",
                    method=method,
                    path=path,
                    tags=self._safe_string_list(operation_data.get("tags")),
                    summary=self._safe_string(operation_data.get("summary")),
                    parameters=self._parse_parameters(
                        path_item.get("parameters"),
                        operation_data.get("parameters"),
                    ),
                    request_body=self._parse_request_body(operation_data.get("requestBody")),
                    responses=self._parse_responses(operation_data.get("responses")),
                    auth_required=self._detect_auth_required(operation_data),
                )
                operations.append(operation)

        return operations

    def _parse_parameters(
        self,
        path_level_parameters: Any,
        operation_level_parameters: Any,
    ) -> list[OpenApiParameter]:
        collected: list[OpenApiParameter] = []

        for source in [path_level_parameters, operation_level_parameters]:
            if not isinstance(source, list):
                continue

            for item in source:
                if not isinstance(item, dict):
                    continue

                location = item.get("in")
                if location not in {"path", "query", "header", "cookie"}:
                    continue

                parameter = OpenApiParameter(
                    name=self._safe_string(item.get("name")),
                    location=ParamLocation(location),
                    required=bool(item.get("required", False)),
                    schema=item.get("schema") if isinstance(item.get("schema"), dict) else {},
                )
                collected.append(parameter)

        unique: dict[tuple[str, str], OpenApiParameter] = {}
        for parameter in collected:
            key = (parameter.name, parameter.location.value)
            unique[key] = parameter

        return list(unique.values())

    def _parse_request_body(self, request_body: Any) -> OpenApiRequestBody | None:
        if not isinstance(request_body, dict):
            return None

        content = request_body.get("content")
        if not isinstance(content, dict):
            return None

        if "application/json" in content:
            media = content["application/json"]
            if isinstance(media, dict):
                return OpenApiRequestBody(
                    required=bool(request_body.get("required", False)),
                    content_type="application/json",
                    schema=media.get("schema") if isinstance(media.get("schema"), dict) else {},
                )

        for content_type, media in content.items():
            if isinstance(media, dict):
                return OpenApiRequestBody(
                    required=bool(request_body.get("required", False)),
                    content_type=str(content_type),
                    schema=media.get("schema") if isinstance(media.get("schema"), dict) else {},
                )

        return None

    def _parse_responses(self, responses: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(responses, dict):
            return {}

        parsed: dict[str, dict[str, Any]] = {}
        for status_code, response_data in responses.items():
            if isinstance(response_data, dict):
                parsed[str(status_code)] = response_data

        return parsed

    def _detect_auth_required(self, operation_data: dict[str, Any]) -> bool:
        security = operation_data.get("security")
        if isinstance(security, list) and len(security) > 0:
            return True
        return False

    def _safe_string(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        return ""

    def _safe_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]