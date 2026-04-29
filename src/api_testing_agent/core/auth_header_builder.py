from __future__ import annotations

from typing import Any


class AuthHeaderBuilder:
    def build(
        self,
        *,
        target: Any,
        operation_context: dict[str, Any],
        case: dict[str, Any],
    ) -> dict[str, str]:
        headers: dict[str, str] = {}

        default_headers = self._extract_default_headers(target)
        headers.update(default_headers)

        case_headers = case.get("headers") or {}
        if isinstance(case_headers, dict):
            for key, value in case_headers.items():
                headers[str(key)] = str(value)

        test_type = str(case.get("test_type", "")).strip().lower()
        auth_required = bool(operation_context.get("auth_required", False))

        if test_type == "unauthorized_or_forbidden":
            headers.pop("Authorization", None)
            return headers

        if auth_required and "Authorization" not in headers:
            token = self._extract_bearer_token(target)
            if token:
                headers["Authorization"] = f"Bearer {token}"

        return headers

    def _extract_default_headers(self, target: Any) -> dict[str, str]:
        raw = self._extract_value(target, "default_headers")
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
        return {}

    def _extract_bearer_token(self, target: Any) -> str | None:
        for field_name in (
            "auth_bearer_token",
            "bearer_token",
            "api_token",
            "token",
        ):
            value = self._extract_value(target, field_name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _extract_value(self, target: Any, name: str) -> Any:
        if isinstance(target, dict):
            return target.get(name)
        return getattr(target, name, None)