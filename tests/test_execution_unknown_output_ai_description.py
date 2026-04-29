import httpx

from api_testing_agent.core.execution_engine import ExecutionEngine


class FakeUnknownOutputDescriptionService:
    def describe(self, *, status_code: int, headers: dict[str, str], raw_bytes: bytes) -> str:
        return (
            f"AI summary: response thành công nhưng output chưa xác định rõ "
            f"(status={status_code}, content_type={headers.get('content-type', 'unknown')}, "
            f"size={len(raw_bytes)} bytes)."
        )


def build_operation_context():
    return {
        "operation_id": "custom_success_output",
        "method": "GET",
        "path": "/mystery",
        "auth_required": False,
        "parameters": [],
        "request_body": None,
        "responses": {
            "200": {"description": "OK"}
        },
    }


def build_draft_groups():
    return [
        {
            "operation_id": "custom_success_output",
            "method": "GET",
            "path": "/mystery",
            "cases": [
                {
                    "test_type": "positive",
                    "description": "Unknown 200 output case",
                    "expected_status_codes": [200],
                }
            ],
        }
    ]


def test_unknown_success_output_uses_ai_description():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            content=b"\x01\x02CUSTOM_PAYLOAD_\x7f_WITH_UNKNOWN_FORMAT",
            headers={"content-type": "application/x-custom-format"},
        )

    transport = httpx.MockTransport(handler)

    engine = ExecutionEngine(
        timeout_seconds=5.0,
        transport=transport,
        unknown_output_description_service=FakeUnknownOutputDescriptionService(),
    )

    target = {
        "base_url": "http://127.0.0.1:8000",
    }

    batch = engine.execute_approved_draft(
        thread_id="thread-unknown-output",
        target=target,
        target_name="cms_local",
        operation_contexts=[build_operation_context()],
        draft_groups=build_draft_groups(),
    )

    assert batch.total_cases == 1
    assert batch.executed_cases == 1
    assert batch.skipped_cases == 0

    result = batch.results[0]
    assert result.actual_status == 200
    assert result.response_json is None
    assert result.response_text is not None
    assert "AI summary:" in result.response_text
    assert "application/x-custom-format" in result.response_text