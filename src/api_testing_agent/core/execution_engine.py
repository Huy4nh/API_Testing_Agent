from __future__ import annotations

import time
from typing import Any

import httpx

from api_testing_agent.core.models import ApiTarget, ExecutionResult, TestCase


class ExecutionEngine:
    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self._timeout_seconds = timeout_seconds

    def execute(self, target: ApiTarget, test_case: TestCase) -> ExecutionResult:
        url = self._build_url(
            base_url=target.base_url,
            path_template=test_case.operation.path,
            path_params=test_case.path_params,
        )

        started = time.perf_counter()

        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                follow_redirects=True,
            ) as client:
                response = client.request(
                    method=test_case.operation.method.value.upper(),
                    url=url,
                    params=test_case.query_params,
                    headers=test_case.headers,
                    json=test_case.json_body,
                )

            elapsed_ms = (time.perf_counter() - started) * 1000

            parsed_json: Any | None = None
            try:
                parsed_json = response.json()
            except Exception:
                parsed_json = None

            return ExecutionResult(
                status_code=response.status_code,
                elapsed_ms=elapsed_ms,
                response_headers=dict(response.headers),
                response_json=parsed_json,
                response_text=response.text,
                error=None,
            )

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000

            return ExecutionResult(
                status_code=0,
                elapsed_ms=elapsed_ms,
                response_headers={},
                response_json=None,
                response_text=None,
                error=str(exc),
            )

    def _build_url(
        self,
        base_url: str,
        path_template: str,
        path_params: dict[str, Any],
    ) -> str:
        path = path_template

        for key, value in path_params.items():
            path = path.replace("{" + key + "}", str(value))

        return f"{base_url.rstrip('/')}{path}"