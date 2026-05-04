from __future__ import annotations

from typing import Any, cast

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from api_testing_agent.core.report_interaction_graph import (
    build_report_interaction_graph,
    report_graph_config,
)
from api_testing_agent.core.report_interaction_models import (
    ReportIntentDecision,
    ReportInteractionState,
    ReportUserIntent,
)
from api_testing_agent.core.report_intent_agent import ReportIntentAgent
from api_testing_agent.core.reporter.interactive.interactive_report_service import (
    InteractiveReportService,
)

class StubIntentAgent:
    def __init__(self, decisions: dict[str, ReportIntentDecision]) -> None:
        self._decisions = decisions
        self.calls: list[str] = []

    def detect(
        self,
        message: str,
        state: ReportInteractionState | dict[str, Any] | None = None,
    ) -> ReportIntentDecision:
        self.calls.append(message)
        return self._decisions.get(
            message,
            ReportIntentDecision(
                intent=ReportUserIntent.ASK_REPORT_QUESTION,
                confidence=0.8,
                reason="Default question fallback in test stub.",
            ),
        )


class StubReportService:
    def __init__(self) -> None:
        self.last_revision_instruction: str | None = None
        self.last_rerun_basis: str | None = None
        self.persist_calls = 0

    def initialize_session(self, state: ReportInteractionState) -> dict[str, Any]:
        return {
            "assistant_response": "Đã mở phiên tương tác report.",
            "artifact_paths": list(state.get("artifact_paths", [])),
        }

    def persist_session_snapshot(self, state: dict[str, Any]) -> dict[str, Any]:
        self.persist_calls += 1
        return {}

    def answer_question(
        self,
        state: ReportInteractionState,
        user_message: str,
    ) -> dict[str, Any]:
        return {
            "assistant_response": f"Q&A::{user_message}",
        }

    def revise_report_text(
        self,
        state: ReportInteractionState,
        revision_instruction: str,
    ) -> dict[str, Any]:
        self.last_revision_instruction = revision_instruction
        return {
            "assistant_response": f"REWRITE::{revision_instruction}",
            "final_report_markdown": f"rewritten::{revision_instruction}",
        }

    def share_report(self, state: ReportInteractionState) -> dict[str, Any]:
        return {
            "assistant_response": "SHARE::done",
            "shareable_summary": "shareable-summary",
        }

    def build_rerun_request_text(
        self,
        state: ReportInteractionState,
        rerun_basis: str,
    ) -> str:
        self.last_rerun_basis = rerun_basis
        return f"RERUN::{rerun_basis}"

    def finalize_session(self, state: ReportInteractionState) -> dict[str, Any]:
        return {
            "assistant_response": "FINALIZED::done",
            "finalized": True,
            "cancelled": False,
            "final_report_json_path": "reports/final.json",
            "final_report_md_path": "reports/final.md",
        }

    def cancel_session(self, state: ReportInteractionState) -> dict[str, Any]:
        return {
            "assistant_response": "CANCELLED::done",
            "cancelled": True,
            "finalized": False,
        }


def _make_initial_state(thread_id: str = "thread-report-1") -> ReportInteractionState:
    return {
        "thread_id": thread_id,
        "target_name": "img_local",
        "preferred_language": "vi",
        "original_request": "test target img_local",
        "canonical_command": "test target img_local /img POST",
        "understanding_explanation": "Initial understanding",
        "candidate_targets": ["img_local"],
        "target_selection_question": None,
        "review_feedback_history": [],
        "draft_report_json_path": "reports/draft.json",
        "draft_report_md_path": "reports/draft.md",
        "execution_report_json_path": "reports/execution.json",
        "execution_report_md_path": "reports/execution.md",
        "validation_report_json_path": "reports/validation.json",
        "validation_report_md_path": "reports/validation.md",
        "staged_final_report_json_path": "reports/staged_final.json",
        "staged_final_report_md_path": "reports/staged_final.md",
        "final_report_json_path": None,
        "final_report_md_path": None,
        "final_report_markdown": "# Final report\n\nInitial content",
        "final_report_data": {
            "summary": {
                "thread_id": thread_id,
                "target_name": "img_local",
            }
        },
        "execution_batch_result": {},
        "validation_batch_result": {},
        "messages": [],
        "latest_user_message": "",
        "assistant_response": "",
        "shareable_summary": None,
        "last_intent": "",
        "last_intent_reason": "",
        "last_intent_confidence": 0.0,
        "pending_revision_instruction": None,
        "pending_rerun_instruction": None,
        "artifact_paths": [],
        "finalized": False,
        "cancelled": False,
        "rerun_requested": False,
        "rerun_user_text": None,
    }


def _build_graph(
    *,
    decisions: dict[str, ReportIntentDecision],
):
    intent_agent = StubIntentAgent(decisions)
    report_service = StubReportService()
    graph = build_report_interaction_graph(
        intent_agent=cast(ReportIntentAgent, intent_agent),
        report_service=cast(InteractiveReportService, report_service),
        checkpointer=InMemorySaver(),
    )
    return graph, intent_agent, report_service


