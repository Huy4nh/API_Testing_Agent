from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from api_testing_agent.core.ai_testcase_agent import AITestCaseAgent
from api_testing_agent.core.feedback_scope_refiner import FeedbackScopeRefiner
from api_testing_agent.core.reporter.testcase import TestcaseDraftReporter
from api_testing_agent.logging_config import bind_logger, get_logger


class TestcaseReviewState(TypedDict):
    # ===== Required keys: luôn có từ initial_state =====
    thread_id: str
    user_request_text: str
    canonical_command: str
    understanding_explanation: str
    target_name: str
    plan: dict[str, Any]

    all_operation_contexts: list[dict[str, Any]]
    operation_contexts: list[dict[str, Any]]

    feedback_history: list[str]
    review_round: int
    scope_note: str | None

    approved: bool
    cancelled: bool

    # ===== Optional keys: được sinh dần trong graph =====
    draft_groups: NotRequired[list[dict[str, Any]]]
    draft_preview: NotRequired[str]
    draft_report_json_path: NotRequired[str]
    draft_report_md_path: NotRequired[str]

    review_action: NotRequired[str]
    latest_feedback: NotRequired[str]


def build_testcase_review_graph(
    agent: AITestCaseAgent,
    draft_reporter: TestcaseDraftReporter,
    feedback_scope_refiner: FeedbackScopeRefiner | None = None,
    checkpointer: Any | None = None,
):
    base_logger = get_logger(__name__)

    if checkpointer is None:
        checkpointer = InMemorySaver()

    def _state_logger(
        state: TestcaseReviewState,
        *,
        payload_source: str,
        operation_id: str | None = None,
    ):
        return bind_logger(
            base_logger,
            thread_id=str(state.get("thread_id", "-")),
            target_name=str(state.get("target_name", "-")),
            operation_id=operation_id or "-",
            payload_source=payload_source,
        )

    def generate_draft_node(state: TestcaseReviewState) -> dict[str, Any]:
        logger = _state_logger(state, payload_source="review_generate_draft")
        logger.info("Starting generate_draft_node.")

        current_operation_contexts = list(state.get("operation_contexts", []))
        all_operation_contexts = list(state.get("all_operation_contexts", current_operation_contexts))
        scope_note = state.get("scope_note")
        canonical_command = state.get("canonical_command", "")

        logger.info(
            f"Initial scope contains {len(current_operation_contexts)} operation(s)."
        )

        if feedback_scope_refiner is not None:
            logger.info("Running feedback scope refiner.")
            refined_scope = feedback_scope_refiner.refine(
                target_name=state["target_name"],
                current_operation_contexts=current_operation_contexts,
                all_operation_contexts=all_operation_contexts,
                feedback_history=list(state.get("feedback_history", [])),
            )
            current_operation_contexts = refined_scope.operation_contexts
            scope_note = refined_scope.scope_note

            logger.info(
                f"Scope refinement completed. Refined scope contains {len(current_operation_contexts)} operation(s)."
            )

        # Đồng bộ canonical command theo scope hiện tại
        canonical_command = _build_canonical_command_from_scope(
            target_name=state["target_name"],
            operation_contexts=current_operation_contexts,
            plan=state["plan"],
        )

        logger.info(f"Canonical command rebuilt: {canonical_command}")

        draft_groups: list[dict[str, Any]] = []

        for operation_ctx in current_operation_contexts:
            operation_logger = _state_logger(
                state,
                payload_source="review_generate_operation_draft",
                operation_id=str(operation_ctx.get("operation_id", "-")),
            )
            operation_logger.info(
                f"Generating testcase draft for {operation_ctx.get('method', '-')} {operation_ctx.get('path', '-')}"
            )

            context = {
                "target_name": state["target_name"],
                "original_user_text": state["user_request_text"],
                "canonical_command": canonical_command,
                "understanding_explanation": state.get("understanding_explanation"),
                "operation": operation_ctx,
                "plan": state["plan"],
                "feedback_history": state.get("feedback_history", []),
                "scope_note": scope_note,
                "rules": [
                    "Sinh testcase bám đúng phạm vi operation hiện tại.",
                    "Không được bịa endpoint mới.",
                    "Nếu feedback đã đổi scope thì chỉ sinh testcase cho scope mới.",
                    "Unauthorized case chỉ hợp lệ nếu operation cần auth.",
                    "Not found case chỉ hợp lý nếu có path parameter đại diện resource identifier.",
                    "Nếu test type không phù hợp thì trả skip=true.",
                ],
            }

            draft_list = agent.generate_for_operation(context)

            operation_logger.info(
                f"Generated {len(draft_list.cases)} testcase(s) for operation."
            )

            draft_groups.append(
                {
                    "operation_id": operation_ctx["operation_id"],
                    "method": operation_ctx["method"],
                    "path": operation_ctx["path"],
                    "cases": [case.model_dump(mode="json") for case in draft_list.cases],
                }
            )

        round_no = int(state.get("review_round", 0)) + 1
        logger.info(f"Writing testcase draft report for round={round_no}.")

        report = draft_reporter.write(
            thread_id=state["thread_id"],
            target_name=state["target_name"],
            round_number=round_no,
            original_user_text=state["user_request_text"],
            canonical_command=canonical_command,
            understanding_explanation=state.get("understanding_explanation"),
            draft_groups=draft_groups,
            feedback_history=list(state.get("feedback_history", [])),
            plan=state["plan"],
            operation_contexts=current_operation_contexts,
            scope_note=scope_note,
        )

        logger.info(
            f"Draft report written. json_path={report.json_path}, md_path={report.markdown_path}"
        )

        return {
            "canonical_command": canonical_command,
            "operation_contexts": current_operation_contexts,
            "draft_groups": draft_groups,
            "draft_preview": report.preview_text,
            "draft_report_json_path": report.json_path,
            "draft_report_md_path": report.markdown_path,
            "review_round": round_no,
            "scope_note": scope_note,
        }

    def review_gate_node(state: TestcaseReviewState) -> dict[str, Any]:
        logger = _state_logger(state, payload_source="review_gate")
        logger.info("Entering review_gate_node and waiting for human decision.")

        decision = interrupt(
            {
                "kind": "testcase_review",
                "round": state.get("review_round", 0),
                "original_user_text": state.get("user_request_text", ""),
                "canonical_command": state.get("canonical_command", ""),
                "understanding_explanation": state.get("understanding_explanation"),
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

        logger.info(f"Review decision received. action={action}")

        history = list(state.get("feedback_history", []))
        if action == "revise" and feedback:
            history.append(feedback)
            logger.info("Feedback appended to history.")

        return {
            "review_action": action,
            "latest_feedback": feedback,
            "feedback_history": history,
        }

    def mark_approved_node(state: TestcaseReviewState) -> dict[str, Any]:
        logger = _state_logger(state, payload_source="review_mark_approved")
        logger.info("Marking review as approved.")
        return {"approved": True, "cancelled": False}

    def mark_cancelled_node(state: TestcaseReviewState) -> dict[str, Any]:
        logger = _state_logger(state, payload_source="review_mark_cancelled")
        logger.info("Marking review as cancelled.")
        return {"approved": False, "cancelled": True}

    def route_after_review(state: TestcaseReviewState) -> str:
        logger = _state_logger(state, payload_source="review_route_after_review")

        action = str(state.get("review_action", "revise")).strip().lower()
        if action == "approve":
            logger.info("Routing to mark_approved.")
            return "mark_approved"
        if action == "cancel":
            logger.info("Routing to mark_cancelled.")
            return "mark_cancelled"

        logger.info("Routing back to generate_draft for another round.")
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

    base_logger.info(
        "Compiled testcase review graph.",
        extra={"payload_source": "review_graph_compile"},
    )

    return builder.compile(checkpointer=checkpointer)


def _build_canonical_command_from_scope(
    *,
    target_name: str,
    operation_contexts: list[dict],
    plan: dict[str, Any],
) -> str:
    parts: list[str] = ["test", "target", target_name]

    # Nếu scope hiện tại có operation cụ thể thì đưa path + method vào canonical command
    # để phản ánh đúng phạm vi đang test.
    seen_path_method: set[tuple[str, str]] = set()
    for operation in operation_contexts:
        path = str(operation.get("path", "")).strip()
        method = str(operation.get("method", "")).strip().upper()

        if not path or not method:
            continue

        key = (path, method)
        if key in seen_path_method:
            continue

        seen_path_method.add(key)
        parts.append(path)
        parts.append(method)

    # Giữ nguyên test types hiện tại
    test_types = list(plan.get("test_types", []))
    parts.extend(_build_test_type_tokens(test_types))

    # Giữ nguyên ignore fields
    ignore_fields = list(plan.get("ignore_fields", []))
    for field_name in ignore_fields:
        parts.extend(["ignore", "field", str(field_name)])

    return " ".join(parts).strip()


def _build_test_type_tokens(test_types: list[str]) -> list[str]:
    values = {str(item) for item in test_types}

    negative_values = {
        "missing_required",
        "invalid_type_or_format",
        "unauthorized",
        "not_found",
    }

    if values == negative_values:
        return ["negative"]

    if values == {"positive"}:
        return ["positive"]

    tokens: list[str] = []
    if "positive" in values:
        tokens.append("positive")
    if "unauthorized" in values:
        tokens.append("unauthorized")
    if "not_found" in values:
        tokens.append("not_found")
    if "missing_required" in values:
        tokens.append("missing")
    if "invalid_type_or_format" in values:
        tokens.append("invalid")

    return tokens