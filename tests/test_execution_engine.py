import httpx

from api_testing_agent.core.execution_engine import ExecutionEngine
from api_testing_agent.core.models import (
    ApiTarget,
    ExecutionResult,
    HttpMethod,
    OpenApiOperation,
    TestCase,
    TestType,
)


class TestableExecutionEngine(ExecutionEngine):
    def __init__(self, transport: httpx.BaseTransport, timeout_seconds: float = 15.0) -> None:
        super().__init__(timeout_seconds=timeout_seconds)
        self._transport = transport

    def execute(self, target: ApiTarget, test_case: TestCase) -> ExecutionResult:
        url = self._build_url(
            base_url=target.base_url,
            path_template=test_case.operation.path,
            path_params=test_case.path_params,
        )

        import time

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

            parsed_json = None
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


def build_test_case() -> TestCase:
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

    result = engine.execute(target, build_test_case())

    assert result.status_code == 200
    assert result.response_json == {"id": 1, "title": "hello"}
    assert result.error is None


def test_execute_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    transport = httpx.MockTransport(handler)

    engine = TestableExecutionEngine(transport=transport)
    target = ApiTarget(name="cms_local", base_url="http://127.0.0.1:8000")

    result = engine.execute(target, build_test_case())

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