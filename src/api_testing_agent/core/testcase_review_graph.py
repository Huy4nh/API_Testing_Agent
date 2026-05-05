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

    # ===== Scope trace / report consistency =====
    initial_understanding_explanation: NotRequired[str]
    initial_scope_operation_refs: NotRequired[list[str]]
    current_scope_explanation: NotRequired[str]
    current_scope_operation_refs: NotRequired[list[str]]
    scope_change_history: NotRequired[list[dict[str, Any]]]


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
        all_operation_contexts = list(
            state.get("all_operation_contexts", current_operation_contexts)
        )
        previous_scope_refs = _operation_refs(current_operation_contexts)

        scope_note = state.get("scope_note")
        feedback_history = list(state.get("feedback_history", []))
        latest_feedback = feedback_history[-1] if feedback_history else None

        initial_understanding_explanation = str(
            state.get("initial_understanding_explanation")
            or state.get("understanding_explanation")
            or ""
        ).strip()

        initial_scope_operation_refs = list(
            state.get("initial_scope_operation_refs") or previous_scope_refs
        )

        scope_change_history = list(state.get("scope_change_history", []))

        logger.info(
            f"Initial scope contains {len(current_operation_contexts)} operation(s)."
        )

        if feedback_scope_refiner is not None:
            logger.info("Running feedback scope refiner.")
            refined_scope = feedback_scope_refiner.refine(
                target_name=state["target_name"],
                current_operation_contexts=current_operation_contexts,
                all_operation_contexts=all_operation_contexts,
                feedback_history=feedback_history,
            )
            current_operation_contexts = refined_scope.operation_contexts
            scope_note = refined_scope.scope_note

            logger.info(
                "Scope refinement completed. "
                f"Refined scope contains {len(current_operation_contexts)} operation(s)."
            )

        current_scope_refs = _operation_refs(current_operation_contexts)

        scope_changed = previous_scope_refs != current_scope_refs
        if latest_feedback and scope_changed:
            scope_change_history = _append_scope_change_event(
                history=scope_change_history,
                feedback=latest_feedback,
                before_refs=previous_scope_refs,
                after_refs=current_scope_refs,
                scope_note=scope_note,
            )

        current_scope_explanation = _build_current_scope_explanation(
            target_name=state["target_name"],
            operation_contexts=current_operation_contexts,
            feedback_history=feedback_history,
            scope_note=scope_note,
        )

        # Đồng bộ canonical command theo scope hiện tại.
        canonical_command = _build_canonical_command_from_scope(
            target_name=state["target_name"],
            operation_contexts=current_operation_contexts,
            plan=state["plan"],
        )

        # Quan trọng:
        # understanding_explanation phải phản ánh scope hiện tại, không giữ mãi explanation cũ.
        # Nếu không, final report sẽ nhìn như "understanding nói simple nhưng execution chạy coins".
        understanding_explanation = _build_scope_trace_understanding(
            initial_understanding_explanation=initial_understanding_explanation,
            initial_scope_operation_refs=initial_scope_operation_refs,
            current_scope_explanation=current_scope_explanation,
            current_scope_operation_refs=current_scope_refs,
            scope_change_history=scope_change_history,
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
                f"Generating testcase draft for "
                f"{operation_ctx.get('method', '-')} {operation_ctx.get('path', '-')}"
            )

            context = {
                "target_name": state["target_name"],
                "original_user_text": state["user_request_text"],
                "canonical_command": canonical_command,
                "understanding_explanation": understanding_explanation,
                "operation": operation_ctx,
                "plan": state["plan"],
                "feedback_history": feedback_history,
                "scope_note": scope_note,
                "current_scope_explanation": current_scope_explanation,
                "scope_change_history": scope_change_history,
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
            understanding_explanation=understanding_explanation,
            draft_groups=draft_groups,
            feedback_history=feedback_history,
            plan=state["plan"],
            operation_contexts=current_operation_contexts,
            scope_note=scope_note,
        )

        logger.info(
            f"Draft report written. json_path={report.json_path}, "
            f"md_path={report.markdown_path}"
        )

        return {
            "canonical_command": canonical_command,
            "understanding_explanation": understanding_explanation,
            "initial_understanding_explanation": initial_understanding_explanation,
            "initial_scope_operation_refs": initial_scope_operation_refs,
            "current_scope_explanation": current_scope_explanation,
            "current_scope_operation_refs": current_scope_refs,
            "scope_change_history": scope_change_history,
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
                "initial_understanding_explanation": state.get(
                    "initial_understanding_explanation"
                ),
                "current_scope_explanation": state.get("current_scope_explanation"),
                "scope_change_history": state.get("scope_change_history", []),
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

    # Giữ nguyên test types hiện tại.
    test_types = list(plan.get("test_types", []))
    parts.extend(_build_test_type_tokens(test_types))

    # Giữ nguyên ignore fields.
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


def _operation_refs(operation_contexts: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    for operation in operation_contexts:
        method = str(operation.get("method", "")).strip().upper()
        path = str(operation.get("path", "")).strip()
        operation_id = str(operation.get("operation_id", "")).strip()

        if not method and not path and not operation_id:
            continue

        key = (operation_id, method, path)
        if key in seen:
            continue
        seen.add(key)

        if method and path:
            refs.append(f"{method} {path}")
        elif operation_id:
            refs.append(operation_id)
        else:
            refs.append(f"{method} {path}".strip())

    return refs


def _append_scope_change_event(
    *,
    history: list[dict[str, Any]],
    feedback: str,
    before_refs: list[str],
    after_refs: list[str],
    scope_note: str | None,
) -> list[dict[str, Any]]:
    cleaned_feedback = feedback.strip()

    if history:
        last = history[-1]
        if (
            str(last.get("feedback", "")).strip() == cleaned_feedback
            and list(last.get("after", [])) == after_refs
        ):
            return history

    return history + [
        {
            "feedback": cleaned_feedback,
            "before": before_refs,
            "after": after_refs,
            "scope_note": scope_note,
        }
    ]


def _build_current_scope_explanation(
    *,
    target_name: str,
    operation_contexts: list[dict[str, Any]],
    feedback_history: list[str],
    scope_note: str | None,
) -> str:
    current_refs = _operation_refs(operation_contexts)

    parts: list[str] = [
        f"Current approved review scope for target `{target_name}`:"
    ]

    if current_refs:
        parts.append("Final active operations: " + ", ".join(current_refs) + ".")
    else:
        parts.append("Final active operations: none.")

    if feedback_history:
        parts.append(
            "Latest review feedback: "
            f"`{str(feedback_history[-1]).strip()}`."
        )

    if scope_note:
        parts.append(f"Scope note: {scope_note}")

    return " ".join(parts).strip()


def _build_scope_trace_understanding(
    *,
    initial_understanding_explanation: str,
    initial_scope_operation_refs: list[str],
    current_scope_explanation: str,
    current_scope_operation_refs: list[str],
    scope_change_history: list[dict[str, Any]],
) -> str:
    pieces: list[str] = []

    initial = initial_understanding_explanation.strip()
    if initial:
        pieces.append("Initial understanding: " + initial)

    if initial_scope_operation_refs:
        pieces.append(
            "Initial scope operations: "
            + ", ".join(initial_scope_operation_refs)
            + "."
        )

    if scope_change_history:
        pieces.append("Scope changed during review:")
        for index, item in enumerate(scope_change_history, start=1):
            feedback = str(item.get("feedback", "")).strip()
            before_refs = [str(ref) for ref in list(item.get("before", []))]
            after_refs = [str(ref) for ref in list(item.get("after", []))]
            scope_note = str(item.get("scope_note", "") or "").strip()

            event_parts = [f"{index}. Feedback `{feedback}`"]
            if before_refs:
                event_parts.append("before: " + ", ".join(before_refs))
            if after_refs:
                event_parts.append("after: " + ", ".join(after_refs))
            if scope_note:
                event_parts.append("note: " + scope_note)

            pieces.append("; ".join(event_parts) + ".")

    current = current_scope_explanation.strip()
    if current:
        pieces.append(current)

    if current_scope_operation_refs:
        pieces.append(
            "Final approved scope operations: "
            + ", ".join(current_scope_operation_refs)
            + "."
        )

    return " ".join(pieces).strip()