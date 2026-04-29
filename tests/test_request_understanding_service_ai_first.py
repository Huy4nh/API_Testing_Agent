from api_testing_agent.core.models import HttpMethod, TestType
from api_testing_agent.core.request_understanding_service import (
    InvalidFunctionRequestError,
    RequestUnderstandingService,
)
from api_testing_agent.core.scope_resolution_models import ScopeResolutionDecision


class FakeScopeResolutionAgent:
    def __init__(self, decision: ScopeResolutionDecision) -> None:
        self._decision = decision

    def decide(self, *, raw_text: str, target_name: str, operation_hints: list[dict]):
        return self._decision


def build_operation_hints():
    return [
        {
            "operation_id": "image_generate_img_post",
            "method": "POST",
            "path": "/img",
            "tags": ["image"],
            "summary": "Generate image",
        },
        {
            "operation_id": "fb_get_content_FB_post",
            "method": "POST",
            "path": "/FB",
            "tags": ["facebook"],
            "summary": "Generate Facebook content",
        },
        {
            "operation_id": "yt_get_content_YT_post",
            "method": "POST",
            "path": "/YT",
            "tags": ["youtube"],
            "summary": "Generate YouTube content",
        },
    ]


def test_general_request_without_specific_function_becomes_all_scope():
    service = RequestUnderstandingService(
        scope_resolution_agent=FakeScopeResolutionAgent(
            ScopeResolutionDecision(
                scope_mode="all",
                reason="User did not specify any concrete function.",
            )
        ),
    )

    result = service.understand(
        "hãy test hello cho tôi",
        forced_target_name="hello_world",
        operation_hints=build_operation_hints(),
    )

    assert result.canonical_command == "test target hello_world positive unauthorized not_found missing invalid"
    assert result.plan.target_name == "hello_world"
    assert result.plan.paths == []
    assert result.plan.tags == []
    assert result.plan.methods == []
    assert TestType.POSITIVE in result.plan.test_types
    assert "test toàn bộ chức năng" in result.explanation


def test_specific_function_request_maps_to_exact_operation():
    service = RequestUnderstandingService(
        scope_resolution_agent=FakeScopeResolutionAgent(
            ScopeResolutionDecision(
                scope_mode="specific",
                matched_operation_ids=["image_generate_img_post"],
                matched_paths=["/img"],
                matched_tags=[],
                reason="User explicitly requested the image generation function.",
            )
        ),
    )

    result = service.understand(
        "hãy test chức năng sinh ảnh của hello_world",
        forced_target_name="hello_world",
        operation_hints=build_operation_hints(),
    )

    assert result.canonical_command == "test target hello_world /img POST positive unauthorized not_found missing invalid"
    assert result.plan.target_name == "hello_world"
    assert result.plan.paths == ["/img"]
    assert result.plan.methods == [HttpMethod.POST]
    assert "match đúng chức năng cụ thể" in result.explanation


def test_invalid_function_request_raises_and_returns_available_functions():
    service = RequestUnderstandingService(
        scope_resolution_agent=FakeScopeResolutionAgent(
            ScopeResolutionDecision(
                scope_mode="invalid_function",
                invalid_requested_function="payment",
                reason="User requested payment but target has no payment operation.",
            )
        ),
    )

    try:
        service.understand(
            "hãy test chức năng payment của hello_world",
            forced_target_name="hello_world",
            operation_hints=build_operation_hints(),
        )
        assert False, "Expected InvalidFunctionRequestError"
    except InvalidFunctionRequestError as exc:
        assert "payment" in str(exc)
        assert len(exc.available_functions) == 3
        assert "POST /img" in exc.available_functions[0]