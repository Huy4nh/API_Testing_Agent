from api_testing_agent.core.feedback_scope_models import FeedbackScopeDecision
from api_testing_agent.core.feedback_scope_refiner import FeedbackScopeRefiner


class FakeFeedbackScopeAgent:
    def decide(self, *, feedback_text: str, target_name: str, all_operation_hints: list[dict], current_scope_hints: list[dict]):
        lowered = feedback_text.lower()

        if "chỉ test sinh ảnh" in lowered or "chi test sinh anh" in lowered:
            return FeedbackScopeDecision(
                action_mode="replace_with_specific",
                matched_operation_ids=["image_generate_img_post"],
                reason="Replace current scope with image generation only.",
            )

        if "thêm post bài" in lowered:
            return FeedbackScopeDecision(
                action_mode="add_specific",
                matched_paths=["/post/x"],
                reason="Add post operation into current scope.",
            )

        if "bỏ yt với fb đi" in lowered or "bỏ youtube với facebook đi" in lowered:
            return FeedbackScopeDecision(
                action_mode="remove_specific",
                matched_paths=["/YT", "/FB"],
                reason="Remove YT and FB operations from current scope.",
            )

        if "test lại toàn bộ" in lowered or "quay lại toàn bộ" in lowered:
            return FeedbackScopeDecision(
                action_mode="reset_all",
                reason="Reset scope back to all operations.",
            )

        return FeedbackScopeDecision(
            action_mode="keep",
            reason="No scope change.",
        )


def build_all_ops():
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
        {
            "operation_id": "x_post_post_x_post",
            "method": "POST",
            "path": "/post/x",
            "tags": ["x"],
            "summary": "Post to X",
        },
    ]


def test_replace_scope_with_image_only():
    refiner = FeedbackScopeRefiner(FakeFeedbackScopeAgent())

    result = refiner.refine(
        target_name="hello_work",
        current_operation_contexts=build_all_ops(),
        all_operation_contexts=build_all_ops(),
        feedback_history=["chỉ test sinh ảnh"],
    )

    assert len(result.operation_contexts) == 1
    assert result.operation_contexts[0]["path"] == "/img"


def test_add_scope_with_post_x():
    refiner = FeedbackScopeRefiner(FakeFeedbackScopeAgent())

    current = [
        build_all_ops()[0],  # /img
    ]

    result = refiner.refine(
        target_name="hello_work",
        current_operation_contexts=current,
        all_operation_contexts=build_all_ops(),
        feedback_history=["thêm post bài nữa"],
    )

    paths = [item["path"] for item in result.operation_contexts]
    assert "/img" in paths
    assert "/post/x" in paths
    assert len(paths) == 2


def test_remove_scope_for_yt_and_fb():
    refiner = FeedbackScopeRefiner(FakeFeedbackScopeAgent())

    result = refiner.refine(
        target_name="hello_work",
        current_operation_contexts=build_all_ops(),
        all_operation_contexts=build_all_ops(),
        feedback_history=["bỏ YT với FB đi"],
    )

    paths = [item["path"] for item in result.operation_contexts]
    assert "/img" in paths
    assert "/post/x" in paths
    assert "/FB" not in paths
    assert "/YT" not in paths


def test_reset_scope_to_all():
    refiner = FeedbackScopeRefiner(FakeFeedbackScopeAgent())

    current = [
        build_all_ops()[0],  # /img
    ]

    result = refiner.refine(
        target_name="hello_work",
        current_operation_contexts=current,
        all_operation_contexts=build_all_ops(),
        feedback_history=["test lại toàn bộ"],
    )

    assert len(result.operation_contexts) == 4