from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from api_testing_agent.core.ai_testcase_agent import AITestCaseAgent
from api_testing_agent.core.feedback_scope_refiner import FeedbackScopeRefiner
from api_testing_agent.core.reporter.testcase import TestcaseDraftReporter


class TestcaseReviewState(TypedDict, total=False):
    thread_id: str
    user_request_text: str
    canonical_command: str
    target_name: str
    plan: dict[str, Any]

    all_operation_contexts: list[dict]
    operation_contexts: list[dict]

    feedback_history: list[str]
    review_round: int
    scope_note: str | None

    draft_groups: list[dict[str, Any]]
    draft_preview: str
    draft_report_json_path: str
    draft_report_md_path: str

    review_action: str
    latest_feedback: str

    approved: bool
    cancelled: bool


def build_testcase_review_graph(
    agent: AITestCaseAgent,
    draft_reporter: TestcaseDraftReporter,
    feedback_scope_refiner: FeedbackScopeRefiner | None = None,
    checkpointer: Any | None = None,
):
    if checkpointer is None:
        checkpointer = InMemorySaver()

    def generate_draft_node(state: TestcaseReviewState) -> dict[str, Any]:
        current_operation_contexts = list(state.get("operation_contexts", []))
        all_operation_contexts = list(state.get("all_operation_contexts", current_operation_contexts))
        scope_note = state.get("scope_note")

        if feedback_scope_refiner is not None:
            refined_scope = feedback_scope_refiner.refine(
                target_name=state["target_name"],
                current_operation_contexts=current_operation_contexts,
                all_operation_contexts=all_operation_contexts,
                feedback_history=list(state.get("feedback_history", [])),
            )
            current_operation_contexts = refined_scope.operation_contexts
            scope_note = refined_scope.scope_note

        draft_groups: list[dict[str, Any]] = []

        for operation_ctx in current_operation_contexts:
            context = {
                "target_name": state["target_name"],
                "original_user_text": state["user_request_text"],
                "canonical_command": state["canonical_command"],
                "operation": operation_ctx,
                "plan": state["plan"],
                "feedback_history": state.get("feedback_history", []),
                "rules": [
                    "Sinh testcase bám đúng phạm vi operation hiện tại.",
                    "Không được bịa endpoint mới.",
                    "Không được đưa token thật vào Authorization header.",
                    "Runtime system sẽ tự thêm bearer token nếu cần cho mọi case trừ unauthorized.",
                    "Unauthorized case chỉ hợp lệ nếu operation cần auth.",
                    "Not found case chỉ hợp lý nếu có path parameter đại diện resource identifier.",
                    "Nếu một test type không phù hợp thì trả skip=true.",
                ],
            }

            draft_list = agent.generate_for_operation(context)

            draft_groups.append(
                {
                    "operation_id": operation_ctx["operation_id"],
                    "method": operation_ctx["method"],
                    "path": operation_ctx["path"],
                    "cases": [case.model_dump(mode="json") for case in draft_list.cases],
                }
            )

        round_no = int(state.get("review_round", 0)) + 1

        report = draft_reporter.write(
            thread_id=state["thread_id"],
            target_name=state["target_name"],
            round_number=round_no,
            original_user_text=state["user_request_text"],
            canonical_command=state["canonical_command"],
            draft_groups=draft_groups,
            feedback_history=list(state.get("feedback_history", [])),
            plan=state["plan"],
            operation_contexts=current_operation_contexts,
            scope_note=scope_note,
        )

        return {
            "operation_contexts": current_operation_contexts,
            "draft_groups": draft_groups,
            "draft_preview": report.preview_text,
            "draft_report_json_path": report.json_path,
            "draft_report_md_path": report.markdown_path,
            "review_round": round_no,
            "scope_note": scope_note,
        }

    def review_gate_node(state: TestcaseReviewState) -> dict[str, Any]:
        decision = interrupt(
            {
                "kind": "testcase_review",
                "round": state.get("review_round", 0),
                "original_user_text": state.get("user_request_text", ""),
                "canonical_command": state.get("canonical_command", ""),
                "scope_note": state.get("scope_note"),
                "preview": state.get("draft_preview", ""),
                "draft_groups": state.get("draft_groups", []),
                "draft_report_json_path": state.get("draft_report_json_path", ""),
                "draft_report_md_path": state.get("draft_report_md_path", ""),
                "feedback_history": state.get("feedback_history", []),
            }
        )

        if not isinstance(decision, dict):
            decision = {"action": "revise", "feedback": str(decision)}

        action = str(decision.get("action", "revise")).strip().lower()
        feedback = str(decision.get("feedback", "")).strip()

        history = list(state.get("feedback_history", []))
        if action == "revise" and feedback:
            history.append(feedback)

        return {
            "review_action": action,
            "latest_feedback": feedback,
            "feedback_history": history,
        }

    def mark_approved_node(state: TestcaseReviewState) -> dict[str, Any]:
        return {"approved": True, "cancelled": False}

    def mark_cancelled_node(state: TestcaseReviewState) -> dict[str, Any]:
        return {"approved": False, "cancelled": True}

    def route_after_review(state: TestcaseReviewState) -> str:
        action = str(state.get("review_action", "revise")).strip().lower()

        if action == "approve":
            return "mark_approved"
        if action == "cancel":
            return "mark_cancelled"
        return "generate_draft"

    builder = StateGraph(TestcaseReviewState)
    builder.add_node("generate_draft", generate_draft_node)
    builder.add_node("review_gate", review_gate_node)
    builder.add_node("mark_approved", mark_approved_node)
    builder.add_node("mark_cancelled", mark_cancelled_node)

    builder.add_edge(START, "generate_draft")
    builder.add_edge("generate_draft", "review_gate")
    builder.add_conditional_edges(
        "review_gate",
        route_after_review,
        {
            "generate_draft": "generate_draft",
            "mark_approved": "mark_approved",
            "mark_cancelled": "mark_cancelled",
        },
    )
    builder.add_edge("mark_approved", END)
    builder.add_edge("mark_cancelled", END)

    return builder.compile(checkpointer=checkpointer)