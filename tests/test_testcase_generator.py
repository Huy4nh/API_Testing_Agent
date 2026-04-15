from api_testing_agent.core.models import (
    ApiTarget,
    HttpMethod,
    OpenApiOperation,
    OpenApiRequestBody,
    TestPlan as ApiTestPlan,
    TestType as ApiTestType,
)
from api_testing_agent.core.testcase_generator import TestCaseGenerator as ApiTestCaseGenerator


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


def test_generate_positive_and_negative_cases():
    target = ApiTarget(
        name="cms_local",
        base_url="http://127.0.0.1:8000",
        auth_bearer_token="abc123",
        enabled=True,
    )

    operation = build_post_operation()

    plan = ApiTestPlan(
        target_name="cms_local",
        tags=["posts"],
        methods=[HttpMethod.POST],
        test_types=[
            ApiTestType.POSITIVE,
            ApiTestType.MISSING_REQUIRED,
            ApiTestType.INVALID_TYPE_OR_FORMAT,
            ApiTestType.UNAUTHORIZED,
        ],
        ignore_fields=[],
        limit_endpoints=10,
    )

    generator = ApiTestCaseGenerator()
    cases = generator.generate(target, [operation], plan)

    assert len(cases) == 4

    positive_case = next(case for case in cases if case.test_type == ApiTestType.POSITIVE)
    assert positive_case.headers["Authorization"] == "Bearer abc123"
    assert positive_case.json_body is not None
    assert positive_case.json_body["title"] == "string"
    assert 201 in positive_case.expected_status_codes

    missing_case = next(case for case in cases if case.test_type == ApiTestType.MISSING_REQUIRED)
    assert missing_case.json_body is not None
    assert "title" not in missing_case.json_body or "content" not in missing_case.json_body

    invalid_case = next(case for case in cases if case.test_type == ApiTestType.INVALID_TYPE_OR_FORMAT)
    assert invalid_case.json_body is not None

    unauthorized_case = next(case for case in cases if case.test_type == ApiTestType.UNAUTHORIZED)
    assert unauthorized_case.headers == {}
    assert unauthorized_case.expected_status_codes == {401, 403}


def test_ignore_field_is_applied():
    target = ApiTarget(
        name="cms_local",
        base_url="http://127.0.0.1:8000",
        auth_bearer_token="abc123",
        enabled=True,
    )

    operation = build_post_operation()

    plan = ApiTestPlan(
        target_name="cms_local",
        tags=["posts"],
        methods=[HttpMethod.POST],
        test_types=[ApiTestType.POSITIVE],
        ignore_fields=["published"],
        limit_endpoints=10,
    )

    generator = ApiTestCaseGenerator()
    cases = generator.generate(target, [operation], plan)

    assert len(cases) == 1
    assert cases[0].json_body is not None
    assert "published" not in cases[0].json_body