from __future__ import annotations

from typing import Any, Literal, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from api_testing_agent.core.report_intent_agent import ReportIntentAgent
from api_testing_agent.core.report_interaction_models import (
    ReportInteractionState,
    ReportUserIntent,
)
from api_testing_agent.core.reporter.interactive.interactive_report_service import (
    InteractiveReportService,
)
from api_testing_agent.logging_config import bind_logger, get_logger


_AWAIT_CONFIRM_CANCEL = "awaiting_confirm_cancel"
_AWAIT_CONFIRM_FINALIZE = "awaiting_confirm_finalize"
_CONFIRMATION_DECLINED = "confirmation_declined"


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
        merged = _persist_snapshot(report_service, merged)
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

        updated_state["pending_revision_instruction"] = None
        updated_state["pending_rerun_instruction"] = None
        updated_state["assistant_response"] = ""

        return cast(ReportInteractionState, updated_state)

    def detect_intent(state: ReportInteractionState) -> ReportInteractionState:
        latest_user_message = str(state.get("latest_user_message", "")).strip()
        preferred_language = str(state.get("preferred_language", "vi"))

        updated_state = dict(state)

        pending_confirmation_kind = _get_pending_confirmation_kind(state)
        if pending_confirmation_kind is not None:
            confirmation = _classify_confirmation_reply(latest_user_message)

            if confirmation == "yes":
                resolved_intent = (
                    ReportUserIntent.CANCEL_REPORT
                    if pending_confirmation_kind == "cancel"
                    else ReportUserIntent.FINALIZE_REPORT
                )
                updated_state["last_intent"] = resolved_intent.value
                updated_state["last_intent_reason"] = _localize(
                    preferred_language,
                    "Người dùng đã xác nhận thao tác phá huỷ sau bước hỏi lại.",
                    "The user confirmed the destructive action after the confirmation step.",
                )
                updated_state["last_intent_confidence"] = 1.0
                return cast(ReportInteractionState, updated_state)

            if confirmation == "no":
                updated_state["last_intent"] = _CONFIRMATION_DECLINED
                updated_state["last_intent_reason"] = _localize(
                    preferred_language,
                    "Người dùng đã từ chối thao tác phá huỷ.",
                    "The user declined the destructive action.",
                )
                updated_state["last_intent_confidence"] = 1.0
                return cast(ReportInteractionState, updated_state)

            updated_state["last_intent"] = (
                _AWAIT_CONFIRM_CANCEL
                if pending_confirmation_kind == "cancel"
                else _AWAIT_CONFIRM_FINALIZE
            )
            updated_state["last_intent_reason"] = _localize(
                preferred_language,
                "Phản hồi xác nhận chưa đủ rõ, cần hỏi lại ngắn gọn.",
                "The confirmation reply is still unclear, so a brief clarification is needed.",
            )
            updated_state["last_intent_confidence"] = 0.5
            return cast(ReportInteractionState, updated_state)

        decision = intent_agent.detect(latest_user_message, state)

        updated_state["last_intent"] = decision.intent.value
        updated_state["last_intent_reason"] = decision.reason
        updated_state["last_intent_confidence"] = decision.confidence
        updated_state["pending_revision_instruction"] = decision.revision_instruction
        updated_state["pending_rerun_instruction"] = decision.rerun_instruction

        if _should_confirm_destructive_action(
            intent=decision.intent,
            confidence=decision.confidence,
        ):
            updated_state["last_intent"] = (
                _AWAIT_CONFIRM_CANCEL
                if decision.intent == ReportUserIntent.CANCEL_REPORT
                else _AWAIT_CONFIRM_FINALIZE
            )
            updated_state["last_intent_reason"] = decision.reason
            updated_state["last_intent_confidence"] = decision.confidence

        return cast(ReportInteractionState, updated_state)

    def confirm_destructive_action(state: ReportInteractionState) -> ReportInteractionState:
        preferred_language = str(state.get("preferred_language", "vi"))
        last_intent = str(state.get("last_intent", ""))

        if last_intent == _AWAIT_CONFIRM_CANCEL:
            assistant_response = _localize(
                preferred_language,
                "Tôi hiểu là bạn có thể muốn **hủy** phiên report hiện tại. Bạn xác nhận hủy chứ? Trả lời `đồng ý` hoặc `không`.",
                "I understand that you may want to **cancel** the current report session. Do you want to cancel it? Reply with `yes` or `no`.",
            )
        else:
            assistant_response = _localize(
                preferred_language,
                "Tôi hiểu là bạn có thể muốn **chốt/lưu** report hiện tại. Bạn xác nhận finalize chứ? Trả lời `đồng ý` hoặc `không`.",
                "I understand that you may want to **finalize/save** the current report. Do you want to finalize it? Reply with `yes` or `no`.",
            )

        merged = dict(state)
        merged["assistant_response"] = assistant_response
        merged = _merge_state_with_assistant_message(
            cast(ReportInteractionState, merged),
            {"assistant_response": assistant_response},
        )
        merged = _persist_snapshot(report_service, merged)
        return cast(ReportInteractionState, merged)

    def confirmation_declined(state: ReportInteractionState) -> ReportInteractionState:
        preferred_language = str(state.get("preferred_language", "vi"))

        assistant_response = _localize(
            preferred_language,
            "Được rồi, tôi sẽ không thực hiện thao tác đó. Bạn muốn tôi làm gì tiếp với report này?",
            "Understood. I will not perform that action. What would you like me to do next with this report?",
        )

        merged = dict(state)
        merged["assistant_response"] = assistant_response
        merged["last_intent"] = ReportUserIntent.UNKNOWN.value
        merged["last_intent_reason"] = _localize(
            preferred_language,
            "Đã hủy thao tác phá huỷ sau khi người dùng từ chối xác nhận.",
            "The destructive action was abandoned after the user declined confirmation.",
        )
        merged["last_intent_confidence"] = 1.0
        merged = _merge_state_with_assistant_message(
            cast(ReportInteractionState, merged),
            {"assistant_response": assistant_response},
        )
        merged = _persist_snapshot(report_service, merged)
        return cast(ReportInteractionState, merged)

    def answer_question(state: ReportInteractionState) -> ReportInteractionState:
        updates = report_service.answer_question(
            state,
            str(state.get("latest_user_message", "")),
        )
        merged = _merge_state_with_assistant_message(state, updates)
        merged = _persist_snapshot(report_service, merged)
        return cast(ReportInteractionState, merged)

    def revise_report_text(state: ReportInteractionState) -> ReportInteractionState:
        revision_instruction = _resolve_revision_instruction(state)

        updates = report_service.revise_report_text(
            state,
            revision_instruction,
        )
        merged = _merge_state_with_assistant_message(state, updates)
        merged["pending_revision_instruction"] = None
        merged = _persist_snapshot(report_service, merged)
        return cast(ReportInteractionState, merged)

    def share_report(state: ReportInteractionState) -> ReportInteractionState:
        updates = report_service.share_report(state)
        merged = _merge_state_with_assistant_message(state, updates)
        merged = _persist_snapshot(report_service, merged)
        return cast(ReportInteractionState, merged)

    def prepare_rerun(state: ReportInteractionState) -> ReportInteractionState:
        rerun_basis = _resolve_rerun_instruction(state)

        rerun_user_text = report_service.build_rerun_request_text(
            state,
            rerun_basis,
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
        merged["pending_rerun_instruction"] = None
        merged = _persist_snapshot(report_service, merged)
        return cast(ReportInteractionState, merged)

    def finalize_session(state: ReportInteractionState) -> ReportInteractionState:
        updates = report_service.finalize_session(state)
        merged = _merge_state_with_assistant_message(state, updates)
        merged = _persist_snapshot(report_service, merged)
        return cast(ReportInteractionState, merged)

    def cancel_session(state: ReportInteractionState) -> ReportInteractionState:
        updates = report_service.cancel_session(state)
        merged = _merge_state_with_assistant_message(state, updates)
        merged = _persist_snapshot(report_service, merged)
        return cast(ReportInteractionState, merged)

    def route_after_intent(state: ReportInteractionState) -> str:
        raw_intent = str(state.get("last_intent", ReportUserIntent.UNKNOWN.value))

        if raw_intent in {_AWAIT_CONFIRM_CANCEL, _AWAIT_CONFIRM_FINALIZE}:
            return "confirm_destructive_action"

        if raw_intent == _CONFIRMATION_DECLINED:
            return "confirmation_declined"

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
    builder.add_node("confirm_destructive_action", confirm_destructive_action)
    builder.add_node("confirmation_declined", confirmation_declined)
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
            "confirm_destructive_action": "confirm_destructive_action",
            "confirmation_declined": "confirmation_declined",
            "answer_question": "answer_question",
            "revise_report_text": "revise_report_text",
            "share_report": "share_report",
            "prepare_rerun": "prepare_rerun",
            "finalize_session": "finalize_session",
            "cancel_session": "cancel_session",
        },
    )

    builder.add_edge("confirm_destructive_action", "wait_for_user_message")
    builder.add_edge("confirmation_declined", "wait_for_user_message")
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


