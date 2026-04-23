from api_testing_agent.core.openapi_ref_resolver import OpenApiRefResolver


def test_resolve_direct_schema_ref():
    spec = {
        "openapi": "3.0.0",
        "components": {
            "schemas": {
                "PostCreateInput": {
                    "type": "object",
                    "required": ["title", "content"],
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "published": {"type": "boolean"},
                    },
                }
            }
        },
    }

    resolver = OpenApiRefResolver(spec)
    schema = resolver.resolve_schema({"$ref": "#/components/schemas/PostCreateInput"})

    assert schema["type"] == "object"
    assert schema["required"] == ["title", "content"]
    assert schema["properties"]["title"]["type"] == "string"
    assert schema["properties"]["published"]["type"] == "boolean"


def test_resolve_nested_property_ref():
    spec = {
        "openapi": "3.0.0",
        "components": {
            "schemas": {
                "UserSummary": {
                    "type": "object",
                    "required": ["id", "username"],
                    "properties": {
                        "id": {"type": "integer"},
                        "username": {"type": "string"},
                    },
                },
                "PostDetail": {
                    "type": "object",
                    "required": ["title", "author"],
                    "properties": {
                        "title": {"type": "string"},
                        "author": {"$ref": "#/components/schemas/UserSummary"},
                    },
                },
            }
        },
    }

    resolver = OpenApiRefResolver(spec)
    schema = resolver.resolve_schema({"$ref": "#/components/schemas/PostDetail"})

    assert schema["type"] == "object"
    assert schema["properties"]["author"]["type"] == "object"
    assert schema["properties"]["author"]["properties"]["id"]["type"] == "integer"
    assert schema["properties"]["author"]["properties"]["username"]["type"] == "string"