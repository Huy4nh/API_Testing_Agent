from pathlib import Path

from api_testing_agent.core.models import ApiTarget, HttpMethod, ParamLocation
from api_testing_agent.core.openapi_ingestor import OpenApiIngestor


def test_load_openapi_from_local_file_with_refs(tmp_path: Path):
    spec_file = tmp_path / "openapi.yaml"
    spec_file.write_text(
        """
openapi: 3.0.0
info:
  title: Demo API
  version: 1.0.0

security:
  - bearerAuth: []

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

    PostDetail:
      type: object
      required:
        - id
        - title
      properties:
        id:
          type: integer
        title:
          type: string
        content:
          type: string

    EnvelopePostDetail:
      type: object
      required:
        - data
      properties:
        data:
          $ref: '#/components/schemas/PostDetail'

  parameters:
    PostId:
      name: id
      in: path
      required: true
      schema:
        type: integer

  requestBodies:
    PostCreateBody:
      required: true
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/PostCreateInput'

  responses:
    PostDetailResponse:
      description: OK
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/EnvelopePostDetail'

paths:
  /posts:
    post:
      tags:
        - posts
      summary: Create post
      requestBody:
        $ref: '#/components/requestBodies/PostCreateBody'
      responses:
        "201":
          description: Created

  /posts/{id}:
    parameters:
      - $ref: '#/components/parameters/PostId'
    get:
      tags:
        - posts
      summary: Get post detail
      responses:
        "200":
          $ref: '#/components/responses/PostDetailResponse'
        "404":
          description: Not Found
        """,
        encoding="utf-8",
    )

    target = ApiTarget(
        name="cms_local",
        base_url="http://127.0.0.1:8000",
        openapi_spec_path=str(spec_file),
        enabled=True,
    )

    ingestor = OpenApiIngestor()
    operations = ingestor.load_for_target(target)

    assert len(operations) == 2

    post_posts = next(op for op in operations if op.method == HttpMethod.POST and op.path == "/posts")
    assert post_posts.auth_required is True
    assert post_posts.request_body is not None
    assert post_posts.request_body.required is True
    assert post_posts.request_body.content_type == "application/json"
    assert post_posts.request_body.schema["type"] == "object"
    assert post_posts.request_body.schema["required"] == ["title", "content"]
    assert post_posts.request_body.schema["properties"]["title"]["type"] == "string"
    assert post_posts.request_body.schema["properties"]["published"]["type"] == "boolean"

    get_post_detail = next(
        op for op in operations if op.method == HttpMethod.GET and op.path == "/posts/{id}"
    )
    assert get_post_detail.auth_required is True
    assert len(get_post_detail.parameters) == 1
    assert get_post_detail.parameters[0].name == "id"
    assert get_post_detail.parameters[0].location == ParamLocation.PATH
    assert get_post_detail.parameters[0].required is True
    assert get_post_detail.parameters[0].schema["type"] == "integer"

    response_200 = get_post_detail.responses["200"]
    response_schema = response_200["content"]["application/json"]["schema"]
    assert response_schema["type"] == "object"
    assert response_schema["properties"]["data"]["type"] == "object"
    assert response_schema["properties"]["data"]["properties"]["id"]["type"] == "integer"
    assert response_schema["properties"]["data"]["properties"]["title"]["type"] == "string"