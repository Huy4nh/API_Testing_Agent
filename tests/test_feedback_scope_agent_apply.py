from api_testing_agent.core.feedback_scope_models import FeedbackScopeDecision


def apply_feedback_scope(current_ops: list[dict], all_ops: list[dict], decision: FeedbackScopeDecision) -> list[dict]:
    def key(item: dict):
        return (
            str(item.get("operation_id", "")),
            str(item.get("path", "")),
            str(item.get("method", "")),
        )

    def resolve(decision: FeedbackScopeDecision) -> list[dict]:
        matched_ids = set(decision.matched_operation_ids)
        matched_paths = set(decision.matched_paths)
        matched_tags = {item.lower() for item in decision.matched_tags}

        resolved: list[dict] = []
        for item in all_ops:
            tags = {str(tag).lower() for tag in item.get("tags", [])}
            if matched_ids and item.get("operation_id") in matched_ids:
                resolved.append(item)
                continue
            if matched_paths and item.get("path") in matched_paths:
                resolved.append(item)
                continue
            if matched_tags and tags.intersection(matched_tags):
                resolved.append(item)
                continue
        return resolved

    if decision.action_mode == "reset_all":
        return all_ops

    if decision.action_mode == "replace_with_specific":
        return resolve(decision)

    if decision.action_mode == "add_specific":
        merged = list(current_ops)
        seen = {key(item) for item in merged}
        for item in resolve(decision):
            if key(item) not in seen:
                seen.add(key(item))
                merged.append(item)
        return merged

    if decision.action_mode == "remove_specific":
        remove_keys = {key(item) for item in resolve(decision)}
        return [item for item in current_ops if key(item) not in remove_keys]

    return current_ops


def build_ops():
    return [
        {"operation_id": "image_generate_img_post", "method": "POST", "path": "/img", "tags": ["image"]},
        {"operation_id": "fb_get_content_FB_post", "method": "POST", "path": "/FB", "tags": ["facebook"]},
        {"operation_id": "yt_get_content_YT_post", "method": "POST", "path": "/YT", "tags": ["youtube"]},
        {"operation_id": "x_post_post_x_post", "method": "POST", "path": "/post/x", "tags": ["x"]},
    ]


def test_replace_scope():
    result = apply_feedback_scope(
        current_ops=build_ops(),
        all_ops=build_ops(),
        decision=FeedbackScopeDecision(
            action_mode="replace_with_specific",
            matched_paths=["/img"],
            reason="replace",
        ),
    )
    assert [item["path"] for item in result] == ["/img"]


def test_add_scope():
    result = apply_feedback_scope(
        current_ops=[build_ops()[0]],
        all_ops=build_ops(),
        decision=FeedbackScopeDecision(
            action_mode="add_specific",
            matched_paths=["/YT", "/FB"],
            reason="add",
        ),
    )
    paths = [item["path"] for item in result]
    assert "/img" in paths
    assert "/YT" in paths
    assert "/FB" in paths


def test_remove_scope():
    result = apply_feedback_scope(
        current_ops=build_ops(),
        all_ops=build_ops(),
        decision=FeedbackScopeDecision(
            action_mode="remove_specific",
            matched_paths=["/YT", "/FB"],
            reason="remove",
        ),
    )
    paths = [item["path"] for item in result]
    assert "/img" in paths
    assert "/post/x" in paths
    assert "/YT" not in paths
    assert "/FB" not in paths