def test_revise_report_text_uses_structured_revision_instruction() -> None:
    graph, _intent_agent, report_service = _build_graph(
        decisions={
            "làm report dễ hiểu hơn đi": ReportIntentDecision(
                intent=ReportUserIntent.REVISE_REPORT_TEXT,
                confidence=0.91,
                reason="User wants rewrite.",
                revision_instruction="Viết lại report ngắn gọn, tự nhiên, dễ hiểu hơn.",
            )
        }
    )

    thread_id = "rewrite-thread"
    config = report_graph_config(thread_id)
    graph.invoke(_make_initial_state(thread_id), config=config)

    graph.invoke(
        Command(resume={"message": "làm report dễ hiểu hơn đi"}),
        config=config,
    )

    snapshot = graph.get_state(config)
    values = dict(snapshot.values)

    assert report_service.last_revision_instruction == (
        "Viết lại report ngắn gọn, tự nhiên, dễ hiểu hơn."
    )
    assert values["finalized"] is False
    assert values["cancelled"] is False
    assert values["pending_revision_instruction"] is None
    assert "REWRITE::Viết lại report ngắn gọn, tự nhiên, dễ hiểu hơn." in str(
        values.get("assistant_response", "")
    )
    assert "rewritten::Viết lại report ngắn gọn, tự nhiên, dễ hiểu hơn." in str(
        values.get("final_report_markdown", "")
    )


def test_finalize_low_confidence_requires_confirmation_then_finalizes() -> None:
    graph, intent_agent, _report_service = _build_graph(
        decisions={
            "ok lưu đi": ReportIntentDecision(
                intent=ReportUserIntent.FINALIZE_REPORT,
                confidence=0.72,
                reason="Looks like finalize, but not confident enough to auto-run.",
            )
        }
    )

    thread_id = "finalize-thread"
    config = report_graph_config(thread_id)
    graph.invoke(_make_initial_state(thread_id), config=config)

    graph.invoke(
        Command(resume={"message": "ok lưu đi"}),
        config=config,
    )

    snapshot = graph.get_state(config)
    values = dict(snapshot.values)

    assert values["finalized"] is False
    assert values["cancelled"] is False
    assert values["last_intent"] == "awaiting_confirm_finalize"
    assert "xác nhận finalize" in str(values.get("assistant_response", "")).lower()

    graph.invoke(
        Command(resume={"message": "đồng ý"}),
        config=config,
    )

    snapshot = graph.get_state(config)
    values = dict(snapshot.values)

    assert values["finalized"] is True
    assert values["cancelled"] is False
    assert values["final_report_json_path"] == "reports/final.json"
    assert values["final_report_md_path"] == "reports/final.md"
    assert "FINALIZED::done" in str(values.get("assistant_response", ""))
    assert intent_agent.calls == ["ok lưu đi"]


def test_cancel_low_confidence_requires_confirmation_then_cancels() -> None:
    graph, intent_agent, _report_service = _build_graph(
        decisions={
            "hủy report này đi": ReportIntentDecision(
                intent=ReportUserIntent.CANCEL_REPORT,
                confidence=0.75,
                reason="Looks like cancel, but not confident enough to auto-run.",
            )
        }
    )

    thread_id = "cancel-thread"
    config = report_graph_config(thread_id)
    graph.invoke(_make_initial_state(thread_id), config=config)

    graph.invoke(
        Command(resume={"message": "hủy report này đi"}),
        config=config,
    )

    snapshot = graph.get_state(config)
    values = dict(snapshot.values)

    assert values["cancelled"] is False
    assert values["finalized"] is False
    assert values["last_intent"] == "awaiting_confirm_cancel"
    assert "xác nhận hủy" in str(values.get("assistant_response", "")).lower()

    graph.invoke(
        Command(resume={"message": "đồng ý"}),
        config=config,
    )

    snapshot = graph.get_state(config)
    values = dict(snapshot.values)

    assert values["cancelled"] is True
    assert values["finalized"] is False
    assert "CANCELLED::done" in str(values.get("assistant_response", ""))
    assert intent_agent.calls == ["hủy report này đi"]


def test_declining_destructive_confirmation_returns_to_interaction() -> None:
    graph, _intent_agent, _report_service = _build_graph(
        decisions={
            "ok lưu đi": ReportIntentDecision(
                intent=ReportUserIntent.FINALIZE_REPORT,
                confidence=0.73,
                reason="Looks like finalize, but not confident enough to auto-run.",
            )
        }
    )

    thread_id = "decline-thread"
    config = report_graph_config(thread_id)
    graph.invoke(_make_initial_state(thread_id), config=config)

    graph.invoke(
        Command(resume={"message": "ok lưu đi"}),
        config=config,
    )

    graph.invoke(
        Command(resume={"message": "không"}),
        config=config,
    )

    snapshot = graph.get_state(config)
    values = dict(snapshot.values)

    assert values["finalized"] is False
    assert values["cancelled"] is False
    assert values["last_intent"] == ReportUserIntent.UNKNOWN.value
    assert "sẽ không thực hiện thao tác đó" in str(
        values.get("assistant_response", "")
    ).lower()


def test_prepare_rerun_uses_structured_rerun_instruction() -> None:
    graph, _intent_agent, report_service = _build_graph(
        decisions={
            "chạy lại nhưng chỉ test POST /img": ReportIntentDecision(
                intent=ReportUserIntent.REVISE_AND_RERUN,
                confidence=0.9,
                reason="User wants to rerun with narrower scope.",
                rerun_instruction="Chỉ giữ lại operation POST /img rồi chạy lại.",
            )
        }
    )

    thread_id = "rerun-thread"
    config = report_graph_config(thread_id)
    graph.invoke(_make_initial_state(thread_id), config=config)

    graph.invoke(
        Command(resume={"message": "chạy lại nhưng chỉ test POST /img"}),
        config=config,
    )

    snapshot = graph.get_state(config)
    values = dict(snapshot.values)

    assert report_service.last_rerun_basis == "Chỉ giữ lại operation POST /img rồi chạy lại."
    assert values["rerun_requested"] is True
    assert values["rerun_user_text"] == "RERUN::Chỉ giữ lại operation POST /img rồi chạy lại."
    assert values["finalized"] is False
    assert values["cancelled"] is False