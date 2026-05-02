from __future__ import annotations

from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from api_testing_agent.core.report_intent_agent import ReportIntentAgent
from api_testing_agent.core.report_interaction_models import (
    ReportInteractionState,
    ReportSessionResult,
    ReportUserIntent,
)
from api_testing_agent.core.reporter.interactive.interactive_report_service import (
    InteractiveReportService,
)
from api_testing_agent.logging_config import bind_logger, get_logger


def build_report_interaction_graph(
    *,
    intent_agent: ReportIntentAgent,
    report_service: InteractiveReportService,
    checkpointer: Any,
):
    logger = get_logger(__name__)

    def bootstrap_session(state: ReportInteractionState) -> ReportInteractionState:
        thread_id = str(state.get("thread_id", ""))
        target_name = str(state.get("target_name", ""))

        node_logger = bind_logger(
            logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="report_graph_bootstrap",
        )
        node_logger.info("Bootstrapping final-report interaction session.")

        updates = report_service.initialize_session(state)
        merged = _merge_state_with_assistant_message(state, updates)

        snapshot_updates = report_service.persist_session_snapshot(merged)
        merged.update(snapshot_updates)

        return cast(ReportInteractionState, merged)

    def wait_for_user_message(state: ReportInteractionState) -> ReportInteractionState:
        prompt_payload = {
            "assistant_response": state.get("assistant_response", ""),
            "finalized": bool(state.get("finalized", False)),
            "cancelled": bool(state.get("cancelled", False)),
        }

        resumed = interrupt(prompt_payload)

        if isinstance(resumed, dict):
            latest_message = str(resumed.get("message", "")).strip()
        else:
            latest_message = str(resumed).strip()

        messages = list(state.get("messages", []))
        messages.append({"role": "user", "content": latest_message})

        updated_state = dict(state)
        updated_state["latest_user_message"] = latest_message
        updated_state["messages"] = messages

        return cast(ReportInteractionState, updated_state)

    def detect_intent(state: ReportInteractionState) -> ReportInteractionState:
        latest_user_message = str(state.get("latest_user_message", ""))
        decision = intent_agent.detect(latest_user_message, state)

        updated_state = dict(state)
        updated_state["last_intent"] = decision.intent.value
        updated_state["last_intent_reason"] = decision.reason
        updated_state["last_intent_confidence"] = decision.confidence

        if decision.revision_instruction:
            updated_state["pending_revision_instruction"] = decision.revision_instruction

        return cast(ReportInteractionState, updated_state)

    def answer_question(state: ReportInteractionState) -> ReportInteractionState:
        updates = report_service.answer_question(
            state,
            str(state.get("latest_user_message", "")),
        )
        merged = _merge_state_with_assistant_message(state, updates)
        snapshot_updates = report_service.persist_session_snapshot(merged)
        merged.update(snapshot_updates)
        return cast(ReportInteractionState, merged)

    def revise_report_text(state: ReportInteractionState) -> ReportInteractionState:
        updates = report_service.revise_report_text(
            state,
            str(state.get("latest_user_message", "")),
        )
        merged = _merge_state_with_assistant_message(state, updates)
        snapshot_updates = report_service.persist_session_snapshot(merged)
        merged.update(snapshot_updates)
        return cast(ReportInteractionState, merged)

    def share_report(state: ReportInteractionState) -> ReportInteractionState:
        updates = report_service.share_report(state)
        merged = _merge_state_with_assistant_message(state, updates)
        snapshot_updates = report_service.persist_session_snapshot(merged)
        merged.update(snapshot_updates)
        return cast(ReportInteractionState, merged)

    def prepare_rerun(state: ReportInteractionState) -> ReportInteractionState:
        rerun_user_text = report_service.build_rerun_request_text(
            state,
            str(state.get("latest_user_message", "")),
        )

        updates = {
            "rerun_requested": True,
            "rerun_user_text": rerun_user_text,
            "assistant_response": (
                "Tôi hiểu đây là yêu cầu sửa phạm vi kiểm thử để chạy lại. "
                "Tôi đã chuẩn bị `rerun_user_text` để handoff về review flow."
            ),
        }

        merged = _merge_state_with_assistant_message(state, updates)
        snapshot_updates = report_service.persist_session_snapshot(merged)
        merged.update(snapshot_updates)
        return cast(ReportInteractionState, merged)

    def finalize_session(state: ReportInteractionState) -> ReportInteractionState:
        updates = report_service.finalize_session(state)
        merged = _merge_state_with_assistant_message(state, updates)
        return cast(ReportInteractionState, merged)

    def cancel_session(state: ReportInteractionState) -> ReportInteractionState:
        updates = report_service.cancel_session(state)
        merged = _merge_state_with_assistant_message(state, updates)
        return cast(ReportInteractionState, merged)

    def route_after_intent(state: ReportInteractionState) -> str:
        raw_intent = str(state.get("last_intent", ReportUserIntent.UNKNOWN.value))

        if raw_intent == ReportUserIntent.CANCEL_REPORT.value:
            return "cancel_session"

        if raw_intent == ReportUserIntent.FINALIZE_REPORT.value:
            return "finalize_session"

        if raw_intent == ReportUserIntent.SHARE_REPORT.value:
            return "share_report"

        if raw_intent == ReportUserIntent.REVISE_AND_RERUN.value:
            return "prepare_rerun"

        if raw_intent == ReportUserIntent.REVISE_REPORT_TEXT.value:
            return "revise_report_text"

        return "answer_question"

    builder = StateGraph(ReportInteractionState)

    builder.add_node("bootstrap_session", bootstrap_session)
    builder.add_node("wait_for_user_message", wait_for_user_message)
    builder.add_node("detect_intent", detect_intent)
    builder.add_node("answer_question", answer_question)
    builder.add_node("revise_report_text", revise_report_text)
    builder.add_node("share_report", share_report)
    builder.add_node("prepare_rerun", prepare_rerun)
    builder.add_node("finalize_session", finalize_session)
    builder.add_node("cancel_session", cancel_session)

    builder.set_entry_point("bootstrap_session")

    builder.add_edge("bootstrap_session", "wait_for_user_message")
    builder.add_edge("wait_for_user_message", "detect_intent")

    builder.add_conditional_edges(
        "detect_intent",
        route_after_intent,
        {
            "answer_question": "answer_question",
            "revise_report_text": "revise_report_text",
            "share_report": "share_report",
            "prepare_rerun": "prepare_rerun",
            "finalize_session": "finalize_session",
            "cancel_session": "cancel_session",
        },
    )

    builder.add_edge("answer_question", "wait_for_user_message")
    builder.add_edge("revise_report_text", "wait_for_user_message")
    builder.add_edge("share_report", "wait_for_user_message")

    builder.add_edge("prepare_rerun", END)
    builder.add_edge("finalize_session", END)
    builder.add_edge("cancel_session", END)

    return builder.compile(checkpointer=checkpointer)


def report_graph_config(thread_id: str) -> RunnableConfig:
    return cast(
        RunnableConfig,
        {"configurable": {"thread_id": f"report::{thread_id}"}},
    )


def _merge_state_with_assistant_message(
    state: ReportInteractionState,
    updates: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(state)
    merged.update(updates)

    assistant_response = str(updates.get("assistant_response", "")).strip()
    messages = list(state.get("messages", []))

    if assistant_response:
        messages.append({"role": "assistant", "content": assistant_response})

    merged["messages"] = messages
    return merged