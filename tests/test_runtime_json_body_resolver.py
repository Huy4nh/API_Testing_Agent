from api_testing_agent.core.payload_plan_models import PayloadPlan
from api_testing_agent.core.runtime_json_body_resolver import RuntimeJsonBodyResolver
from api_testing_agent.core.runtime_payload_planning_graph import RuntimePayloadPlanningGraph


class FakePlannerService:
    def __init__(self, plan: PayloadPlan) -> None:
        self._plan = plan

    def plan(self, *, operation_context, case, explicit_json_body):
        return self._plan


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


def test_positive_empty_payload_should_synthesize_valid_body():
    graph = RuntimePayloadPlanningGraph(
        planner_service=FakePlannerService(
            PayloadPlan(
                trust_explicit_payload=False,
                base_payload_strategy="synthesize_from_schema",
                mutation_kind="none",
                target_field=None,
                invalid_value_strategy=None,
                reason="test",
                confidence=1.0,
            )
        )
    )
    resolver = RuntimeJsonBodyResolver(planning_graph=graph)

    resolved = resolver.resolve(
        operation_context=build_operation_context(),
        case={"test_type": "positive", "description": "positive"},
        explicit_json_body={},
    )

    assert isinstance(resolved.value, dict)
    assert "content" in resolved.value
    assert resolved.source == "synthesized_valid_payload"


def test_missing_required_should_remove_content():
    graph = RuntimePayloadPlanningGraph(
        planner_service=FakePlannerService(
            PayloadPlan(
                trust_explicit_payload=False,
                base_payload_strategy="synthesize_from_schema",
                mutation_kind="remove_required_field",
                target_field="content",
                invalid_value_strategy=None,
                reason="remove content",
                confidence=1.0,
            )
        )
    )
    resolver = RuntimeJsonBodyResolver(planning_graph=graph)

    resolved = resolver.resolve(
        operation_context=build_operation_context(),
        case={"test_type": "missing_required"},
        explicit_json_body={},
    )

    assert isinstance(resolved.value, dict)
    assert "content" not in resolved.value
    assert "prompt" in resolved.value
    assert "quality" in resolved.value
    assert resolved.source == "mutated_missing_required"


def test_invalid_should_mutate_quality_not_content():
    graph = RuntimePayloadPlanningGraph(
        planner_service=FakePlannerService(
            PayloadPlan(
                trust_explicit_payload=False,
                base_payload_strategy="synthesize_from_schema",
                mutation_kind="invalid_type_or_format",
                target_field="quality",
                invalid_value_strategy="string_for_integer",
                reason="quality invalid",
                confidence=1.0,
            )
        )
    )
    resolver = RuntimeJsonBodyResolver(planning_graph=graph)

    resolved = resolver.resolve(
        operation_context=build_operation_context(),
        case={"test_type": "invalid_type_or_format"},
        explicit_json_body={},
    )

    assert isinstance(resolved.value, dict)
    assert resolved.value["quality"] == "invalid_integer"
    assert resolved.value["content"] != 12345
    assert resolved.source == "mutated_invalid_type_or_format"


def test_non_empty_explicit_payload_can_be_trusted():
    graph = RuntimePayloadPlanningGraph(
        planner_service=FakePlannerService(
            PayloadPlan(
                trust_explicit_payload=True,
                base_payload_strategy="use_explicit",
                mutation_kind="none",
                target_field=None,
                invalid_value_strategy=None,
                reason="trust explicit",
                confidence=1.0,
            )
        )
    )
    resolver = RuntimeJsonBodyResolver(planning_graph=graph)

    explicit = {
        "content": "my explicit prompt",
        "prompt": "extra",
        "quality": 80,
    }

    resolved = resolver.resolve(
        operation_context=build_operation_context(),
        case={"test_type": "positive"},
        explicit_json_body=explicit,
    )

    assert resolved.value == explicit
    assert resolved.source == "explicit_payload_final"