from api_testing_agent.core.payload_plan_models import PayloadPlan
from api_testing_agent.core.runtime_json_body_resolver import RuntimeJsonBodyResolver
from api_testing_agent.core.runtime_payload_planning_graph import RuntimePayloadPlanningGraph


class FakePlannerService:
    def __init__(self, plan: PayloadPlan) -> None:
        self._plan = plan

    def plan(self, *, operation_context, case, explicit_json_body) -> PayloadPlan:
        return self._plan


def build_yt_operation_context():
    return {
        "operation_id": "yt_get_content_YT_post",
        "method": "POST",
        "path": "/YT",
        "summary": "Get YouTube content",
        "auth_required": False,
        "parameters": [],
        "request_body": {
            "required": True,
            "content_type": "application/json",
            "schema": {
                "type": "object",
                "required": ["data"],
                "properties": {
                    "data": {
                        "type": "string"
                    }
                },
            },
        },
        "responses": {"200": {"description": "OK"}},
    }


def test_yt_positive_should_use_concrete_youtube_url_override():
    graph = RuntimePayloadPlanningGraph(
        planner_service=FakePlannerService(
            PayloadPlan(
                trust_explicit_payload=False,
                base_payload_strategy="synthesize_from_schema",
                mutation_kind="semantic_positive",
                field_overrides={
                    "data": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                },
                reason="Use a real YouTube URL",
                confidence=0.99,
            )
        )
    )

    resolver = RuntimeJsonBodyResolver(planning_graph=graph)

    resolved = resolver.resolve(
        operation_context=build_yt_operation_context(),
        case={
            "test_type": "positive",
            "description": "Gửi request hợp lệ với URL YouTube hợp lệ",
        },
        explicit_json_body={},
    )

    assert resolved.value == {
        "data": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    }
    assert resolved.source == "synthesized_with_semantic_overrides"


def test_yt_invalid_should_send_integer_not_string_placeholder():
    graph = RuntimePayloadPlanningGraph(
        planner_service=FakePlannerService(
            PayloadPlan(
                trust_explicit_payload=False,
                base_payload_strategy="synthesize_from_schema",
                mutation_kind="invalid_type_or_format",
                target_field="data",
                field_overrides={"data": 12345},
                reason="data should be integer instead of string",
                confidence=0.99,
            )
        )
    )

    resolver = RuntimeJsonBodyResolver(planning_graph=graph)

    resolved = resolver.resolve(
        operation_context=build_yt_operation_context(),
        case={
            "test_type": "invalid_type_or_format",
            "description": "Gửi request với trường 'data' là số nguyên thay vì chuỗi",
        },
        explicit_json_body={},
    )

    assert resolved.value == {"data": 12345}
    assert resolved.source == "mutated_invalid_type_or_format"