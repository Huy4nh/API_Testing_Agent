from api_testing_agent.core.schema_faker import FakerOptions, SchemaFaker


def test_example_for_simple_object():
    faker = SchemaFaker()

    schema = {
        "type": "object",
        "required": ["title", "content"],
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
            "published": {"type": "boolean"},
        },
    }

    data = faker.example_for_schema(schema)

    assert data["title"] == "string"
    assert data["content"] == "string"
    assert data["published"] is True


def test_example_for_email():
    faker = SchemaFaker()

    schema = {"type": "string", "format": "email"}
    data = faker.example_for_schema(schema)

    assert data == "user@example.com"


def test_optional_fields_can_be_excluded():
    faker = SchemaFaker(FakerOptions(include_optional_fields=False))

    schema = {
        "type": "object",
        "required": ["title"],
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
        },
    }

    data = faker.example_for_schema(schema)

    assert "title" in data
    assert "content" not in data


def test_enum_is_used_first():
    faker = SchemaFaker()

    schema = {"type": "string", "enum": ["draft", "published"]}
    data = faker.example_for_schema(schema)

    assert data == "draft"