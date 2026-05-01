from api_testing_agent.core.ai_payload_planner_service import DeterministicFallbackPayloadPlanner


def build_operation_context():
    return {
        "operation_id": "image_generate_img_post",
        "method": "POST",
        "path": "/img",
        "auth_required": False,
        "parameters": [],
        "request_body": {
            "required": True,
            "content_type": "application/json",
            "schema": {
                "type": "object",
                "required": ["content"],
                "properties": {
                    "content": {
                        "anyOf": [
                            {"type": "string", "format": "uri"},
                            {"type": "string"},
                        ]
                    },
                    "prompt": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "null"},
                        ]
                    },
                    "quality": {
                        "anyOf": [
                            {"type": "integer"},
                            {"type": "null"},
                        ]
                    },
                },
            },
        },
        "responses": {"200": {"description": "OK"}},
    }


def test_fallback_planner_detects_missing_required_target_field():
    planner = DeterministicFallbackPayloadPlanner()

    plan = planner.plan(
        operation_context=build_operation_context(),
        case={
            "test_type": "missing_required",
            "description": "Gửi request thiếu trường bắt buộc 'content'",
            "why": "Trường 'content' là required",
        },
        explicit_json_body={},
    )

    assert plan.mutation_kind == "remove_required_field"
    assert plan.target_field == "content"


def test_fallback_planner_detects_invalid_quality():
    planner = DeterministicFallbackPayloadPlanner()

    plan = planner.plan(
        operation_context=build_operation_context(),
        case={
            "test_type": "invalid_type_or_format",
            "description": "Gửi request với 'quality' là string thay vì integer",
            "why": "Trường quality yêu cầu integer",
        },
        explicit_json_body={},
    )

    assert plan.mutation_kind == "invalid_type_or_format"
    assert plan.target_field == "quality"
    assert plan.invalid_value_strategy == "string_for_integer"


def test_fallback_planner_trusts_non_empty_explicit_payload():
    planner = DeterministicFallbackPayloadPlanner()

    plan = planner.plan(
        operation_context=build_operation_context(),
        case={
            "test_type": "positive",
            "description": "Positive case",
        },
        explicit_json_body={
            "content": "hello",
            "prompt": "world",
        },
    )

    assert plan.trust_explicit_payload is True
    assert plan.base_payload_strategy == "use_explicit"