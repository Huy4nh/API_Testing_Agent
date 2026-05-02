from api_testing_agent.core.report_intent_agent import ReportIntentAgent
from api_testing_agent.core.report_interaction_models import ReportUserIntent


def test_detect_finalize():
    agent = ReportIntentAgent()
    decision = agent.detect("ok lưu đi")
    assert decision.intent == ReportUserIntent.FINALIZE_REPORT


def test_detect_cancel():
    agent = ReportIntentAgent()
    decision = agent.detect("hủy hết")
    assert decision.intent == ReportUserIntent.CANCEL_REPORT


def test_detect_rerun():
    agent = ReportIntentAgent()
    decision = agent.detect("bỏ unauthorized rồi chạy lại")
    assert decision.intent == ReportUserIntent.REVISE_AND_RERUN
    assert decision.rerun_instruction is not None


def test_detect_revise_report_text():
    agent = ReportIntentAgent()
    decision = agent.detect("viết lại report gọn hơn")
    assert decision.intent == ReportUserIntent.REVISE_REPORT_TEXT
    assert decision.revision_instruction is not None


def test_detect_question():
    agent = ReportIntentAgent()
    decision = agent.detect("vì sao case này fail?")
    assert decision.intent == ReportUserIntent.ASK_REPORT_QUESTION