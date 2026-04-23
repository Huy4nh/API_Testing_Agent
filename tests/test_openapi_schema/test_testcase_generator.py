from pathlib import Path

from api_testing_agent.core.models import (
    ApiTarget,
    HttpMethod,
    TestPlan as ApiTestPlan,
    TestType as ApiTestType,
)
from api_testing_agent.core.openapi_ingestor import OpenApiIngestor
from api_testing_agent.core.testcase_generator import TestCaseGenerator as ApiTestCaseGenerator


def test_generate_cases_from_ref_request_body_schema(tmp_path: Path):
    spec_file = tmp_path / "openapi.yaml"
    spec_file.write_text(
        """
openapi: 3.0.0
info:
  title: Demo API
  version: 1.0.0

components:
  schemas:
    PostCreateInput:
      type: object
      required:
        - title
        - content
      properties:
        title:
          type: string
        content:
          type: string
        published:
          type: boolean

  requestBodies:
    PostCreateBody:
      required: true
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/PostCreateInput'

paths:
  /posts:
    post:
      tags:
        - posts
      summary: Create post
      security:
        - bearerAuth: []
      requestBody:
        $ref: '#/components/requestBodies/PostCreateBody'
      responses:
        "201":
          description: Created
          content:
            application/json:
              schema:
                type: object
                required:
                  - id
                  - title
                properties:
                  id:
                    type: integer
                  title:
                    type: string
        """,
        encoding="utf-8",
    )

    target = ApiTarget(
        name="cms_local",
        base_url="http://127.0.0.1:8000",
        openapi_spec_path=str(spec_file),
        auth_bearer_token="abc123",
        enabled=True,
    )

    ingestor = OpenApiIngestor()
    operations = ingestor.load_for_target(target)

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
    cases = generator.generate(target, operations, plan)

    assert len(cases) == 4

    positive_case = next(case for case in cases if case.test_type == ApiTestType.POSITIVE)
    assert positive_case.headers["Authorization"] == "Bearer abc123"
    assert positive_case.json_body is not None
    assert positive_case.json_body["title"] == "string"
    assert positive_case.json_body["content"] == "string"
    assert positive_case.json_body["published"] is True
    assert 201 in positive_case.expected_status_codes

    missing_case = next(case for case in cases if case.test_type == ApiTestType.MISSING_REQUIRED)
    assert missing_case.json_body is not None
    assert ("title" not in missing_case.json_body) or ("content" not in missing_case.json_body)

    invalid_case = next(case for case in cases if case.test_type == ApiTestType.INVALID_TYPE_OR_FORMAT)
    assert invalid_case.json_body is not None
    assert (
        invalid_case.json_body["title"] == 12345
        or invalid_case.json_body["content"] == 12345
    )

    unauthorized_case = next(case for case in cases if case.test_type == ApiTestType.UNAUTHORIZED)
    assert unauthorized_case.headers == {}
    assert unauthorized_case.expected_status_codes == {401, 403}


def test_ignore_field_is_applied_after_ref_resolution(tmp_path: Path):
    spec_file = tmp_path / "openapi.yaml"
    spec_file.write_text(
        """
openapi: 3.0.0
info:
  title: Demo API
  version: 1.0.0

components:
  schemas:
    PostCreateInput:
      type: object
      required:
        - title
        - content
      properties:
        title:
          type: string
        content:
          type: string
        published:
          type: boolean

paths:
  /posts:
    post:
      tags:
        - posts
      summary: Create post
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/PostCreateInput'
      responses:
        "201":
          description: Created
        """,
        encoding="utf-8",
    )

    target = ApiTarget(
        name="cms_local",
        base_url="http://127.0.0.1:8000",
        openapi_spec_path=str(spec_file),
        auth_bearer_token="abc123",
        enabled=True,
    )

    ingestor = OpenApiIngestor()
    operations = ingestor.load_for_target(target)

    plan = ApiTestPlan(
        target_name="cms_local",
        tags=["posts"],
        methods=[HttpMethod.POST],
        test_types=[ApiTestType.POSITIVE],
        ignore_fields=["published"],
        limit_endpoints=10,
    )

    generator = ApiTestCaseGenerator()
    cases = generator.generate(target, operations, plan)

    assert len(cases) == 1
    assert cases[0].json_body is not None
    assert cases[0].json_body["title"] == "string"
    assert cases[0].json_body["content"] == "string"
    assert "published" not in cases[0].json_body