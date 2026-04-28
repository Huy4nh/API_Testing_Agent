from api_testing_agent.core.ai_testcase_models import AITestCaseDraft
from api_testing_agent.core.models import (
    ApiTarget,
    HttpMethod,
    OpenApiOperation,
    OpenApiRequestBody,
    TestType,
)
from api_testing_agent.core.testcase_normalizer import TestCaseNormalizer


def build_post_operation() -> OpenApiOperation:
    return OpenApiOperation(
        operation_id="post_posts",
        method=HttpMethod.POST,
        path="/posts",
        tags=["posts"],
        summary="Create post",
        parameters=[],
        request_body=OpenApiRequestBody(
            required=True,
            content_type="application/json",
            schema={
                "type": "object",
                "required": ["title", "content"],
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "published": {"type": "boolean"},
                },
            },
        ),
        responses={
            "201": {
                "description": "Created",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["id", "title"],
                            "properties": {
                                "id": {"type": "integer"},
                                "title": {"type": "string"},
                            },
                        }
                    }
                },
            }
        },
        auth_required=True,
    )


def test_normalizer_injects_auth_and_success_schema():
    target = ApiTarget(
        name="cms_local",
        base_url="http://127.0.0.1:8000",
        auth_bearer_token="abc123",
        enabled=True,
    )

    draft = AITestCaseDraft(
        test_type="positive",
        description="Positive case",
        reasoning_summary="Use valid body",
        json_body={"title": "string", "content": "string", "published": True},
        expected_status_codes=[201],
    )

    normalizer = TestCaseNormalizer()
    case = normalizer.normalize(
        target=target,
        operation=build_post_operation(),
        draft=draft,
        ignore_fields=[],
    )

    assert case is not None
    assert case.test_type == TestType.POSITIVE
    assert case.headers["Authorization"] == "Bearer abc123"
    assert case.json_body is not None
    assert case.json_body["title"] == "string"
    assert case.expected_status_codes == {201}
    assert case.expected_response_schema is not None


def test_normalizer_removes_auth_for_unauthorized():
    target = ApiTarget(
        name="cms_local",
        base_url="http://127.0.0.1:8000",
        auth_bearer_token="abc123",
        enabled=True,
    )

    draft = AITestCaseDraft(
        test_type="unauthorized_or_forbidden",
        description="Unauthorized case",
        reasoning_summary="No token",
        headers={"Authorization": "Bearer should_not_be_kept"},
        expected_status_codes=[401, 403],
    )

    normalizer = TestCaseNormalizer()
    case = normalizer.normalize(
        target=target,
        operation=build_post_operation(),
        draft=draft,
        ignore_fields=[],
    )

    assert case is not None
    assert case.test_type == TestType.UNAUTHORIZED
    assert "Authorization" not in case.headers
    assert case.expected_status_codes == {401, 403}


def test_normalizer_applies_ignore_fields():
    target = ApiTarget(
        name="cms_local",
        base_url="http://127.0.0.1:8000",
        auth_bearer_token="abc123",
        enabled=True,
    )

    draft = AITestCaseDraft(
        test_type="positive",
        description="Positive case",
        reasoning_summary="Ignore published",
        json_body={"title": "string", "content": "string", "published": True},
        expected_status_codes=[201],
    )

    normalizer = TestCaseNormalizer()
    case = normalizer.normalize(
        target=target,
        operation=build_post_operation(),
        draft=draft,
        ignore_fields=["published"],
    )

    assert case is not None
    assert case.json_body is not None
    assert "published" not in case.json_body