def _resolve_revision_instruction(state: ReportInteractionState) -> str:
    pending = str(state.get("pending_revision_instruction", "") or "").strip()
    if pending:
        return pending
    return str(state.get("latest_user_message", "") or "").strip()


def _resolve_rerun_instruction(state: ReportInteractionState) -> str:
    pending = str(state.get("pending_rerun_instruction", "") or "").strip()
    if pending:
        return pending
    return str(state.get("latest_user_message", "") or "").strip()


def _persist_snapshot(
    report_service: InteractiveReportService,
    state: dict[str, Any],
) -> dict[str, Any]:
    snapshot_updates = report_service.persist_session_snapshot(state)
    merged = dict(state)
    merged.update(snapshot_updates)
    return merged


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


def _should_confirm_destructive_action(
    *,
    intent: ReportUserIntent,
    confidence: float,
) -> bool:
    if intent == ReportUserIntent.CANCEL_REPORT:
        return confidence < 0.92

    if intent == ReportUserIntent.FINALIZE_REPORT:
        return confidence < 0.88

    return False


def _get_pending_confirmation_kind(
    state: ReportInteractionState,
) -> Literal["cancel", "finalize"] | None:
    last_intent = str(state.get("last_intent", "")).strip()

    if last_intent == _AWAIT_CONFIRM_CANCEL:
        return "cancel"
    if last_intent == _AWAIT_CONFIRM_FINALIZE:
        return "finalize"
    return None


