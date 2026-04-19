from __future__ import annotations

import os
import time
from typing import Any

from dataclasses import replace

import httpx
import pytest

from api_testing_agent.core.execution_engine import ExecutionEngine
from api_testing_agent.core.models import (
    ApiTarget,
    ExecutionResult,
    HttpMethod,
    OpenApiOperation,
    OpenApiRequestBody,
    TestCase,
    TestType,
)


# =========================
# UNIT TEST PART (MOCK)
# =========================

class TestableExecutionEngine(ExecutionEngine):
    """
    Bản testable để giữ lại unit test mock transport.
    Không dùng cho production.
    """

    def __init__(self, transport: httpx.BaseTransport, timeout_seconds: float = 15.0) -> None:
        super().__init__(timeout_seconds=timeout_seconds)
        self._transport = transport

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
                transport=self._transport,
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


def build_mock_test_case() -> TestCase:
    operation = OpenApiOperation(
        operation_id="get_post",
        method=HttpMethod.GET,
        path="/posts/{id}",
        tags=["posts"],
        summary="Get post detail",
        parameters=[],
        request_body=None,
        responses={"200": {"description": "OK"}},
        auth_required=False,
    )

    return TestCase(
        id="case-1",
        target_name="cms_local",
        operation=operation,
        test_type=TestType.POSITIVE,
        description="Positive test",
        path_params={"id": 1},
        query_params={"expand": "author"},
        headers={"X-Test": "1"},
        json_body=None,
        expected_status_codes={200},
        expected_response_schema=None,
    )


def test_execute_success_json_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "http://127.0.0.1:8000/posts/1?expand=author"
        assert request.headers["X-Test"] == "1"
        return httpx.Response(
            status_code=200,
            json={"id": 1, "title": "hello"},
            headers={"Content-Type": "application/json"},
        )

    transport = httpx.MockTransport(handler)

    engine = TestableExecutionEngine(transport=transport)
    target = ApiTarget(name="cms_local", base_url="http://127.0.0.1:8000")

    result = engine.execute(target, build_mock_test_case())

    assert result.status_code == 200
    assert result.response_json == {"id": 1, "title": "hello"}
    assert result.error is None


def test_execute_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    transport = httpx.MockTransport(handler)

    engine = TestableExecutionEngine(transport=transport)
    target = ApiTarget(name="cms_local", base_url="http://127.0.0.1:8000")

    result = engine.execute(target, build_mock_test_case())

    assert result.status_code == 0
    assert result.response_json is None
    assert result.error is not None


def test_build_url():
    engine = ExecutionEngine()

    url = engine._build_url(
        base_url="http://127.0.0.1:8000/",
        path_template="/posts/{id}",
        path_params={"id": 55},
    )

    assert url == "http://127.0.0.1:8000/posts/55"


# =========================
# LIVE TEST PART (NGROK)
# =========================

NGROK_LIVE_TARGET = ApiTarget(
    name="ngrok_live",
    base_url="https://gnat-cuddly-supposedly.ngrok-free.app",
    openapi_spec_url="https://gnat-cuddly-supposedly.ngrok-free.app/openapi.json",
    enabled=True,
)


def build_live_x_content_422_case() -> TestCase:
    """
    Dựa theo OpenAPI:
      POST /X/content
      body required: {"data": "..."}
    Ta cố tình gửi body rỗng để nhận 422 ổn định.
    """
    operation = OpenApiOperation(
        operation_id="x_content_X_content_post",
        method=HttpMethod.POST,
        path="/X/content",
        tags=["x"],
        summary="X Content",
        parameters=[],
        request_body=OpenApiRequestBody(
            required=True,
            content_type="application/json",
            schema={
                "type": "object",
                "required": ["data"],
                "properties": {
                    "data": {
                        "anyOf": [
                            {"type": "string", "format": "uri", "minLength": 1, "maxLength": 2083},
                            {"type": "string"},
                        ]
                    }
                },
            },
        ),
        responses={
            "200": {"description": "Successful Response"},
            "422": {"description": "Validation Error"},
        },
        auth_required=False,
    )

    return TestCase(
        id="live-ngrok-x-content-422",
        target_name="ngrok_live",
        operation=operation,
        test_type=TestType.MISSING_REQUIRED,
        description="Live test: POST /X/content with invalid body to trigger 422",
        path_params={},
        query_params={},
        headers={},
        json_body={},  # cố tình thiếu field required: data
        expected_status_codes={422},
        expected_response_schema=None,
    )


