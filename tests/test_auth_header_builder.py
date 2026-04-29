from dataclasses import dataclass

from api_testing_agent.core.auth_header_builder import AuthHeaderBuilder


@dataclass
class DummyTarget:
    base_url: str
    auth_bearer_token: str | None = None


def test_adds_auth_when_required():
    builder = AuthHeaderBuilder()
    target = DummyTarget(base_url="http://example.com", auth_bearer_token="abc123")

    headers = builder.build(
        target=target,
        operation_context={"auth_required": True},
        case={"test_type": "positive"},
    )

    assert headers["Authorization"] == "Bearer abc123"


def test_unauthorized_case_removes_auth():
    builder = AuthHeaderBuilder()
    target = DummyTarget(base_url="http://example.com", auth_bearer_token="abc123")

    headers = builder.build(
        target=target,
        operation_context={"auth_required": True},
        case={
            "test_type": "unauthorized_or_forbidden",
            "headers": {"Authorization": "Bearer abc123"},
        },
    )

    assert "Authorization" not in headers