def _classify_confirmation_reply(message: str) -> Literal["yes", "no", "unknown"]:
    normalized = _normalize_text(message)

    yes_exact = {
        "ok",
        "oke",
        "dong y",
        "duoc",
        "co",
        "yes",
        "y",
        "xac nhan",
        "chac chan",
    }
    no_exact = {
        "khong",
        "khong dau",
        "khong dong y",
        "khong can",
        "no",
        "n",
        "thoi",
    }

    if normalized in yes_exact:
        return "yes"
    if normalized in no_exact:
        return "no"

    yes_tokens = [
        "dong y",
        "xac nhan",
        "yes",
        "co",
        "ok",
        "oke",
        "duoc",
    ]
    no_tokens = [
        "khong",
        "no",
        "thoi",
        "dung",
        "bo qua",
    ]

    if any(token in normalized for token in yes_tokens):
        return "yes"
    if any(token in normalized for token in no_tokens):
        return "no"

    return "unknown"


def _normalize_text(text: str) -> str:
    import re
    import unicodedata

    lowered = text.strip().lower()
    normalized = unicodedata.normalize("NFD", lowered)
    without_accents = "".join(
        ch for ch in normalized if unicodedata.category(ch) != "Mn"
    )
    without_accents = without_accents.replace("đ", "d").replace("Đ", "D")
    without_accents = re.sub(r"\s+", " ", without_accents)
    return without_accents.strip()


def _localize(preferred_language: str, vi_text: str, en_text: str) -> str:
    return en_text if preferred_language == "en" else vi_text