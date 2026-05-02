from __future__ import annotations

import difflib
import json
import sqlite3
import traceback
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from api_testing_agent.config import Settings
from api_testing_agent.core.execution_engine import ExecutionEngine
from api_testing_agent.core.execution_log_formatter import ExecutionLogFormatter
from api_testing_agent.core.execution_models import ExecutionBatchResult, ExecutionCaseResult
from api_testing_agent.core.report_intent_agent import ReportIntentAgent
from api_testing_agent.core.report_interaction_graph import (
    build_report_interaction_graph,
    report_graph_config,
)
from api_testing_agent.core.report_interaction_models import (
    ReportInteractionState,
    ReportSessionResult,
)
from api_testing_agent.core.report_context_builder import ReportContextBuilder
from api_testing_agent.core.reporter.interactive.interactive_report_service import (
    InteractiveReportService,
)
from api_testing_agent.tasks.orchestrator import ReviewWorkflowResult, TestOrchestrator
from api_testing_agent.core.unknown_output_description_service import (
    UnknownOutputDescriptionService,
)
from api_testing_agent.core.validation_models import (
    ValidationBatchResult,
    ValidationCaseResult,
)
from api_testing_agent.core.validator import Validator
from api_testing_agent.logging_config import bind_logger, get_logger, setup_logging
from api_testing_agent.tasks.orchestrator import TestOrchestrator

from api_testing_agent.core.report_hybrid_ai import (
    ReportHybridAI,
    ReviewActionHybridAIProtocol,
)

from collections.abc import Sequence

DIVIDER = "=" * 100


@runtime_checkable
class ExecutionCaseLike(Protocol):
    @property
    def testcase_id(self) -> str | None: ...
    @property
    def logical_case_name(self) -> str | None: ...
    @property
    def target_name(self) -> str: ...
    @property
    def operation_id(self) -> str: ...
    @property
    def method(self) -> str: ...
    @property
    def path(self) -> str: ...
    @property
    def test_type(self) -> str | None: ...
    @property
    def expected_statuses(self) -> Sequence[int]: ...
    @property
    def actual_status(self) -> int | None: ...
    @property
    def response_time_ms(self) -> float | None: ...
    @property
    def skip(self) -> bool: ...
    @property
    def skip_reason(self) -> str | None: ...
    @property
    def network_error(self) -> str | None: ...
    @property
    def response_json(self) -> Any: ...
    @property
    def response_text(self) -> str | None: ...
    @property
    def response_headers(self) -> dict[str, Any] | None: ...
    @property
    def final_headers(self) -> dict[str, Any]: ...
    @property
    def final_query_params(self) -> dict[str, Any]: ...
    @property
    def final_json_body(self) -> Any: ...
    @property
    def final_url(self) -> str: ...
    @property
    def executed_at(self) -> str: ...
    @property
    def planner_reason(self) -> str | None: ...
    @property
    def planner_confidence(self) -> float | None: ...
    @property
    def payload_source(self) -> str | None: ...


@runtime_checkable
class ExecutionBatchLike(Protocol):
    @property
    def thread_id(self) -> str: ...
    @property
    def target_name(self) -> str: ...
    @property
    def total_cases(self) -> int: ...
    @property
    def executed_cases(self) -> int: ...
    @property
    def skipped_cases(self) -> int: ...
    @property
    def results(self) -> Sequence[Any]: ...


@runtime_checkable
class ValidationIssueLike(Protocol):
    @property
    def level(self) -> Any: ...
    @property
    def code(self) -> str: ...
    @property
    def message(self) -> str: ...


@runtime_checkable
class ValidationCaseLike(Protocol):
    @property
    def testcase_id(self) -> str | None: ...
    @property
    def logical_case_name(self) -> str | None: ...
    @property
    def operation_id(self) -> str: ...
    @property
    def method(self) -> str: ...
    @property
    def path(self) -> str: ...
    @property
    def verdict(self) -> Any: ...
    @property
    def summary_message(self) -> str: ...
    @property
    def expected_statuses(self) -> Sequence[int]: ...
    @property
    def actual_status(self) -> int | None: ...
    @property
    def status_check_passed(self) -> bool | None: ...
    @property
    def schema_check_passed(self) -> bool | None: ...
    @property
    def required_fields_check_passed(self) -> bool | None: ...
    @property
    def expected_required_fields(self) -> Sequence[str]: ...
    @property
    def missing_required_fields(self) -> Sequence[str]: ...
    @property
    def network_error(self) -> str | None: ...
    @property
    def skip_reason(self) -> str | None: ...
    @property
    def issues(self) -> Sequence[ValidationIssueLike]: ...


@runtime_checkable
class ValidationBatchLike(Protocol):
    @property
    def thread_id(self) -> str | None: ...
    @property
    def target_name(self) -> str | None: ...
    @property
    def total_cases(self) -> int: ...
    @property
    def validated_cases(self) -> int: ...
    @property
    def pass_cases(self) -> int: ...
    @property
    def fail_cases(self) -> int: ...
    @property
    def skip_cases(self) -> int: ...
    @property
    def error_cases(self) -> int: ...
    @property
    def results(self) -> Sequence[Any]: ...

def main() -> None:
    setup_logging()

    base_logger = get_logger(__name__)
    settings = Settings()
    hybrid_ai = ReportHybridAI(
        model_name=settings.langchain_model_name,
        model_provider=getattr(settings, "langchain_model_provider", None),
    )
    orchestrator = TestOrchestrator(settings)

    unknown_output_description_service = UnknownOutputDescriptionService(
        model_name=settings.langchain_model_name,
        model_provider=getattr(settings, "langchain_model_provider", None),
    )

    execution_engine = ExecutionEngine(
        timeout_seconds=settings.http_timeout_seconds,
        unknown_output_description_service=unknown_output_description_service,
    )

    execution_log_formatter = ExecutionLogFormatter()
    validator = Validator()

    thread_id = _generate_thread_id()
    logger = bind_logger(base_logger, thread_id=thread_id)
    logger.info("Started manual report workflow v2.")

    candidate_targets_history: list[str] = []
    target_selection_question: str | None = None
    review_feedback_history: list[str] = []

    try:
        raw_text = input("Nhập lệnh test: ").strip()
        if not raw_text:
            logger.warning("No input provided. Exiting manual report workflow.")
            print("Không có input. Kết thúc.")
            return

        logger.info(
            "Received user input for manual report workflow.",
            extra={"payload_source": "manual_input"},
        )

        result = orchestrator.start_review_from_text(raw_text, thread_id=thread_id)

        while True:
            _print_review_result(result)

            if result.status in {"target_not_found", "invalid_function", "cancelled"}:
                logger.info(
                    f"Workflow ended early with status={result.status}.",
                    extra={"target_name": result.selected_target or "-"},
                )
                return

            if result.status == "pending_target_selection":
                candidate_targets_history = list(result.candidate_targets or [])
                target_selection_question = result.selection_question

                logger.info(
                    "Pending target selection.",
                    extra={"target_name": ",".join(result.candidate_targets or [])},
                )

                selection = input(
                    "\nNhập lựa chọn target [số thứ tự / tên target / cancel]: "
                ).strip()

                logger.info("User submitted target selection.")
                result = orchestrator.resume_target_selection(
                    result.thread_id,
                    selection=selection,
                )
                continue

            if result.status == "pending_review":
                logger.info(
                    "Pending review for testcase draft.",
                    extra={"target_name": result.selected_target or "-"},
                )

                raw_action = input(
                    "\nNhập action [approve / feedback / cancel]: "
                ).strip()

                action, feedback = _normalize_review_input(
                    raw_action,
                    hybrid_ai=hybrid_ai,
                    thread_id=result.thread_id,
                    target_name=result.selected_target,
                    preview_text=result.preview_text or "",
                    feedback_history=review_feedback_history,
                )

                if action == "approve":
                    logger.info(
                        "User approved testcase draft.",
                        extra={"target_name": result.selected_target or "-"},
                    )

                    result = orchestrator.resume_review(
                        result.thread_id,
                        action="approve",
                        feedback="",
                    )

                    _print_review_result(result)

                    _run_full_report_session(
                        settings=settings,
                        orchestrator=orchestrator,
                        execution_engine=execution_engine,
                        execution_log_formatter=execution_log_formatter,
                        validator=validator,
                        result=result,
                        original_request=raw_text,
                        candidate_targets_history=candidate_targets_history,
                        target_selection_question=target_selection_question,
                        review_feedback_history=review_feedback_history,
                        logger=logger,
                    )
                    return

                if action == "cancel":
                    logger.info(
                        "User cancelled review.",
                        extra={"target_name": result.selected_target or "-"},
                    )
                    result = orchestrator.resume_review(
                        result.thread_id,
                        action="cancel",
                        feedback="",
                    )
                    continue

                if action == "revise":
                    if not feedback:
                        feedback = input("Nhập feedback để sinh lại testcase: ").strip()

                    if feedback:
                        review_feedback_history.append(feedback)

                    logger.info(
                        "User requested testcase revision.",
                        extra={"target_name": result.selected_target or "-"},
                    )

                    result = orchestrator.resume_review(
                        result.thread_id,
                        action="revise",
                        feedback=feedback,
                    )
                    continue

                logger.warning(f"Invalid review action: {raw_action}")
                print(f"Action không hợp lệ: {raw_action}")
                continue

            if result.status == "approved":
                logger.info(
                    "Workflow reached approved state directly. Starting full report session.",
                    extra={"target_name": result.selected_target or "-"},
                )

                _run_full_report_session(
                    settings=settings,
                    orchestrator=orchestrator,
                    execution_engine=execution_engine,
                    execution_log_formatter=execution_log_formatter,
                    validator=validator,
                    result=result,
                    original_request=raw_text,
                    candidate_targets_history=candidate_targets_history,
                    target_selection_question=target_selection_question,
                    review_feedback_history=review_feedback_history,
                    logger=logger,
                )
                return

            logger.warning(f"Unhandled workflow status: {result.status}")
            print(f"Trạng thái chưa xử lý: {result.status}")
            return

    except KeyboardInterrupt:
        logger.warning("Manual report workflow interrupted by user.")
        print("\nĐã dừng bởi người dùng.")
    except Exception as exc:
        logger.exception(f"Manual report workflow failed with exception: {exc}")
        print("\nCó lỗi khi chạy workflow report test.")
        print(f"Error: {exc}")
        print("\nChi tiết traceback:")
        print(traceback.format_exc())


