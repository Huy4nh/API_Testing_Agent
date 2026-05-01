from api_testing_agent.core.payload_plan_models import PayloadPlan
from api_testing_agent.core.request_runtime_builder import RequestRuntimeBuilder
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
                    "data": {"type": "string"}
                },
            },
        },
        "responses": {"200": {"description": "OK"}},
    }


def test_builder_should_keep_semantic_override_for_yt_positive():
    graph = RuntimePayloadPlanningGraph(
        planner_service=FakePlannerService(
            PayloadPlan(
                trust_explicit_payload=False,
                base_payload_strategy="synthesize_from_schema",
                mutation_kind="semantic_positive",
                field_overrides={
                    "data": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                },
                reason="Use actual YouTube URL",
                confidence=0.98,
            )
        )
    )

    resolver = RuntimeJsonBodyResolver(planning_graph=graph)
    builder = RequestRuntimeBuilder(json_body_resolver=resolver)

    request = builder.build(
        target={"base_url": "https://example.com"},
        target_name="img_local",
        operation_context=build_yt_operation_context(),
        case={
            "test_type": "positive",
            "description": "Gửi request hợp lệ với URL YouTube hợp lệ",
            "expected_status_codes": [200],
            "json_body": {},
        },
        case_index=1,
    )

    assert request.final_url == "https://example.com/YT"
    assert request.final_json_body == {
        "data": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    }
    assert request.payload_source == "synthesized_with_semantic_overrides"
    assert request.planner_reason == "Use actual YouTube URL"
    assert request.planner_confidence == 0.98


def test_builder_should_keep_integer_override_for_string_field_invalid_case():
    graph = RuntimePayloadPlanningGraph(
        planner_service=FakePlannerService(
            PayloadPlan(
                trust_explicit_payload=False,
                base_payload_strategy="synthesize_from_schema",
                mutation_kind="invalid_type_or_format",
                target_field="data",
                field_overrides={"data": 12345},
                reason="Use integer to violate string field",
                confidence=0.99,
            )
        )
    )

    resolver = RuntimeJsonBodyResolver(planning_graph=graph)
    builder = RequestRuntimeBuilder(json_body_resolver=resolver)

    request = builder.build(
        target={"base_url": "https://example.com"},
        target_name="img_local",
        operation_context=build_yt_operation_context(),
        case={
            "test_type": "invalid_type_or_format",
            "description": "Gửi request với trường 'data' là số nguyên thay vì chuỗi",
            "expected_status_codes": [422],
            "json_body": {},
        },
        case_index=2,
    )

    assert request.final_json_body == {"data": 12345}
    assert request.payload_source == "mutated_invalid_type_or_format"
    assert request.planner_reason == "Use integer to violate string field"
    assert request.planner_confidence == 0.99