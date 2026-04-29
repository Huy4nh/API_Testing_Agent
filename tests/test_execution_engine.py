import httpx

from api_testing_agent.core.execution_engine import ExecutionEngine


def build_operation_context():
    return {
        "operation_id": "get_post",
        "method": "GET",
        "path": "/posts/{id}",
        "auth_required": False,
        "parameters": [
            {
                "name": "id",
                "location": "path",
                "required": True,
                "schema": {"type": "integer"},
            }
        ],
        "request_body": None,
        "responses": {"200": {"description": "OK"}},
    }


def build_draft_groups():
    return [
        {
            "operation_id": "get_post",
            "method": "GET",
            "path": "/posts/{id}",
            "cases": [
                {
                    "test_type": "positive",
                    "description": "Get post detail",
                    "expected_status_codes": [200],
                }
            ],
        }
    ]


def test_execute_approved_draft_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "http://127.0.0.1:8000/posts/1"
        return httpx.Response(
            status_code=200,
            json={"id": 1, "title": "hello"},
            headers={"Content-Type": "application/json"},
        )

    transport = httpx.MockTransport(handler)

    engine = ExecutionEngine(timeout_seconds=5.0, transport=transport)

    target = {
        "base_url": "http://127.0.0.1:8000",
    }

    batch = engine.execute_approved_draft(
        thread_id="thread-1",
        target=target,
        target_name="cms_local",
        operation_contexts=[build_operation_context()],
        draft_groups=build_draft_groups(),
    )

    assert batch.total_cases == 1
    assert batch.executed_cases == 1
    assert batch.skipped_cases == 0
    assert batch.results[0].actual_status == 200
    assert batch.results[0].response_json == {"id": 1, "title": "hello"}


def test_execute_skipped_case():
    transport = httpx.MockTransport(lambda request: httpx.Response(status_code=500))
    engine = ExecutionEngine(timeout_seconds=5.0, transport=transport)

    target = {"base_url": "http://127.0.0.1:8000"}

    draft_groups = [
        {
            "operation_id": "get_post",
            "method": "GET",
            "path": "/posts/{id}",
            "cases": [
                {
                    "test_type": "resource_not_found",
                    "description": "skip me",
                    "expected_status_codes": [404],
                    "skip": True,
                    "skip_reason": "not applicable",
                }
            ],
        }
    ]

    batch = engine.execute_approved_draft(
        thread_id="thread-1",
        target=target,
        target_name="cms_local",
        operation_contexts=[build_operation_context()],
        draft_groups=draft_groups,
    )

    assert batch.total_cases == 1
    assert batch.executed_cases == 0
    assert batch.skipped_cases == 1
    assert batch.results[0].skip is True
    assert batch.results[0].skip_reason == "not applicable"