from api_testing_agent.core.payload_plan_models import PayloadPlan
from api_testing_agent.core.request_runtime_builder import RequestRuntimeBuilder
from api_testing_agent.core.runtime_json_body_resolver import RuntimeJsonBodyResolver
from api_testing_agent.core.runtime_payload_planning_graph import RuntimePayloadPlanningGraph


class FakePlannerService:
    def __init__(self, plan: PayloadPlan) -> None:
        self._plan = plan

    def plan(self, *, operation_context, case, explicit_json_body) -> PayloadPlan:
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


def test_builder_uses_general_resolver_and_mutates_quality():
    graph = RuntimePayloadPlanningGraph(
        planner_service=FakePlannerService(
            PayloadPlan(
                trust_explicit_payload=False,
                base_payload_strategy="synthesize_from_schema",
                mutation_kind="invalid_type_or_format",
                target_field="quality",
                invalid_value_strategy="string_for_integer",
                reason="mutate quality",
                confidence=1.0,
            )
        )
    )

    resolver = RuntimeJsonBodyResolver(planning_graph=graph)
    builder = RequestRuntimeBuilder(json_body_resolver=resolver)

    request = builder.build(
        target={"base_url": "https://example.com"},
        target_name="img_local",
        operation_context=build_operation_context(),
        case={
            "test_type": "invalid_type_or_format",
            "description": "Gửi request với 'quality' là string thay vì integer",
            "expected_status_codes": [422],
            "json_body": {},
        },
        case_index=1,
    )

    assert request.final_url == "https://example.com/img"
    assert isinstance(request.final_json_body, dict)
    assert request.final_json_body["quality"] == "invalid_integer"
    assert request.final_json_body["content"] != 12345
    assert request.payload_source == "mutated_invalid_type_or_format"
    assert request.planner_reason == "mutate quality"
    assert request.planner_confidence == 1.0