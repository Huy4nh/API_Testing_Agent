from __future__ import annotations

import json
import traceback
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from api_testing_agent.config import Settings
from api_testing_agent.core.execution_engine import ExecutionEngine
from api_testing_agent.core.execution_log_formatter import ExecutionLogFormatter
from api_testing_agent.core.execution_models import ExecutionBatchResult, ExecutionCaseResult
from api_testing_agent.core.unknown_output_description_service import (
    UnknownOutputDescriptionService,
)
from api_testing_agent.logging_config import bind_logger, get_logger, setup_logging
from api_testing_agent.tasks.orchestrator import ReviewWorkflowResult, TestOrchestrator


DIVIDER = "=" * 100


def main() -> None:
    setup_logging()
    base_logger = get_logger(__name__)

    settings = Settings()
    orchestrator = TestOrchestrator(settings)

    unknown_output_description_service = UnknownOutputDescriptionService(
        model_name=settings.langchain_model_name,
        model_provider=getattr(settings, "langchain_model_provider", None),
    )

    execution_engine = ExecutionEngine(
        timeout_seconds=settings.http_timeout_seconds,
        unknown_output_description_service=unknown_output_description_service,
    )
    log_formatter = ExecutionLogFormatter()

    thread_id = _generate_thread_id()
    logger = bind_logger(base_logger, thread_id=thread_id)
    logger.info("Started manual execution workflow.")

    try:
        raw_text = input("Nhập lệnh test: ").strip()
        if not raw_text:
            logger.warning("No input provided. Exiting manual workflow.")
            print("Không có input. Kết thúc.")
            return

        logger.info(
            "Received user input for manual workflow.",
            extra={"payload_source": "manual_input"},
        )

        result = orchestrator.start_review_from_text(raw_text, thread_id=thread_id)

        while True:
            _print_review_result(result)

            if result.status in {
                "target_not_found",
                "invalid_function",
                "cancelled",
            }:
                logger.info(
                    f"Workflow ended early with status={result.status}.",
                    extra={"target_name": result.selected_target or "-"},
                )
                return

            if result.status == "pending_target_selection":
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

                action, feedback = _normalize_review_input(raw_action)

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

                    payload = _get_execution_payload(orchestrator, result.thread_id)
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

                    report_paths = _write_execution_reports(
                        settings=settings,
                        batch_result=batch_result,
                    )

                    _print_execution_batch_result(
                        batch_result=batch_result,
                        log_formatter=log_formatter,
                        report_paths=report_paths,
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
                    "Workflow reached approved state directly. Starting execution.",
                    extra={"target_name": result.selected_target or "-"},
                )

                payload = _get_execution_payload(orchestrator, result.thread_id)
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

                report_paths = _write_execution_reports(
                    settings=settings,
                    batch_result=batch_result,
                )

                _print_execution_batch_result(
                    batch_result=batch_result,
                    log_formatter=log_formatter,
                    report_paths=report_paths,
                )
                return

            logger.warning(f"Unhandled workflow status: {result.status}")
            print(f"Trạng thái chưa xử lý: {result.status}")
            return

    except KeyboardInterrupt:
        logger.warning("Manual workflow interrupted by user.")
        print("\nĐã dừng bởi người dùng.")
    except Exception as exc:
        logger.exception(f"Manual workflow failed with exception: {exc}")
        print("\nCó lỗi khi chạy workflow execution test.")
        print(f"Error: {exc}")
        print("\nChi tiết traceback:")
        print(traceback.format_exc())


def _generate_thread_id() -> str:
    return f"cli-exec-{uuid.uuid4().hex}"


def _normalize_review_input(raw_action: str) -> tuple[str, str]:
    cleaned = raw_action.strip()
    lowered = cleaned.lower()

    if lowered == "approve":
        return "approve", ""

    if lowered == "cancel":
        return "cancel", ""

    if lowered in {"feedback", "revise"}:
        return "revise", ""

    return "revise", cleaned


def _get_execution_payload(
    orchestrator: TestOrchestrator,
    thread_id: str,
) -> dict[str, Any]:
    if not hasattr(orchestrator, "get_approved_execution_payload"):
        raise RuntimeError(
            "TestOrchestrator chưa có method 'get_approved_execution_payload'.\n"
            "Hãy thêm method này vào orchestrator trước khi chạy manual execution test."
        )

    payload = orchestrator.get_approved_execution_payload(thread_id)
    if not isinstance(payload, dict):
        raise RuntimeError("Execution payload trả về không hợp lệ.")

    return payload


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
    batch_result: ExecutionBatchResult,
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
        print(log_formatter.format_case_result(case_result))
        _print_execution_case_detail(case_result)


def _print_execution_case_detail(case_result: ExecutionCaseResult) -> None:
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


def _write_execution_reports(
    *,
    settings: Settings,
    batch_result: ExecutionBatchResult,
) -> dict[str, str]:
    root_dir = (
        Path(settings.report_output_dir)
        / "execution_runs"
        / batch_result.target_name
        / batch_result.thread_id
    )
    root_dir.mkdir(parents=True, exist_ok=True)

    json_path = root_dir / "execution_batch.json"
    md_path = root_dir / "execution_batch.md"

    json_payload = asdict(batch_result)
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


def _build_execution_markdown(batch_result: ExecutionBatchResult) -> str:
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
        lines.append(f"## {index}. [{result.test_type}] {result.logical_case_name}")
        lines.append("")
        lines.append(f"- Operation ID: `{result.operation_id}`")
        lines.append(f"- Method: `{result.method}`")
        lines.append(f"- Path: `{result.path}`")
        lines.append(f"- Final URL: `{result.final_url}`")
        lines.append(f"- Expected statuses: `{result.expected_statuses}`")
        lines.append(f"- Actual status: `{result.actual_status}`")
        lines.append(f"- Response time (ms): `{result.response_time_ms:.2f}`")
        lines.append(f"- Executed at: `{result.executed_at}`")
        lines.append(f"- Skip: `{result.skip}`")

        if result.payload_source:
            lines.append(f"- Payload source: `{result.payload_source}`")

        if result.planner_reason:
            lines.append(f"- Planner reason: {result.planner_reason}")

        if result.planner_confidence is not None:
            lines.append(f"- Planner confidence: `{result.planner_confidence:.2f}`")

        if result.skip_reason:
            lines.append(f"- Skip reason: {result.skip_reason}")

        if result.network_error:
            lines.append(f"- Network error: {result.network_error}")

        if result.final_headers:
            lines.append(f"- Headers: `{result.final_headers}`")

        if result.final_query_params:
            lines.append(f"- Query params: `{result.final_query_params}`")

        if result.final_json_body is not None:
            lines.append(f"- JSON body: `{result.final_json_body}`")

        if result.response_json is not None:
            lines.append("- Response JSON:")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(result.response_json, ensure_ascii=False, indent=2))
            lines.append("```")
        elif result.response_text is not None:
            lines.append("- Response text:")
            lines.append("")
            lines.append("```text")
            lines.append(result.response_text)
            lines.append("```")

        lines.append("")

    return "\n".join(lines)


def _pretty_json(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        return str(data)


if __name__ == "__main__":
    main()