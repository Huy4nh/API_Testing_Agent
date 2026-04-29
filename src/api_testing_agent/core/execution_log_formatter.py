from __future__ import annotations

from typing import Any

from api_testing_agent.core.execution_models import ExecutionCaseResult


class ExecutionLogFormatter:
    SENSITIVE_HEADERS = {
        "authorization",
        "x-api-key",
        "api-key",
        "proxy-authorization",
    }

    def sanitize_headers(self, headers: dict[str, str]) -> dict[str, str]:
        sanitized: dict[str, str] = {}

        for key, value in headers.items():
            if key.lower() in self.SENSITIVE_HEADERS:
                sanitized[key] = self._mask_value(value)
            else:
                sanitized[key] = value

        return sanitized

    def format_case_result(self, result: ExecutionCaseResult) -> str:
        lines: list[str] = []
        lines.append(f"[{result.test_type}] {result.logical_case_name}")
        lines.append(f"  {result.method} {result.final_url}")
        lines.append(f"  expected: {result.expected_statuses}")
        lines.append(f"  actual: {result.actual_status}")
        lines.append(f"  time_ms: {result.response_time_ms:.2f}")
        lines.append(f"  network_error: {result.network_error}")

        if result.skip:
            lines.append("  skip: true")
            if result.skip_reason:
                lines.append(f"  skip_reason: {result.skip_reason}")

        return "\n".join(lines)

    def _mask_value(self, value: str) -> str:
        if len(value) <= 10:
            return "***"
        return value[:6] + "..." + value[-4:]