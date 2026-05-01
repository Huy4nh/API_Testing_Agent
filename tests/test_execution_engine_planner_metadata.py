import httpx

from api_testing_agent.core.execution_engine import ExecutionEngine
from api_testing_agent.core.execution_models import RuntimeRequest


def test_execution_engine_preserves_planner_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"ok": True},
            headers={"Content-Type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    engine = ExecutionEngine(timeout_seconds=5.0, transport=transport)

    runtime_request = RuntimeRequest(
        testcase_id="case-001",
        logical_case_name="positive case",
        target_name="img_local",
        operation_id="image_generate_img_post",
        method="POST",
        path="/img",
        final_url="https://example.com/img",
        final_headers={},
        final_query_params={},
        final_json_body={"content": "hello"},
        expected_statuses=[200],
        test_type="positive",
        skip=False,
        skip_reason=None,
        planner_reason="planner chose synthesized valid payload",
        planner_confidence=0.92,
        payload_source="synthesized_valid_payload",
    )

    result = engine.execute_runtime_request(runtime_request)

    assert result.actual_status == 200
    assert result.response_json == {"ok": True}
    assert result.planner_reason == "planner chose synthesized valid payload"
    assert result.planner_confidence == 0.92
    assert result.payload_source == "synthesized_valid_payload"