def _run_full_report_session(
    *,
    settings: Settings,
    orchestrator: TestOrchestrator,
    execution_engine: ExecutionEngine,
    execution_log_formatter: ExecutionLogFormatter,
    validator: Validator,
    result: ReviewWorkflowResult,
    original_request: str,
    candidate_targets_history: list[str],
    target_selection_question: str | None,
    review_feedback_history: list[str],
    logger: Any,
) -> None:
    approved_payload = _get_execution_payload(orchestrator, result.thread_id)

    execution_batch_result = _execute_approved_review(
        orchestrator=orchestrator,
        execution_engine=execution_engine,
        thread_id=result.thread_id,
        logger=logger,
    )

    execution_report_paths = _write_execution_reports(
        settings=settings,
        batch_result=execution_batch_result,
    )

    approved_payload["execution_report_json_path"] = execution_report_paths["json_path"]
    approved_payload["execution_report_md_path"] = execution_report_paths["md_path"]

    _print_execution_batch_result(
        batch_result=execution_batch_result,
        log_formatter=execution_log_formatter,
        report_paths=execution_report_paths,
    )

    validation_batch_result = validator.validate_batch(execution_batch_result)

    logger.info(
        "Validation batch finished.",
        extra={
            "target_name": validation_batch_result.target_name or "-",
            "payload_source": "validation_batch",
            "pass_cases": validation_batch_result.pass_cases,
            "fail_cases": validation_batch_result.fail_cases,
            "skip_cases": validation_batch_result.skip_cases,
            "error_cases": validation_batch_result.error_cases,
        },
    )

    validation_report_paths = _write_validation_reports(
        settings=settings,
        batch_result=validation_batch_result,
    )

    approved_payload["validation_report_json_path"] = validation_report_paths["json_path"]
    approved_payload["validation_report_md_path"] = validation_report_paths["md_path"]

    _print_validation_batch_result(
        batch_result=validation_batch_result,
        report_paths=validation_report_paths,
    )

    final_report_payload = _build_final_report_payload(
        approved_payload=approved_payload,
        execution_batch_result=execution_batch_result,
        execution_report_paths=execution_report_paths,
        validation_batch_result=validation_batch_result,
        validation_report_paths=validation_report_paths,
        original_request=original_request,
        candidate_targets_history=candidate_targets_history,
        target_selection_question=target_selection_question,
        review_feedback_history=review_feedback_history,
    )

    staged_final_report_paths = _write_staged_final_reports(
        settings=settings,
        final_report_payload=final_report_payload,
    )

    final_report_payload["links"]["final_report_json_path"] = staged_final_report_paths["json_path"]
    final_report_payload["links"]["final_report_md_path"] = staged_final_report_paths["md_path"]

    _print_final_report_summary(
        final_report_payload=final_report_payload,
        report_paths=staged_final_report_paths,
        staged=True,
    )

    session_result = _run_post_report_interaction_session(
        settings=settings,
        final_report_payload=final_report_payload,
        approved_payload=approved_payload,
        execution_batch_result=execution_batch_result,
        validation_batch_result=validation_batch_result,
        original_request=original_request,
        candidate_targets_history=candidate_targets_history,
        target_selection_question=target_selection_question,
        review_feedback_history=review_feedback_history,
        logger=logger,
    )

    print("\n" + DIVIDER)
    print("REPORT SESSION RESULT")
    print(f"FINALIZED: {session_result.finalized}")
    print(f"CANCELLED: {session_result.cancelled}")
    print(f"RERUN REQUESTED: {session_result.rerun_requested}")
    print(f"RERUN USER TEXT: {session_result.rerun_user_text}")
    print(f"FINAL REPORT JSON PATH: {session_result.final_report_json_path}")
    print(f"FINAL REPORT MD PATH: {session_result.final_report_md_path}")
    print(f"MESSAGE: {session_result.message}")

    if session_result.cancelled:
        print("\nWorkflow đã bị hủy sau final report. Không persist SQLite.")
        return

    if session_result.rerun_requested:
        print("\nUser yêu cầu chạy lại với instruction mới.")
        print("RERUN USER TEXT:")
        print(session_result.rerun_user_text)
        print("Chưa persist SQLite cho run hiện tại.")
        return

    if session_result.finalized:
        sqlite_path = getattr(settings, "sqlite_path", "./data/runs.sqlite3")
        _persist_final_report_to_sqlite(
            sqlite_path=sqlite_path,
            final_report_payload=final_report_payload,
            finalized_final_report_json_path=session_result.final_report_json_path,
            finalized_final_report_md_path=session_result.final_report_md_path,
            execution_batch_result=execution_batch_result,
            validation_batch_result=validation_batch_result,
            messages=[],
            logger=logger,
        )
        print("\n" + DIVIDER)
        print("SQLITE STATUS: finished")
        print(f"SQLITE PATH: {sqlite_path}")
        print("Đã lưu workflow_runs + execution_case_results + validation_case_results.")
        return


