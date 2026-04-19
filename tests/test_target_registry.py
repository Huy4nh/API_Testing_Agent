from pathlib import Path

from api_testing_agent.core.models import ApiTarget, HttpMethod, ParamLocation
from api_testing_agent.core.openapi_ingestor import OpenApiIngestor


def test_load_openapi_from_local_file(tmp_path: Path):
    spec_file = tmp_path / "openapi.yaml"
    spec_file.write_text(
        """
openapi: 3.0.0
info:
  title: Demo API
  version: 1.0.0

paths:
  /posts:
    get:
      tags:
        - posts
      summary: List posts
      responses:
        "200":
          description: OK

    post:
      tags:
        - posts
      summary: Create post
      security:
        - bearerAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - title
              properties:
                title:
                  type: string
                content:
                  type: string
      responses:
        "201":
          description: Created

  /posts/{id}:
    parameters:
      - name: id
        in: path
        required: true
        schema:
          type: integer

    get:
      tags:
        - posts
      summary: Get post detail
      responses:
        "200":
          description: OK
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

    assert len(operations) == 3

    get_posts = next(op for op in operations if op.method == HttpMethod.GET and op.path == "/posts")
    assert get_posts.tags == ["posts"]
    assert get_posts.summary == "List posts"
    assert get_posts.request_body is None
    assert get_posts.auth_required is False

    post_posts = next(op for op in operations if op.method == HttpMethod.POST and op.path == "/posts")
    assert post_posts.auth_required is True
    assert post_posts.request_body is not None
    assert post_posts.request_body.required is True
    assert post_posts.request_body.content_type == "application/json"
    assert post_posts.request_body.schema["type"] == "object"

    get_post_detail = next(
        op for op in operations if op.method == HttpMethod.GET and op.path == "/posts/{id}"
    )
    assert len(get_post_detail.parameters) == 1
    assert get_post_detail.parameters[0].name == "id"
    assert get_post_detail.parameters[0].location == ParamLocation.PATH
    assert get_post_detail.parameters[0].required is True