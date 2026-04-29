from dataclasses import dataclass

from api_testing_agent.core.request_runtime_builder import RequestRuntimeBuilder


@dataclass
class DummyTarget:
    base_url: str
    auth_bearer_token: str | None = None


def build_operation_context():
    return {
        "operation_id": "post_posts",
        "method": "POST",
        "path": "/posts/{id}",
        "auth_required": True,
        "parameters": [
            {
                "name": "id",
                "location": "path",
                "required": True,
                "schema": {"type": "integer"},
            }
        ],
        "request_body": {
            "required": True,
            "content_type": "application/json",
            "schema": {
                "type": "object",
                "required": ["title", "content"],
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "published": {"type": "boolean"},
                },
            },
        },
        "responses": {"201": {"description": "Created"}},
    }


def test_build_positive_runtime_request():
    builder = RequestRuntimeBuilder()
    target = DummyTarget(base_url="http://127.0.0.1:8000", auth_bearer_token="abc123")

    runtime = builder.build(
        target=target,
        target_name="cms_local",
        operation_context=build_operation_context(),
        case={
            "test_type": "positive",
            "description": "Create post",
            "expected_status_codes": [201],
        },
        case_index=1,
    )

    assert runtime.final_url == "http://127.0.0.1:8000/posts/1"
    assert runtime.final_headers["Authorization"] == "Bearer abc123"
    assert runtime.final_json_body["title"] == "string"
    assert runtime.expected_statuses == [201]


def test_build_missing_required_runtime_request():
    builder = RequestRuntimeBuilder()
    target = DummyTarget(base_url="http://127.0.0.1:8000", auth_bearer_token="abc123")

    runtime = builder.build(
        target=target,
        target_name="cms_local",
        operation_context=build_operation_context(),
        case={
            "test_type": "missing_required",
            "description": "Missing title",
            "expected_status_codes": [422],
        },
        case_index=2,
    )

    assert runtime.final_json_body is not None
    assert "title" not in runtime.final_json_body or "content" not in runtime.final_json_body