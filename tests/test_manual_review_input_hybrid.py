from api_testing_agent.manual_test.report_testcase.manual_review_workflow_test import (
    _normalize_review_input,
)


class FakeHybridAI:
    def decide_review_action(
        self,
        *,
        thread_id: str,
        target_name: str | None,
        user_text: str,
        preview_text: str,
        feedback_history: list[str],
    ) -> dict:
        lowered = user_text.strip().lower()

        if lowered == "tốt rồi":
            return {
                "action": "approve",
                "feedback": "",
                "confidence": 0.94,
                "reason": "Natural confirmation.",
            }

        if lowered == "thêm yt vào":
            return {
                "action": "revise",
                "feedback": "thêm yt vào",
                "confidence": 0.96,
                "reason": "Scope expansion request.",
            }

        return {
            "action": "revise",
            "feedback": user_text,
            "confidence": 0.60,
            "reason": "Fallback revise.",
        }


def test_normalize_review_input_fuzzy_approve():
    action, feedback = _normalize_review_input(
        "aprrove",
        hybrid_ai=None,
    )
    assert action == "approve"
    assert feedback == ""


def test_normalize_review_input_hybrid_good_enough():
    action, feedback = _normalize_review_input(
        "tốt rồi",
        hybrid_ai=FakeHybridAI(),
        thread_id="thread-001",
        target_name="img_api_staging",
        preview_text="preview",
        feedback_history=[],
    )
    assert action == "approve"
    assert feedback == ""


def test_normalize_review_input_hybrid_revise_scope():
    action, feedback = _normalize_review_input(
        "thêm yt vào",
        hybrid_ai=FakeHybridAI(),
        thread_id="thread-001",
        target_name="img_api_staging",
        preview_text="preview",
        feedback_history=[],
    )
    assert action == "revise"
    assert feedback == "thêm yt vào"