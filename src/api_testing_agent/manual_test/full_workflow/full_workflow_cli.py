from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from api_testing_agent.config import Settings
from api_testing_agent.logging_config import get_logger, setup_logging
from api_testing_agent.tasks.full_workflow_orchestrator import FullWorkflowOrchestrator
from api_testing_agent.tasks.workflow_models import FullWorkflowResult, WorkflowPhase


def render_result(result: FullWorkflowResult) -> str:
    lines: list[str] = []

    lines.append("=" * 100)
    lines.append("FULL WORKFLOW RESULT")
    lines.append("=" * 100)
    lines.append(f"workflow_id        : {result.workflow_id}")
    lines.append(f"thread_id          : {result.thread_id}")
    lines.append(f"phase              : {result.phase.value}")
    lines.append(f"selected_target    : {result.selected_target or '-'}")
    lines.append(f"status_message     : {result.status_message or '-'}")
    lines.append(f"needs_user_input   : {result.needs_user_input}")
    lines.append(f"available_actions  : {', '.join(result.available_actions) if result.available_actions else '-'}")
    lines.append(f"finalized          : {result.finalized}")
    lines.append(f"cancelled          : {result.cancelled}")

    if result.canonical_command:
        lines.append(f"canonical_command  : {result.canonical_command}")

    if result.understanding_explanation:
        lines.append(f"understanding      : {result.understanding_explanation}")

    if result.selection_question:
        lines.append(f"selection_question : {result.selection_question}")

    if result.rerun_user_text:
        lines.append(f"rerun_user_text    : {result.rerun_user_text}")

    lines.append("-" * 100)
    lines.append("ARTIFACTS")
    lines.append("-" * 100)
    lines.append(f"draft_report_json        : {result.draft_report_json_path or '-'}")
    lines.append(f"draft_report_md          : {result.draft_report_md_path or '-'}")
    lines.append(f"execution_report_json    : {result.execution_report_json_path or '-'}")
    lines.append(f"execution_report_md      : {result.execution_report_md_path or '-'}")
    lines.append(f"validation_report_json   : {result.validation_report_json_path or '-'}")
    lines.append(f"validation_report_md     : {result.validation_report_md_path or '-'}")
    lines.append(f"staged_final_report_json : {result.staged_final_report_json_path or '-'}")
    lines.append(f"staged_final_report_md   : {result.staged_final_report_md_path or '-'}")
    lines.append(f"final_report_json        : {result.final_report_json_path or '-'}")
    lines.append(f"final_report_md          : {result.final_report_md_path or '-'}")

    lines.append("-" * 100)
    lines.append("ASSISTANT MESSAGE")
    lines.append("-" * 100)
    lines.append(result.assistant_message or "-")

    return "\n".join(lines)


def dump_result_json(thread_id: str, result: FullWorkflowResult, output_dir: str) -> str:
    import json

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_path = Path(output_dir) / f"full_workflow_cli_{thread_id}.json"
    output_path.write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(output_path)


def is_terminal_phase(phase: WorkflowPhase) -> bool:
    return phase in {
        WorkflowPhase.FINALIZED,
        WorkflowPhase.CANCELLED,
        WorkflowPhase.ERROR,
    }


def normalize_cli_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


def handle_idle_global_input(user_input: str) -> tuple[bool, bool, str | None]:
    """
    Returns:
    - handled: CLI đã xử lý input này chưa
    - should_exit: có nên thoát CLI không
    - message: nội dung cần in ra nếu có
    """
    lowered = normalize_cli_text(user_input)

    exit_tokens = {
        "exit",
        "quit",
        "thoát",
        "thoat",
        "kết thúc",
        "ket thuc",
        "dừng",
        "dung",
        "stop",
    }
    if lowered in exit_tokens:
        return True, True, "Thoát CLI."

    cancel_tokens = {
        "cancel",
        "hủy",
        "huy",
    }
    if lowered in cancel_tokens:
        return True, False, (
            "Hiện không có workflow active để hủy. "
            "Nếu bạn muốn thoát CLI, hãy gõ `exit`, `quit`, `thoát`, hoặc `kết thúc`."
        )

    help_tokens = {
        "help",
        "trợ giúp",
        "tro giup",
        "làm sao để dừng",
        "lam sao de dung",
        "cách thoát",
        "cach thoat",
        "how to exit",
        "how do i stop",
    }
    if lowered in help_tokens:
        return True, False, (
            "Bạn đang ở trạng thái idle, chưa có workflow active.\n"
            "- Để bắt đầu workflow mới: nhập yêu cầu test mới\n"
            "- Để thoát CLI: gõ `exit`, `quit`, `thoát`, hoặc `kết thúc`"
        )

    return False, False, None


def run_cli() -> int:
    setup_logging()
    logger = get_logger(__name__)

    settings = Settings()
    orchestrator = FullWorkflowOrchestrator(settings)

    print("=" * 100)
    print("FULL WORKFLOW CLI")
    print("=" * 100)
    print("Gõ yêu cầu test mới để bắt đầu.")
    print("Ví dụ:")
    print("- test target img_api_staging module image POST")
    print("- hãy thử chức năng sinh ảnh của img ở staging")
    print("- test target cms_local module posts GET")
    print("Gõ 'exit' để thoát.")
    print()

    thread_id: str | None = None
    last_result: FullWorkflowResult | None = None

    while True:
        try:
            user_input = input("Bạn: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nThoát CLI.")
            return 0

        if not user_input:
            print("Tin nhắn rỗng, hãy nhập lại.")
            continue

        handled, should_exit, idle_message = handle_idle_global_input(user_input) if thread_id is None else (False, False, None)
        if handled:
            if idle_message:
                print(idle_message)
                print()
            if should_exit:
                return 0
            continue

        try:
            if thread_id is None:
                result = orchestrator.start_from_text(user_input)
                thread_id = result.thread_id
            else:
                result = orchestrator.continue_with_message(
                    thread_id=thread_id,
                    message=user_input,
                )

            print(render_result(result))
            json_dump_path = dump_result_json(
                thread_id=result.thread_id or "unknown",
                result=result,
                output_dir="./debug/full_workflow_cli",
            )
            print(f"\n[debug] Result JSON dump: {json_dump_path}\n")

            last_result = result

            if is_terminal_phase(result.phase):
                logger.info(
                    "Workflow reached terminal phase.",
                    extra={
                        "thread_id": result.thread_id,
                        "payload_source": "full_workflow_cli_terminal_phase",
                    },
                )
                print("Workflow đã ở phase kết thúc. Nếu muốn test mới, hãy nhập yêu cầu mới.")
                print()

                thread_id = None
                last_result = None

        except Exception as exc:
            logger.exception(f"CLI runtime failure: {exc}")
            print(f"\n[LỖI] CLI runtime failure: {exc}\n")

            if last_result is not None and is_terminal_phase(last_result.phase):
                thread_id = None
                last_result = None

    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())