def _run_post_report_interaction_session(
    *,
    settings: Settings,
    final_report_payload: dict[str, Any],
    approved_payload: dict[str, Any],
    execution_batch_result: ExecutionBatchResult,
    validation_batch_result: ValidationBatchResult,
    original_request: str,
    candidate_targets_history: list[str],
    target_selection_question: str | None,
    review_feedback_history: list[str],
    logger: Any,
) -> ReportSessionResult:
    thread_id = str(final_report_payload["summary"]["thread_id"])
    target_name = str(final_report_payload["summary"]["target_name"])

    report_hybrid_ai = ReportHybridAI(
        model_name=settings.langchain_model_name,
        model_provider=getattr(settings, "langchain_model_provider", None),
    )

    report_service = InteractiveReportService(
        output_dir=settings.report_output_dir,
        context_builder=ReportContextBuilder(),
        hybrid_ai=report_hybrid_ai,
    )

    intent_agent = ReportIntentAgent(
        hybrid_ai=report_hybrid_ai,
    )
    
    checkpointer = _create_checkpointer(settings)

    graph = build_report_interaction_graph(
        intent_agent=intent_agent,
        report_service=report_service,
        checkpointer=checkpointer,
    )

    initial_state: ReportInteractionState = {
        "thread_id": thread_id,
        "target_name": target_name,
        "original_request": original_request,
        "canonical_command": approved_payload.get("canonical_command"),
        "understanding_explanation": approved_payload.get("understanding_explanation"),
        "candidate_targets": list(candidate_targets_history or []),
        "target_selection_question": target_selection_question,
        "review_feedback_history": list(review_feedback_history or []),
        "draft_report_json_path": approved_payload.get("draft_report_json_path"),
        "draft_report_md_path": approved_payload.get("draft_report_md_path"),
        "execution_report_json_path": approved_payload.get("execution_report_json_path"),
        "execution_report_md_path": approved_payload.get("execution_report_md_path"),
        "validation_report_json_path": approved_payload.get("validation_report_json_path"),
        "validation_report_md_path": approved_payload.get("validation_report_md_path"),
        "staged_final_report_json_path": final_report_payload["links"]["final_report_json_path"],
        "staged_final_report_md_path": final_report_payload["links"]["final_report_md_path"],
        "final_report_json_path": None,
        "final_report_md_path": None,
        "final_report_markdown": Path(
            str(final_report_payload["links"]["final_report_md_path"])
        ).read_text(encoding="utf-8"),
        "final_report_data": final_report_payload,
        "execution_batch_result": execution_batch_result,
        "validation_batch_result": validation_batch_result,
        "messages": [],
        "finalized": False,
        "cancelled": False,
        "rerun_requested": False,
        "artifact_paths": [],
    }

    config = report_graph_config(thread_id)
    graph.invoke(initial_state, config=config)

    printed_assistant_count = 0

    while True:
        snapshot = graph.get_state(config)
        values = dict(snapshot.values)

        printed_assistant_count = _print_new_assistant_messages(
            values=values,
            printed_assistant_count=printed_assistant_count,
        )

        if bool(values.get("finalized", False)):
            logger.info(
                "Report interaction session finalized.",
                extra={"target_name": target_name, "payload_source": "report_session_finalized"},
            )
            return ReportSessionResult(
                thread_id=thread_id,
                target_name=target_name,
                finalized=True,
                final_report_json_path=values.get("final_report_json_path"),
                final_report_md_path=values.get("final_report_md_path"),
                message="Report session finalized.",
            )

        if bool(values.get("cancelled", False)):
            logger.info(
                "Report interaction session cancelled.",
                extra={"target_name": target_name, "payload_source": "report_session_cancelled"},
            )
            return ReportSessionResult(
                thread_id=thread_id,
                target_name=target_name,
                cancelled=True,
                message="Report session cancelled and staging artifacts cleaned.",
            )

        if bool(values.get("rerun_requested", False)):
            logger.info(
                "Report interaction session requested rerun.",
                extra={"target_name": target_name, "payload_source": "report_session_rerun"},
            )
            return ReportSessionResult(
                thread_id=thread_id,
                target_name=target_name,
                rerun_requested=True,
                rerun_user_text=values.get("rerun_user_text"),
                message="Rerun requested from report interaction session.",
            )

        user_message = input("\nBạn (sau final report): ").strip()
        if not user_message:
            print("Tin nhắn rỗng. Hãy nhập nội dung tiếp theo.")
            continue

        graph.invoke(
            Command(resume={"message": user_message}),
            config=config,
        )


def _print_new_assistant_messages(
    *,
    values: dict[str, Any],
    printed_assistant_count: int,
) -> int:
    messages = list(values.get("messages", []))
    assistant_messages = [
        str(msg.get("content", ""))
        for msg in messages
        if str(msg.get("role", "")).lower() == "assistant"
    ]

    while printed_assistant_count < len(assistant_messages):
        print("\n" + assistant_messages[printed_assistant_count])
        printed_assistant_count += 1

    return printed_assistant_count


def _create_checkpointer(settings: Settings):
    mode = str(getattr(settings, "langgraph_checkpointer", "memory")).strip().lower()
    if mode == "sqlite":
        raw_sqlite_path = getattr(settings, "langgraph_sqlite_path", None)
        sqlite_path = str(raw_sqlite_path or "./data/langgraph.sqlite3")

        Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(sqlite_path, check_same_thread=False)
        return SqliteSaver(connection)

    return InMemorySaver()


def _generate_thread_id() -> str:
    return f"cli-report-{uuid.uuid4().hex}"


def _normalize_review_input(
    raw_action: str,
    *,
    hybrid_ai: ReviewActionHybridAIProtocol | None = None,
    thread_id: str = "",
    target_name: str | None = None,
    preview_text: str = "",
    feedback_history: list[str] | None = None,
) -> tuple[str, str]:
    cleaned = raw_action.strip()
    lowered = cleaned.lower()

    # Rule chắc chắn
    if lowered in {"approve", "approved", "ok", "oke"}:
        return "approve", ""

    if lowered in {"cancel", "huy", "hủy"}:
        return "cancel", ""

    if lowered in {"feedback", "revise"}:
        return "revise", ""

    # Fuzzy cho typo gần
    approve_candidates = ["approve", "approved"]
    if difflib.get_close_matches(lowered, approve_candidates, n=1, cutoff=0.75):
        return "approve", ""

    cancel_candidates = ["cancel"]
    if difflib.get_close_matches(lowered, cancel_candidates, n=1, cutoff=0.85):
        return "cancel", ""

    # AI fallback cho câu tự nhiên như:
    # - tốt rồi
    # - ổn đó
    # - thêm yt vào
    if hybrid_ai is not None:
        try:
            ai_result = hybrid_ai.decide_review_action(
                thread_id=thread_id,
                target_name=target_name,
                user_text=cleaned,
                preview_text=preview_text,
                feedback_history=list(feedback_history or []),
            )

            action = str(ai_result.get("action", "revise")).strip().lower()
            feedback = str(ai_result.get("feedback", "") or "")

            if action in {"approve", "cancel", "revise"}:
                return action, feedback
        except Exception:
            # Nếu AI lỗi thì vẫn không làm crash flow
            pass

    # Fallback cuối cùng
    return "revise", cleaned


def _execute_approved_review(
    *,
    orchestrator: TestOrchestrator,
    execution_engine: ExecutionEngine,
    thread_id: str,
    logger: Any,
) -> ExecutionBatchResult:
    payload = _get_execution_payload(orchestrator, thread_id)

    batch_result = execution_engine.execute_approved_draft(
        thread_id=payload["thread_id"],
        target=payload["target"],
        target_name=payload["target_name"],
        operation_contexts=payload["operation_contexts"],
        draft_groups=payload["draft_groups"],
    )

    logger.info(
        "Execution batch finished.",
        extra={
            "target_name": batch_result.target_name,
            "payload_source": "execution_batch",
        },
    )
    return batch_result


def _get_execution_payload(
    orchestrator: TestOrchestrator,
    thread_id: str,
) -> dict[str, Any]:
    if not hasattr(orchestrator, "get_approved_execution_payload"):
        raise RuntimeError(
            "TestOrchestrator chưa có method 'get_approved_execution_payload'.\n"
            "Hãy thêm method này vào orchestrator trước khi chạy manual report workflow."
        )

    payload = orchestrator.get_approved_execution_payload(thread_id)
    if not isinstance(payload, dict):
        raise RuntimeError("Execution payload trả về không hợp lệ.")

    return payload