def build_live_img_422_case() -> TestCase:
    """
    Dựa theo OpenAPI:
      POST /img
      body required: {"content": "..."}
    Ta cũng cố tình gửi body rỗng để nhận 422.
    """
    operation = OpenApiOperation(
        operation_id="image_generate_img_post",
        method=HttpMethod.POST,
        path="/img",
        tags=["img"],
        summary="Image Generate",
        parameters=[],
        request_body=OpenApiRequestBody(
            required=True,
            content_type="application/json",
            schema={
                "type": "object",
                "required": ["content"],
                "properties": {
                    "content": {
                        "anyOf": [
                            {"type": "string", "format": "uri", "minLength": 1, "maxLength": 2083},
                            {"type": "string"},
                        ]
                    },
                    "prompt": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                    "quality": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "default": 0,
                    },
                },
            },
        ),
        responses={
            "200": {"description": "Successful Response"},
            "422": {"description": "Validation Error"},
        },
        auth_required=False,
    )

    return TestCase(
        id="live-ngrok-img-422",
        target_name="ngrok_live",
        operation=operation,
        test_type=TestType.MISSING_REQUIRED,
        description="Live test: POST /img with invalid body to trigger 422",
        path_params={},
        query_params={},
        headers={},
        json_body={},  # cố tình thiếu field required: content
        expected_status_codes={422},
        expected_response_schema=None,
    )


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_API_TESTS") != "1",
    reason="Set RUN_LIVE_API_TESTS=1 để chạy live integration test với target thật.",
)
def test_execute_live_x_content_returns_422():
    engine = ExecutionEngine(timeout_seconds=20.0)
    case = build_live_x_content_422_case()

    result = engine.execute(NGROK_LIVE_TARGET, case)

    assert result.error is None, f"Lỗi transport/network: {result.error}"
    assert result.status_code == 422
    assert result.elapsed_ms >= 0
    assert isinstance(result.response_headers, dict)
    assert result.response_json is not None
    assert isinstance(result.response_json, dict)
    assert "detail" in result.response_json


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_API_TESTS") != "1",
    reason="Set RUN_LIVE_API_TESTS=1 để chạy live integration test với target thật.",
)
def test_execute_live_img_returns_422():
    engine = ExecutionEngine(timeout_seconds=20.0)
    case = build_live_img_422_case()

    result = engine.execute(NGROK_LIVE_TARGET, case)

    assert result.error is None, f"Lỗi transport/network: {result.error}"
    assert result.status_code == 422
    assert result.elapsed_ms >= 0
    assert isinstance(result.response_headers, dict)
    assert result.response_json is not None
    assert isinstance(result.response_json, dict)
    assert "detail" in result.response_json

@pytest.mark.skipif(
    os.getenv("RUN_LIVE_API_TESTS") != "1",
    reason="Set RUN_LIVE_API_TESTS=1 để chạy live integration test với target thật.",
)
def test_execute_live_img_returns_200():
    engine = ExecutionEngine(timeout_seconds=22222.0)

    old_case = build_live_img_422_case()

    case = replace(
        old_case,
        id="live-ngrok-img-200",
        json_body={
            "content": "Generate an image of a futuristic city at sunset"
        },
        expected_status_codes={200},
        expected_response_schema=None,
    )

    result = engine.execute(NGROK_LIVE_TARGET, case)

    assert result.error is None, f"Lỗi transport/network: {result.error}"
    assert result.status_code == 200, (
        f"Expected 200 but got {result.status_code}. "
        f"Response body: {result.response_text}"
    )
    assert result.elapsed_ms > 0