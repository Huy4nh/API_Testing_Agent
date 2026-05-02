from api_testing_agent.core.report_intent_agent import ReportIntentAgent
from api_testing_agent.core.report_interaction_models import ReportUserIntent


class FakeHybridAI:
    def decide_report_intent(
        self,
        *,
        thread_id: str,
        target_name: str | None,
        user_text: str,
        final_report_data: dict,
        current_markdown: str,
        messages: list[dict[str, str]],
    ) -> dict:
        lowered = user_text.strip().lower()

        if "dễ hiểu hơn" in lowered or "ngôn ngữ tự nhiên" in lowered:
            return {
                "intent": "revise_report_text",
                "confidence": 0.93,
                "reason": "Rewrite to natural language.",
                "revision_instruction": user_text,
                "rerun_instruction": None,
            }

        if "bạn đã sửa chỗ nào" in lowered:
            return {
                "intent": "ask_report_question",
                "confidence": 0.91,
                "reason": "User asks about changes.",
                "revision_instruction": None,
                "rerun_instruction": None,
            }

        return {
            "intent": "ask_report_question",
            "confidence": 0.55,
            "reason": "Fallback AI question.",
            "revision_instruction": None,
            "rerun_instruction": None,
        }


def test_report_intent_rule_finalize():
    agent = ReportIntentAgent(hybrid_ai=FakeHybridAI())
    decision = agent.detect("lưu")
    assert decision.intent == ReportUserIntent.FINALIZE_REPORT


def test_report_intent_hybrid_rewrite():
    agent = ReportIntentAgent(hybrid_ai=FakeHybridAI())
    decision = agent.detect(
        "cho tôi bản dễ hiểu hơn bằng ngôn ngữ tự nhiên",
        state={
            "thread_id": "thread-001",
            "target_name": "img_api_staging",
            "final_report_data": {"summary": {}},
            "final_report_markdown": "# demo",
            "messages": [],
        },
    )
    assert decision.intent == ReportUserIntent.REVISE_REPORT_TEXT
    assert decision.revision_instruction is not None


def test_report_intent_hybrid_question():
    agent = ReportIntentAgent(hybrid_ai=FakeHybridAI())
    decision = agent.detect(
        "bạn đã sửa chỗ nào thế",
        state={
            "thread_id": "thread-001",
            "target_name": "img_api_staging",
            "final_report_data": {"summary": {}},
            "final_report_markdown": "# demo",
            "messages": [],
        },
    )
    assert decision.intent == ReportUserIntent.ASK_REPORT_QUESTION