def _build_final_report_payload(
    *,
    approved_payload: dict[str, Any],
    execution_batch_result: ExecutionBatchLike,
    execution_report_paths: dict[str, str],
    validation_batch_result: ValidationBatchLike,
    validation_report_paths: dict[str, str],
    original_request: str,
    candidate_targets_history: list[str],
    target_selection_question: str | None,
    review_feedback_history: list[str],
) -> dict[str, Any]:
    target_name = approved_payload["target_name"]
    thread_id = approved_payload["thread_id"]

    execution_results = list(execution_batch_result.results or [])
    validation_results = list(validation_batch_result.results or [])

    validation_map: dict[str, ValidationCaseLike] = {}
    for item in validation_results:
        testcase_id = item.testcase_id
        if testcase_id is None:
            continue
        validation_map[testcase_id] = item

    case_summaries: list[dict[str, Any]] = []
    notable_findings: list[dict[str, Any]] = []

    for execution_item in execution_results:
        execution_testcase_id = execution_item.testcase_id
        validation_item = (
            validation_map.get(execution_testcase_id)
            if execution_testcase_id is not None
            else None
        )

        case_summary = {
            "testcase_id": execution_item.testcase_id,
            "logical_case_name": execution_item.logical_case_name,
            "operation_id": execution_item.operation_id,
            "method": execution_item.method,
            "path": execution_item.path,
            "test_type": execution_item.test_type,
            "expected_statuses": list(execution_item.expected_statuses or []),
            "actual_status": execution_item.actual_status,
            "response_time_ms": execution_item.response_time_ms,
            "skipped": bool(execution_item.skip),
            "skip_reason": execution_item.skip_reason,
            "network_error": execution_item.network_error,
            "verdict": validation_item.verdict.value if validation_item else "unknown",
            "summary_message": validation_item.summary_message if validation_item else "",
            "issues": [
                {
                    "level": str(issue.level),
                    "code": issue.code,
                    "message": issue.message,
                    "field": getattr(issue, "field", None),
                }
                for issue in (validation_item.issues if validation_item else [])
            ],
        }
        case_summaries.append(case_summary)

        if validation_item and validation_item.verdict.value in {"fail", "error"}:
            notable_findings.append(
                {
                    "severity": "high",
                    "title": "Case fail/error",
                    "detail": validation_item.summary_message,
                    "testcase_id": execution_item.testcase_id,
                    "operation_id": execution_item.operation_id,
                    "method": execution_item.method,
                    "path": execution_item.path,
                }
            )

        if execution_item.response_time_ms is not None and execution_item.response_time_ms >= 5000:
            notable_findings.append(
                {
                    "severity": "medium",
                    "title": "Slow response",
                    "detail": f"Response time = {execution_item.response_time_ms:.2f} ms, vượt ngưỡng cảnh báo 5000 ms.",
                    "testcase_id": execution_item.testcase_id,
                    "operation_id": execution_item.operation_id,
                    "method": execution_item.method,
                    "path": execution_item.path,
                }
            )

    if validation_batch_result.skip_cases > 0:
        notable_findings.append(
            {
                "severity": "info",
                "title": "Skipped cases",
                "detail": f"Có {validation_batch_result.skip_cases} case bị skip ở lớp validation/runtime.",
                "testcase_id": None,
                "operation_id": None,
                "method": None,
                "path": None,
            }
        )

    return {
        "summary": {
            "run_id": uuid.uuid4().hex,
            "thread_id": thread_id,
            "target_name": target_name,
            "original_request": original_request,
            "canonical_command": approved_payload.get("canonical_command"),
            "understanding_explanation": approved_payload.get("understanding_explanation"),
            "selected_target": target_name,
            "candidate_targets": list(candidate_targets_history or []),
            "target_selection_question": target_selection_question,
            "feedback_history": list(review_feedback_history or []),
            "approved": True,
            "total_cases": execution_batch_result.total_cases,
            "executed_cases": execution_batch_result.executed_cases,
            "skipped_cases": execution_batch_result.skipped_cases,
            "pass_cases": validation_batch_result.pass_cases,
            "fail_cases": validation_batch_result.fail_cases,
            "skip_cases_validation": validation_batch_result.skip_cases,
            "error_cases": validation_batch_result.error_cases,
            "report_stage": "staged",
            "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        },
        "links": {
            "draft_report_json_path": approved_payload.get("draft_report_json_path"),
            "draft_report_md_path": approved_payload.get("draft_report_md_path"),
            "execution_report_json_path": execution_report_paths["json_path"],
            "execution_report_md_path": execution_report_paths["md_path"],
            "validation_report_json_path": validation_report_paths["json_path"],
            "validation_report_md_path": validation_report_paths["md_path"],
            "final_report_json_path": None,
            "final_report_md_path": None,
        },
        "case_summaries": case_summaries,
        "notable_findings": notable_findings,
    }


def _write_staged_final_reports(
    *,
    settings: Settings,
    final_report_payload: dict[str, Any],
) -> dict[str, str]:
    summary = dict(final_report_payload.get("summary", {}) or {})

    raw_target_name = summary.get("target_name")
    raw_thread_id = summary.get("thread_id")
    raw_report_output_dir = getattr(settings, "report_output_dir", None)

    if raw_target_name is None:
        raise ValueError("final_report_payload.summary.target_name is required")

    if raw_thread_id is None:
        raise ValueError("final_report_payload.summary.thread_id is required")

    report_output_dir = str(raw_report_output_dir or "./reports")
    target_name = str(raw_target_name)
    thread_id = str(raw_thread_id)

    root_dir = (
        Path(report_output_dir)
        / "_staging"
        / "final_runs"
        / target_name
        / thread_id
    )
    root_dir.mkdir(parents=True, exist_ok=True)

    json_path = root_dir / "final_summary.json"
    md_path = root_dir / "final_summary.md"

    json_path.write_text(
        json.dumps(final_report_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    md_path.write_text(
        _build_final_markdown(final_report_payload),
        encoding="utf-8",
    )

    return {
        "json_path": str(json_path),
        "md_path": str(md_path),
    }


def _build_final_markdown(final_report_payload: dict[str, Any]) -> str:
    summary = final_report_payload["summary"]
    links = final_report_payload["links"]
    case_summaries = list(final_report_payload.get("case_summaries", []))
    notable_findings = list(final_report_payload.get("notable_findings", []))

    lines: list[str] = []
    lines.append("# Final Workflow Report")
    lines.append("")
    lines.append(f"- Run ID: `{summary['run_id']}`")
    lines.append(f"- Thread ID: `{summary['thread_id']}`")
    lines.append(f"- Target: `{summary['target_name']}`")
    lines.append(f"- Report stage: `{summary['report_stage']}`")
    lines.append("")
    lines.append("## Request Trace")
    if summary.get("original_request"):
        lines.append(f"- Original request: {summary['original_request']}")
    if summary.get("selected_target"):
        lines.append(f"- Selected target: `{summary['selected_target']}`")
    if summary.get("candidate_targets"):
        lines.append(f"- Candidate targets: `{summary['candidate_targets']}`")
    if summary.get("target_selection_question"):
        lines.append(f"- Target question: {summary['target_selection_question']}")
    if summary.get("canonical_command"):
        lines.append(f"- Canonical command: `{summary['canonical_command']}`")
    if summary.get("understanding_explanation"):
        lines.append(f"- Understanding explanation: {summary['understanding_explanation']}")
    lines.append("")
    lines.append("## Review Trace")
    if summary.get("feedback_history"):
        lines.append("- Feedback history:")
        for idx, item in enumerate(summary["feedback_history"], start=1):
            lines.append(f"  - {idx}. {item}")
    else:
        lines.append("- No feedback history.")
    lines.append("")
    lines.append("## Execution Summary")
    lines.append(f"- Total cases: `{summary['total_cases']}`")
    lines.append(f"- Executed cases: `{summary['executed_cases']}`")
    lines.append(f"- Skipped cases (execution): `{summary['skipped_cases']}`")
    lines.append("")
    lines.append("## Validation Summary")
    lines.append(f"- Pass: `{summary['pass_cases']}`")
    lines.append(f"- Fail: `{summary['fail_cases']}`")
    lines.append(f"- Skip: `{summary['skip_cases_validation']}`")
    lines.append(f"- Error: `{summary['error_cases']}`")
    lines.append("")
    lines.append("## Notable Findings")
    if notable_findings:
        for finding in notable_findings:
            lines.append(
                f"- [{finding['severity'].upper()}] {finding['title']}: {finding['detail']}"
            )
    else:
        lines.append("- Không có finding nổi bật.")
    lines.append("")
    lines.append("## Linked Reports")
    if links.get("draft_report_md_path"):
        lines.append(f"- Draft report: `{links['draft_report_md_path']}`")
    if links.get("execution_report_md_path"):
        lines.append(f"- Execution report: `{links['execution_report_md_path']}`")
    if links.get("validation_report_md_path"):
        lines.append(f"- Validation report: `{links['validation_report_md_path']}`")
    lines.append("")
    lines.append("## Case Summaries")

    if not case_summaries:
        lines.append("- Không có case nào trong final summary.")
        return "\n".join(lines)

    for index, case in enumerate(case_summaries, start=1):
        lines.append(f"### {index}. {case['method']} {case['path']}")
        if case.get("logical_case_name"):
            lines.append(f"- Logical case: {case['logical_case_name']}")
        if case.get("test_type"):
            lines.append(f"- Test type: `{case['test_type']}`")
        if case.get("expected_statuses"):
            lines.append(f"- Expected statuses: `{case['expected_statuses']}`")
        if case.get("actual_status") is not None:
            lines.append(f"- Actual status: `{case['actual_status']}`")
        if case.get("response_time_ms") is not None:
            lines.append(f"- Response time: `{float(case['response_time_ms']):.2f} ms`")
        lines.append(f"- Verdict: `{case['verdict']}`")
        if case.get("skipped"):
            lines.append("- Skipped: `True`")
        if case.get("skip_reason"):
            lines.append(f"- Skip reason: {case['skip_reason']}")
        if case.get("network_error"):
            lines.append(f"- Network error: {case['network_error']}")
        if case.get("summary_message"):
            lines.append(f"- Summary: {case['summary_message']}")
        if case.get("issues"):
            lines.append("- Issues:")
            for issue in case["issues"]:
                field = issue.get("field")
                if field:
                    lines.append(
                        f"  - [{issue.get('code', 'UNKNOWN')}] {issue.get('message', '')} (field={field})"
                    )
                else:
                    lines.append(
                        f"  - [{issue.get('code', 'UNKNOWN')}] {issue.get('message', '')}"
                    )
        lines.append("")

    return "\n".join(lines)


def _persist_final_report_to_sqlite(
    *,
    sqlite_path: str,
    final_report_payload: dict[str, Any],
    finalized_final_report_json_path: str | None,
    finalized_final_report_md_path: str | None,
    execution_batch_result: ExecutionBatchLike,
    validation_batch_result: ValidationBatchLike,
    messages: list[dict[str, str]],
    logger: Any,
) -> None:
    _ensure_sqlite_schema(sqlite_path=sqlite_path, logger=logger)

    summary = dict(final_report_payload["summary"])
    links = dict(final_report_payload["links"])

    # Chỉ đến lúc finalize mới patch path cuối.
    links["final_report_json_path"] = finalized_final_report_json_path
    links["final_report_md_path"] = finalized_final_report_md_path
    summary["report_stage"] = "finalized"

    logger.info(
        "Persisting finalized final report into SQLite.",
        extra={
            "target_name": summary["target_name"],
            "payload_source": "sqlite_persist_final_report",
        },
    )

    conn = sqlite3.connect(sqlite_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_runs (
                thread_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                target_name TEXT NOT NULL,
                original_request TEXT,
                canonical_command TEXT,
                understanding_explanation TEXT,
                workflow_status TEXT NOT NULL,
                draft_report_json_path TEXT,
                draft_report_md_path TEXT,
                execution_report_json_path TEXT,
                execution_report_md_path TEXT,
                validation_report_json_path TEXT,
                validation_report_md_path TEXT,
                final_report_json_path TEXT,
                final_report_md_path TEXT,
                total_cases INTEGER NOT NULL DEFAULT 0,
                executed_cases INTEGER NOT NULL DEFAULT 0,
                skipped_cases INTEGER NOT NULL DEFAULT 0,
                pass_cases INTEGER NOT NULL DEFAULT 0,
                fail_cases INTEGER NOT NULL DEFAULT 0,
                skip_cases_validation INTEGER NOT NULL DEFAULT 0,
                error_cases INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_case_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                testcase_id TEXT NOT NULL,
                logical_case_name TEXT,
                target_name TEXT NOT NULL,
                operation_id TEXT NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                test_type TEXT,
                actual_status INTEGER,
                response_time_ms REAL,
                skipped INTEGER NOT NULL DEFAULT 0,
                skip_reason TEXT,
                network_error TEXT,
                response_json_json TEXT,
                planner_reason TEXT,
                planner_confidence REAL,
                payload_source TEXT,
                FOREIGN KEY(thread_id) REFERENCES workflow_runs(thread_id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS validation_case_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                testcase_id TEXT NOT NULL,
                operation_id TEXT NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                verdict TEXT NOT NULL,
                summary_message TEXT NOT NULL,
                status_check_passed INTEGER,
                schema_check_passed INTEGER,
                required_fields_check_passed INTEGER,
                issues_json TEXT NOT NULL,
                validated_at TEXT,
                FOREIGN KEY(thread_id) REFERENCES workflow_runs(thread_id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            INSERT INTO workflow_runs (
                thread_id,
                run_id,
                target_name,
                original_request,
                canonical_command,
                understanding_explanation,
                workflow_status,
                draft_report_json_path,
                draft_report_md_path,
                execution_report_json_path,
                execution_report_md_path,
                validation_report_json_path,
                validation_report_md_path,
                final_report_json_path,
                final_report_md_path,
                total_cases,
                executed_cases,
                skipped_cases,
                pass_cases,
                fail_cases,
                skip_cases_validation,
                error_cases,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                run_id=excluded.run_id,
                target_name=excluded.target_name,
                original_request=excluded.original_request,
                canonical_command=excluded.canonical_command,
                understanding_explanation=excluded.understanding_explanation,
                workflow_status=excluded.workflow_status,
                draft_report_json_path=excluded.draft_report_json_path,
                draft_report_md_path=excluded.draft_report_md_path,
                execution_report_json_path=excluded.execution_report_json_path,
                execution_report_md_path=excluded.execution_report_md_path,
                validation_report_json_path=excluded.validation_report_json_path,
                validation_report_md_path=excluded.validation_report_md_path,
                final_report_json_path=excluded.final_report_json_path,
                final_report_md_path=excluded.final_report_md_path,
                total_cases=excluded.total_cases,
                executed_cases=excluded.executed_cases,
                skipped_cases=excluded.skipped_cases,
                pass_cases=excluded.pass_cases,
                fail_cases=excluded.fail_cases,
                skip_cases_validation=excluded.skip_cases_validation,
                error_cases=excluded.error_cases,
                created_at=excluded.created_at
            """,
            (
                summary["thread_id"],
                summary["run_id"],
                summary["target_name"],
                summary.get("original_request"),
                summary.get("canonical_command"),
                summary.get("understanding_explanation"),
                "finalized",
                links.get("draft_report_json_path"),
                links.get("draft_report_md_path"),
                links.get("execution_report_json_path"),
                links.get("execution_report_md_path"),
                links.get("validation_report_json_path"),
                links.get("validation_report_md_path"),
                links.get("final_report_json_path"),
                links.get("final_report_md_path"),
                int(summary.get("total_cases", 0) or 0),
                int(summary.get("executed_cases", 0) or 0),
                int(summary.get("skipped_cases", 0) or 0),
                int(summary.get("pass_cases", 0) or 0),
                int(summary.get("fail_cases", 0) or 0),
                int(summary.get("skip_cases_validation", 0) or 0),
                int(summary.get("error_cases", 0) or 0),
                summary.get("generated_at"),
            ),
        )

        conn.execute(
            "DELETE FROM execution_case_results WHERE thread_id = ?",
            (summary["thread_id"],),
        )

        for row in execution_batch_result.results:
            conn.execute(
                """
                INSERT INTO execution_case_results (
                    thread_id,
                    testcase_id,
                    logical_case_name,
                    target_name,
                    operation_id,
                    method,
                    path,
                    test_type,
                    actual_status,
                    response_time_ms,
                    skipped,
                    skip_reason,
                    network_error,
                    response_json_json,
                    planner_reason,
                    planner_confidence,
                    payload_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary["thread_id"],
                    row.testcase_id,
                    row.logical_case_name,
                    row.target_name,
                    row.operation_id,
                    row.method,
                    row.path,
                    row.test_type,
                    row.actual_status,
                    row.response_time_ms,
                    1 if row.skip else 0,
                    row.skip_reason,
                    row.network_error,
                    json.dumps(row.response_json, ensure_ascii=False, sort_keys=True)
                    if row.response_json is not None
                    else None,
                    row.planner_reason,
                    row.planner_confidence,
                    row.payload_source,
                ),
            )

        conn.execute(
            "DELETE FROM validation_case_results WHERE thread_id = ?",
            (summary["thread_id"],),
        )

        for row in validation_batch_result.results:
            conn.execute(
                """
                INSERT INTO validation_case_results (
                    thread_id,
                    testcase_id,
                    operation_id,
                    method,
                    path,
                    verdict,
                    summary_message,
                    status_check_passed,
                    schema_check_passed,
                    required_fields_check_passed,
                    issues_json,
                    validated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary["thread_id"],
                    row.testcase_id,
                    row.operation_id,
                    row.method,
                    row.path,
                    row.verdict.value,
                    row.summary_message,
                    _bool_to_db(row.status_check_passed),
                    _bool_to_db(row.schema_check_passed),
                    _bool_to_db(row.required_fields_check_passed),
                    json.dumps(
                        [
                            {
                                "level": str(issue.level),
                                "code": issue.code,
                                "message": issue.message,
                                "field": getattr(issue, "field", None),
                            }
                            for issue in row.issues
                        ],
                        ensure_ascii=False,
                    ),
                    datetime.utcnow().isoformat(timespec="seconds"),
                ),
            )

        conn.commit()
    finally:
        conn.close()

    logger.info(
        "Finalized final report persisted successfully.",
        extra={
            "target_name": summary["target_name"],
            "payload_source": "sqlite_persist_final_report_done",
        },
    )


def _ensure_sqlite_schema(
    *,
    sqlite_path: str,
    logger: Any,
) -> None:
    Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(sqlite_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_runs (
                thread_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                target_name TEXT NOT NULL,
                original_request TEXT,
                canonical_command TEXT,
                understanding_explanation TEXT,
                workflow_status TEXT NOT NULL,
                draft_report_json_path TEXT,
                draft_report_md_path TEXT,
                execution_report_json_path TEXT,
                execution_report_md_path TEXT,
                validation_report_json_path TEXT,
                validation_report_md_path TEXT,
                final_report_json_path TEXT,
                final_report_md_path TEXT,
                total_cases INTEGER NOT NULL DEFAULT 0,
                executed_cases INTEGER NOT NULL DEFAULT 0,
                skipped_cases INTEGER NOT NULL DEFAULT 0,
                pass_cases INTEGER NOT NULL DEFAULT 0,
                fail_cases INTEGER NOT NULL DEFAULT 0,
                skip_cases_validation INTEGER NOT NULL DEFAULT 0,
                error_cases INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_case_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                testcase_id TEXT NOT NULL,
                logical_case_name TEXT,
                target_name TEXT NOT NULL,
                operation_id TEXT NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                test_type TEXT,
                actual_status INTEGER,
                response_time_ms REAL,
                skipped INTEGER NOT NULL DEFAULT 0,
                skip_reason TEXT,
                network_error TEXT,
                response_json_json TEXT,
                planner_reason TEXT,
                planner_confidence REAL,
                payload_source TEXT,
                FOREIGN KEY(thread_id) REFERENCES workflow_runs(thread_id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS validation_case_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                testcase_id TEXT NOT NULL,
                operation_id TEXT NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                verdict TEXT NOT NULL,
                summary_message TEXT NOT NULL,
                status_check_passed INTEGER,
                schema_check_passed INTEGER,
                required_fields_check_passed INTEGER,
                issues_json TEXT NOT NULL,
                validated_at TEXT,
                FOREIGN KEY(thread_id) REFERENCES workflow_runs(thread_id) ON DELETE CASCADE
            )
            """
        )

        conn.commit()
    finally:
        conn.close()

    logger.info(
        "SQLite schema ready.",
        extra={"payload_source": "sqlite_ensure_schema_done"},
    )


def _bool_to_db(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0


def _write_execution_reports(
    *,
    settings: Settings,
    batch_result: ExecutionBatchLike,
) -> dict[str, str]:
    report_output_dir = str(getattr(settings, "report_output_dir", None) or "./reports")
    target_name = str(batch_result.target_name)
    thread_id = str(batch_result.thread_id)

    root_dir = (
        Path(report_output_dir)
        / "execution_runs"
        / target_name
        / thread_id
    )
    root_dir.mkdir(parents=True, exist_ok=True)

    json_path = root_dir / "execution_batch.json"
    md_path = root_dir / "execution_batch.md"

    json_payload = _execution_batch_to_dict(batch_result)

    json_path.write_text(
        json.dumps(json_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    md_path.write_text(
        _build_execution_markdown(batch_result),
        encoding="utf-8",
    )

    return {
        "json_path": str(json_path),
        "md_path": str(md_path),
    }


def _write_validation_reports(
    *,
    settings: Settings,
    batch_result: ValidationBatchLike,
) -> dict[str, str]:
    report_output_dir = str(getattr(settings, "report_output_dir", None) or "./reports")
    target_name = str(batch_result.target_name or "unknown_target")
    thread_id = str(batch_result.thread_id or "unknown_thread")

    root_dir = (
        Path(report_output_dir)
        / "validation_runs"
        / target_name
        / thread_id
    )
    root_dir.mkdir(parents=True, exist_ok=True)

    json_path = root_dir / "validation_batch.json"
    md_path = root_dir / "validation_batch.md"

    json_payload = _validation_batch_to_dict(batch_result)

    json_path.write_text(
        json.dumps(json_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    md_path.write_text(
        _build_validation_markdown(batch_result),
        encoding="utf-8",
    )

    return {
        "json_path": str(json_path),
        "md_path": str(md_path),
    }


def _build_execution_markdown(batch_result: ExecutionBatchLike) -> str:
    lines: list[str] = []

    lines.append("# Execution Batch Report")
    lines.append("")
    lines.append(f"- Thread ID: `{batch_result.thread_id}`")
    lines.append(f"- Target: `{batch_result.target_name}`")
    lines.append(f"- Total cases: `{batch_result.total_cases}`")
    lines.append(f"- Executed cases: `{batch_result.executed_cases}`")
    lines.append(f"- Skipped cases: `{batch_result.skipped_cases}`")
    lines.append("")

    for index, result in enumerate(batch_result.results, start=1):
        lines.append(f"## {index}. [{getattr(result, 'test_type', None)}] {getattr(result, 'logical_case_name', None)}")
        lines.append("")
        lines.append(f"- Operation ID: `{getattr(result, 'operation_id', None)}`")
        lines.append(f"- Method: `{getattr(result, 'method', None)}`")
        lines.append(f"- Path: `{getattr(result, 'path', None)}`")
        lines.append(f"- Final URL: `{getattr(result, 'final_url', None)}`")
        lines.append(f"- Expected statuses: `{getattr(result, 'expected_statuses', [])}`")
        lines.append(f"- Actual status: `{getattr(result, 'actual_status', None)}`")

        response_time_ms = getattr(result, "response_time_ms", None)
        if response_time_ms is not None:
            lines.append(f"- Response time (ms): `{float(response_time_ms):.2f}`")
        else:
            lines.append("- Response time (ms): `None`")

        lines.append(f"- Executed at: `{getattr(result, 'executed_at', None)}`")
        lines.append(f"- Skip: `{getattr(result, 'skip', False)}`")

        payload_source = getattr(result, "payload_source", None)
        if payload_source:
            lines.append(f"- Payload source: `{payload_source}`")

        planner_reason = getattr(result, "planner_reason", None)
        if planner_reason:
            lines.append(f"- Planner reason: {planner_reason}")

        planner_confidence = getattr(result, "planner_confidence", None)
        if planner_confidence is not None:
            lines.append(f"- Planner confidence: `{float(planner_confidence):.2f}`")

        skip_reason = getattr(result, "skip_reason", None)
        if skip_reason:
            lines.append(f"- Skip reason: {skip_reason}")

        network_error = getattr(result, "network_error", None)
        if network_error:
            lines.append(f"- Network error: {network_error}")

        final_headers = getattr(result, "final_headers", None)
        if final_headers:
            lines.append(f"- Headers: `{final_headers}`")

        final_query_params = getattr(result, "final_query_params", None)
        if final_query_params:
            lines.append(f"- Query params: `{final_query_params}`")

        final_json_body = getattr(result, "final_json_body", None)
        if final_json_body is not None:
            lines.append(f"- JSON body: `{final_json_body}`")

        response_json = getattr(result, "response_json", None)
        response_text = getattr(result, "response_text", None)

        if response_json is not None:
            lines.append("- Response JSON:")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(response_json, ensure_ascii=False, indent=2))
            lines.append("```")
        elif response_text is not None:
            lines.append("- Response text:")
            lines.append("")
            lines.append("```text")
            lines.append(response_text)
            lines.append("```")

        lines.append("")

    return "\n".join(lines)


def _build_validation_markdown(batch_result: ValidationBatchLike) -> str:
    lines: list[str] = []

    lines.append("# Validation Batch Report")
    lines.append("")
    lines.append(f"- Thread ID: `{batch_result.thread_id}`")
    lines.append(f"- Target: `{batch_result.target_name}`")
    lines.append(f"- Total cases: `{batch_result.total_cases}`")
    lines.append(f"- Validated cases: `{batch_result.validated_cases}`")
    lines.append(f"- Pass cases: `{batch_result.pass_cases}`")
    lines.append(f"- Fail cases: `{batch_result.fail_cases}`")
    lines.append(f"- Skip cases: `{batch_result.skip_cases}`")
    lines.append(f"- Error cases: `{batch_result.error_cases}`")
    lines.append("")

    for index, case_result in enumerate(batch_result.results, start=1):
        verdict = getattr(case_result, "verdict", None)
        verdict_value = getattr(verdict, "value", verdict)

        lines.append(f"## {index}. {getattr(case_result, 'method', None)} {getattr(case_result, 'path', None)}")
        lines.append(f"- testcase_id: `{getattr(case_result, 'testcase_id', None)}`")
        logical_case_name = getattr(case_result, "logical_case_name", None)
        if logical_case_name:
            lines.append(f"- logical_case_name: {logical_case_name}")
        lines.append(f"- verdict: `{verdict_value}`")
        lines.append(f"- summary: {getattr(case_result, 'summary_message', None)}")
        lines.append(f"- expected_statuses: `{getattr(case_result, 'expected_statuses', [])}`")
        lines.append(f"- actual_status: `{getattr(case_result, 'actual_status', None)}`")
        lines.append(f"- status_check_passed: `{getattr(case_result, 'status_check_passed', None)}`")
        lines.append(f"- schema_check_passed: `{getattr(case_result, 'schema_check_passed', None)}`")
        lines.append(f"- required_fields_check_passed: `{getattr(case_result, 'required_fields_check_passed', None)}`")

        skip_reason = getattr(case_result, "skip_reason", None)
        if skip_reason:
            lines.append(f"- skip_reason: {skip_reason}")

        network_error = getattr(case_result, "network_error", None)
        if network_error:
            lines.append(f"- network_error: {network_error}")

        issues = list(getattr(case_result, "issues", []) or [])
        if issues:
            lines.append("- issues:")
            for issue in issues:
                lines.append(
                    f"  - [{getattr(issue, 'level', None)}] {getattr(issue, 'code', None)}: {getattr(issue, 'message', None)}"
                )

        lines.append("")

    return "\n".join(lines)


def _print_review_result(result: ReviewWorkflowResult) -> None:
    print("\n" + DIVIDER)
    print(f"STATUS: {result.status}")
    print(f"THREAD: {result.thread_id}")

    if result.original_user_text:
        print(f"ORIGINAL REQUEST: {result.original_user_text}")

    if result.selected_target:
        print(f"SELECTED TARGET: {result.selected_target}")

    if result.candidate_targets:
        print("CANDIDATE TARGETS:")
        for index, item in enumerate(result.candidate_targets, start=1):
            print(f"  {index}. {item}")

    if result.selection_question:
        print(f"TARGET QUESTION: {result.selection_question}")

    if result.draft_report_json_path:
        print(f"DRAFT JSON REPORT: {result.draft_report_json_path}")

    if result.draft_report_md_path:
        print(f"DRAFT MD REPORT: {result.draft_report_md_path}")

    if result.available_functions:
        print("AVAILABLE FUNCTIONS:")
        for item in result.available_functions:
            print(f"  - {item}")

    if result.message:
        print(f"MESSAGE: {result.message}")

    if result.preview_text:
        cleaned_preview = _strip_duplicate_preview_header(result.preview_text)
        if cleaned_preview:
            print(cleaned_preview)
    else:
        if result.round_number:
            print(f"Review round: {result.round_number}")

        if result.canonical_command:
            print(f"CANONICAL COMMAND: {result.canonical_command}")

        if result.understanding_explanation:
            print(f"UNDERSTANDING: {result.understanding_explanation}")


def _strip_duplicate_preview_header(preview_text: str) -> str:
    duplicated_prefixes = (
        "Review round:",
        "Original request:",
        "Canonical command:",
        "Understanding:",
        "Scope note:",
        "Active operations:",
        "Feedback history:",
    )

    cleaned_lines: list[str] = []
    for line in preview_text.splitlines():
        if line.startswith(duplicated_prefixes):
            continue
        cleaned_lines.append(line)

    while cleaned_lines and not cleaned_lines[0].strip():
        cleaned_lines.pop(0)

    return "\n".join(cleaned_lines).rstrip()


def _print_execution_batch_result(
    *,
    batch_result: ExecutionBatchLike,
    log_formatter: ExecutionLogFormatter,
    report_paths: dict[str, str],
) -> None:
    print("\n" + DIVIDER)
    print("EXECUTION STATUS: finished")
    print(f"THREAD: {batch_result.thread_id}")
    print(f"TARGET: {batch_result.target_name}")
    print(f"TOTAL CASES: {batch_result.total_cases}")
    print(f"EXECUTED CASES: {batch_result.executed_cases}")
    print(f"SKIPPED CASES: {batch_result.skipped_cases}")
    print(f"EXECUTION JSON REPORT: {report_paths['json_path']}")
    print(f"EXECUTION MD REPORT: {report_paths['md_path']}")

    for index, case_result in enumerate(batch_result.results, start=1):
        print("\n" + DIVIDER)
        print(f"EXECUTION CASE {index}")

        if isinstance(case_result, ExecutionCaseResult):
            print(log_formatter.format_case_result(case_result))
        else:
            print(_format_execution_case_for_console(case_result))

        _print_execution_case_detail(case_result)

def _format_execution_case_for_console(case_result: Any) -> str:
    logical_case_name = getattr(case_result, "logical_case_name", None) or "-"
    test_type = getattr(case_result, "test_type", None) or "-"
    method = getattr(case_result, "method", None) or "-"
    final_url = getattr(case_result, "final_url", None) or "-"
    expected_statuses = getattr(case_result, "expected_statuses", None) or []
    actual_status = getattr(case_result, "actual_status", None)
    response_time_ms = getattr(case_result, "response_time_ms", None)
    network_error = getattr(case_result, "network_error", None)
    payload_source = getattr(case_result, "payload_source", None)

    time_str = (
        f"{float(response_time_ms):.2f}"
        if response_time_ms is not None
        else "0.00"
    )

    lines = [
        f"[{test_type}] {logical_case_name}",
        f"  {method} {final_url}",
        f"  expected: {expected_statuses}",
        f"  actual: {actual_status}",
        f"  time_ms: {time_str}",
        f"  network_error: {network_error}",
    ]

    if payload_source is not None:
        lines.append(f"  payload_source: {payload_source}")

    planner_reason = getattr(case_result, "planner_reason", None)
    if planner_reason:
        lines.append(f"  planner_reason: {planner_reason}")

    planner_confidence = getattr(case_result, "planner_confidence", None)
    if planner_confidence is not None:
        lines.append(f"  planner_confidence: {float(planner_confidence):.2f}")

    return "\n".join(lines)

def _print_execution_case_detail(case_result: ExecutionCaseLike) -> None:
    print(f"  operation_id: {case_result.operation_id}")
    print(f"  testcase_id: {case_result.testcase_id}")
    print(f"  headers: {case_result.final_headers}")
    print(f"  query_params: {case_result.final_query_params}")
    print(f"  json_body: {case_result.final_json_body}")

    if case_result.payload_source:
        print(f"  payload_source: {case_result.payload_source}")

    if case_result.planner_reason:
        print(f"  planner_reason: {case_result.planner_reason}")

    if case_result.planner_confidence is not None:
        print(f"  planner_confidence: {case_result.planner_confidence:.2f}")

    if case_result.response_headers:
        print(f"  response_headers: {case_result.response_headers}")

    if case_result.response_json is not None:
        print("  response_json:")
        print(_pretty_json(case_result.response_json))
    elif case_result.response_text is not None:
        print("  response_text:")
        print(case_result.response_text)


def _print_validation_batch_result(
    *,
    batch_result: ValidationBatchLike,
    report_paths: dict[str, str],
) -> None:
    print("\n" + DIVIDER)
    print("VALIDATION STATUS: finished")
    print(f"THREAD: {batch_result.thread_id}")
    print(f"TARGET: {batch_result.target_name}")
    print(f"TOTAL CASES: {batch_result.total_cases}")
    print(f"VALIDATED CASES: {batch_result.validated_cases}")
    print(f"PASS CASES: {batch_result.pass_cases}")
    print(f"FAIL CASES: {batch_result.fail_cases}")
    print(f"SKIP CASES: {batch_result.skip_cases}")
    print(f"ERROR CASES: {batch_result.error_cases}")
    print(f"VALIDATION JSON REPORT: {report_paths['json_path']}")
    print(f"VALIDATION MD REPORT: {report_paths['md_path']}")

    for index, case_result in enumerate(batch_result.results, start=1):
        print("\n" + DIVIDER)
        print(f"VALIDATION CASE {index}")
        _print_validation_case_detail(case_result)


def _print_validation_case_detail(case_result: ValidationCaseLike) -> None:
    print(f"  testcase_id: {case_result.testcase_id}")
    print(f"  logical_case_name: {case_result.logical_case_name}")
    print(f"  operation_id: {case_result.operation_id}")
    print(f"  method: {case_result.method}")
    print(f"  path: {case_result.path}")
    print(f"  verdict: {case_result.verdict.value}")
    print(f"  summary: {case_result.summary_message}")
    print(f"  expected_statuses: {case_result.expected_statuses}")
    print(f"  actual_status: {case_result.actual_status}")
    print(f"  status_check_passed: {case_result.status_check_passed}")
    print(f"  schema_check_passed: {case_result.schema_check_passed}")
    print(f"  required_fields_check_passed: {case_result.required_fields_check_passed}")

    if case_result.expected_required_fields:
        print(f"  expected_required_fields: {case_result.expected_required_fields}")

    if case_result.missing_required_fields:
        print(f"  missing_required_fields: {case_result.missing_required_fields}")

    if case_result.network_error:
        print(f"  network_error: {case_result.network_error}")

    if case_result.skip_reason:
        print(f"  skip_reason: {case_result.skip_reason}")

    if case_result.issues:
        print("  issues:")
        for issue in case_result.issues:
            print(f"    - [{issue.level}] {issue.code}: {issue.message}")


def _print_final_report_summary(
    *,
    final_report_payload: dict[str, Any],
    report_paths: dict[str, str],
    staged: bool,
) -> None:
    summary = final_report_payload["summary"]

    print("\n" + DIVIDER)
    print("FINAL REPORT STATUS: staged" if staged else "FINAL REPORT STATUS: finished")
    print(f"THREAD: {summary['thread_id']}")
    print(f"TARGET: {summary['target_name']}")
    print(f"RUN ID: {summary['run_id']}")
    print(f"TOTAL CASES: {summary['total_cases']}")
    print(f"EXECUTED CASES: {summary['executed_cases']}")
    print(f"SKIPPED CASES (EXECUTION): {summary['skipped_cases']}")
    print(f"PASS CASES: {summary['pass_cases']}")
    print(f"FAIL CASES: {summary['fail_cases']}")
    print(f"SKIP CASES (VALIDATION): {summary['skip_cases_validation']}")
    print(f"ERROR CASES: {summary['error_cases']}")
    print(f"FINAL JSON REPORT: {report_paths['json_path']}")
    print(f"FINAL MD REPORT: {report_paths['md_path']}")

    findings = list(final_report_payload.get("notable_findings", []))
    if findings:
        print("TOP FINDINGS:")
        for item in findings[:10]:
            print(f"  - [{item['severity']}] {item['title']}: {item['detail']}")


def _pretty_json(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        return str(data)

def _execution_case_to_dict(case_result: Any) -> dict[str, Any]:
    return {
        "testcase_id": getattr(case_result, "testcase_id", None),
        "logical_case_name": getattr(case_result, "logical_case_name", None),
        "target_name": getattr(case_result, "target_name", None),
        "operation_id": getattr(case_result, "operation_id", None),
        "method": getattr(case_result, "method", None),
        "path": getattr(case_result, "path", None),
        "test_type": getattr(case_result, "test_type", None),
        "expected_statuses": list(getattr(case_result, "expected_statuses", []) or []),
        "actual_status": getattr(case_result, "actual_status", None),
        "response_time_ms": getattr(case_result, "response_time_ms", None),
        "skip": bool(getattr(case_result, "skip", False)),
        "skip_reason": getattr(case_result, "skip_reason", None),
        "network_error": getattr(case_result, "network_error", None),
        "response_json": getattr(case_result, "response_json", None),
        "response_text": getattr(case_result, "response_text", None),
        "response_headers": getattr(case_result, "response_headers", None),
        "final_headers": getattr(case_result, "final_headers", {}),
        "final_query_params": getattr(case_result, "final_query_params", {}),
        "final_json_body": getattr(case_result, "final_json_body", None),
        "final_url": getattr(case_result, "final_url", None),
        "executed_at": getattr(case_result, "executed_at", None),
        "planner_reason": getattr(case_result, "planner_reason", None),
        "planner_confidence": getattr(case_result, "planner_confidence", None),
        "payload_source": getattr(case_result, "payload_source", None),
    }


def _execution_batch_to_dict(batch_result: ExecutionBatchLike) -> dict[str, Any]:
    return {
        "thread_id": batch_result.thread_id,
        "target_name": batch_result.target_name,
        "total_cases": batch_result.total_cases,
        "executed_cases": batch_result.executed_cases,
        "skipped_cases": batch_result.skipped_cases,
        "results": [
            _execution_case_to_dict(item)
            for item in batch_result.results
        ],
    }


def _validation_issue_to_dict(issue: Any) -> dict[str, Any]:
    return {
        "level": str(getattr(issue, "level", "")),
        "code": getattr(issue, "code", None),
        "message": getattr(issue, "message", None),
        "field": getattr(issue, "field", None),
    }


def _validation_case_to_dict(case_result: Any) -> dict[str, Any]:
    verdict = getattr(case_result, "verdict", None)
    verdict_value = getattr(verdict, "value", verdict)

    return {
        "testcase_id": getattr(case_result, "testcase_id", None),
        "logical_case_name": getattr(case_result, "logical_case_name", None),
        "operation_id": getattr(case_result, "operation_id", None),
        "method": getattr(case_result, "method", None),
        "path": getattr(case_result, "path", None),
        "verdict": verdict_value,
        "summary_message": getattr(case_result, "summary_message", None),
        "expected_statuses": list(getattr(case_result, "expected_statuses", []) or []),
        "actual_status": getattr(case_result, "actual_status", None),
        "status_check_passed": getattr(case_result, "status_check_passed", None),
        "schema_check_passed": getattr(case_result, "schema_check_passed", None),
        "required_fields_check_passed": getattr(case_result, "required_fields_check_passed", None),
        "expected_required_fields": list(getattr(case_result, "expected_required_fields", []) or []),
        "missing_required_fields": list(getattr(case_result, "missing_required_fields", []) or []),
        "network_error": getattr(case_result, "network_error", None),
        "skip_reason": getattr(case_result, "skip_reason", None),
        "issues": [
            _validation_issue_to_dict(issue)
            for issue in list(getattr(case_result, "issues", []) or [])
        ],
    }


def _validation_batch_to_dict(batch_result: ValidationBatchLike) -> dict[str, Any]:
    return {
        "thread_id": batch_result.thread_id,
        "target_name": batch_result.target_name,
        "total_cases": batch_result.total_cases,
        "validated_cases": batch_result.validated_cases,
        "pass_cases": batch_result.pass_cases,
        "fail_cases": batch_result.fail_cases,
        "skip_cases": batch_result.skip_cases,
        "error_cases": batch_result.error_cases,
        "results": [
            _validation_case_to_dict(item)
            for item in batch_result.results
        ],
    }

if __name__ == "__main__":
    main()