from api_testing_agent.core.schema_faker import FakerOptions, SchemaFaker


IMG_INFO_SCHEMA = {
    "properties": {
        "content": {
            "anyOf": [
                {"type": "string", "maxLength": 2083, "minLength": 1, "format": "uri"},
                {"type": "string"},
            ],
            "title": "Content",
        },
        "prompt": {
            "anyOf": [
                {"type": "string"},
                {"type": "null"},
            ],
            "title": "Prompt",
        },
        "quality": {
            "anyOf": [
                {"type": "integer"},
                {"type": "null"},
            ],
            "title": "Quality",
            "default": 0,
        },
    },
    "type": "object",
    "required": ["content"],
    "title": "ImgInfo",
}


LINK_DATA_SCHEMA = {
    "properties": {
        "data": {
            "anyOf": [
                {"type": "string", "maxLength": 2083, "minLength": 1, "format": "uri"},
                {"type": "string"},
            ],
            "title": "Data",
        }
    },
    "type": "object",
    "required": ["data"],
    "title": "LinkData",
}


XPOST_DATA_SCHEMA = {
    "properties": {
        "content": {"type": "string", "title": "Content"},
        "drive_img_link": {
            "anyOf": [
                {"type": "string", "maxLength": 2083, "minLength": 1, "format": "uri"},
                {"type": "string"},
            ],
            "title": "Drive Img Link",
        },
        "prompt": {
            "anyOf": [
                {"type": "string"},
                {"type": "null"},
            ],
            "title": "Prompt",
        },
    },
    "type": "object",
    "required": ["content", "drive_img_link"],
    "title": "XPostData",
}


VALIDATION_ERROR_SCHEMA = {
    "properties": {
        "loc": {
            "items": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "integer"},
                ]
            },
            "type": "array",
            "title": "Location",
        },
        "msg": {"type": "string", "title": "Message"},
        "type": {"type": "string", "title": "Error Type"},
    },
    "type": "object",
    "required": ["loc", "msg", "type"],
    "title": "ValidationError",
}


HTTP_VALIDATION_ERROR_WITH_UNRESOLVED_REF = {
    "properties": {
        "detail": {
            "items": {"$ref": "#/components/schemas/ValidationError"},
            "type": "array",
            "title": "Detail",
        }
    },
    "type": "object",
    "title": "HTTPValidationError",
}


HTTP_VALIDATION_ERROR_RESOLVED = {
    "properties": {
        "detail": {
            "items": VALIDATION_ERROR_SCHEMA,
            "type": "array",
            "title": "Detail",
        }
    },
    "type": "object",
    "title": "HTTPValidationError",
}


def test_example_for_img_info_schema_from_openapi():
    faker = SchemaFaker()

    data = faker.example_for_schema(IMG_INFO_SCHEMA)

    # content dùng anyOf, phần tử đầu là string format uri
    assert data["content"] == "https://example.com"
    # prompt dùng anyOf(string, null) -> lấy string đầu tiên
    assert data["prompt"] == "string"
    # quality có default=0 nên phải lấy default trước
    assert data["quality"] == 0


def test_example_for_link_data_schema_from_openapi():
    faker = SchemaFaker()

    data = faker.example_for_schema(LINK_DATA_SCHEMA)

    assert data["data"] == "https://example.com"


def test_example_for_xpost_data_schema_from_openapi():
    faker = SchemaFaker()

    data = faker.example_for_schema(XPOST_DATA_SCHEMA)
    
    assert data["content"] == "string"
    assert data["drive_img_link"] == "https://example.com"
    assert data["prompt"] == "string"


def test_optional_fields_can_be_excluded_for_openapi_schema():
    faker = SchemaFaker(FakerOptions(include_optional_fields=False))

    data = faker.example_for_schema(XPOST_DATA_SCHEMA)

    assert data["content"] == "string"
    assert data["drive_img_link"] == "https://example.com"
    assert "prompt" not in data


def test_anyof_with_uri_prefers_first_branch():
    faker = SchemaFaker()

    schema = {
        "anyOf": [
            {"type": "string", "format": "uri"},
            {"type": "string"},
        ]
    }

    data = faker.example_for_schema(schema)

    assert data == "https://example.com"


def test_default_is_used_before_anyof():
    faker = SchemaFaker()

    schema = {
        "anyOf": [
            {"type": "integer"},
            {"type": "null"},
        ],
        "default": 0,
    }

    data = faker.example_for_schema(schema)

    assert data == 0


def test_validation_error_schema_can_be_generated_when_resolved():
    faker = SchemaFaker()

    data = faker.example_for_schema(VALIDATION_ERROR_SCHEMA)

    assert data["loc"] == ["string"]
    assert data["msg"] == "string"
    assert data["type"] == "string"


def test_http_validation_error_with_unresolved_ref_shows_current_limitation():
    faker = SchemaFaker()

    data = faker.example_for_schema(HTTP_VALIDATION_ERROR_WITH_UNRESOLVED_REF)

    # Vì items đang là $ref chưa resolve, SchemaFaker hiện tại không biết ValidationError là gì
    # nên item đầu tiên của detail sẽ là None
    assert data["detail"] == [None]


def test_http_validation_error_can_be_generated_after_manual_ref_resolution():
    faker = SchemaFaker()

    data = faker.example_for_schema(HTTP_VALIDATION_ERROR_RESOLVED)

    assert data["detail"][0]["loc"] == ["string"]
    assert data["detail"][0]["msg"] == "string"
    assert data["detail"][0]["type"] == "string"


def test_direct_ref_schema_is_not_resolved_by_schema_faker():
    faker = SchemaFaker()

    data = faker.example_for_schema({"$ref": "#/components/schemas/ImgInfo"})

    # Đây là hành vi hiện tại: SchemaFaker không tự dereference $ref
    assert data is None