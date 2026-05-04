from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typeguard import typechecked
from enum import Enum
from pathlib import Path
from typing import Any

from api_testing_agent.application.headless_workflow_service import HeadlessWorkflowService
from api_testing_agent.application.workflow_service_models import (
    CancelWorkflowRequest,
    ContinueWorkflowRequest,
    FinalizeWorkflowRequest,
    RerunWorkflowRequest,
    StartWorkflowRequest,
    WorkflowActorContext,
    WorkflowArtifactView,
    WorkflowErrorResponse,
    WorkflowServiceResponse,
    WorkflowSnapshotView,
    WorkflowView,
)
from api_testing_agent.config import Settings
from api_testing_agent.logging_config import get_logger, setup_logging


DEBUG_OUTPUT_DIR = "./debug/headless_workflow_cli"
def is_dataclass_instance(value: Any) -> bool:
    """
    Pylance-friendly check.

    dataclasses.is_dataclass(value) trả True cho cả:
    - dataclass instance
    - dataclass class

    dataclasses.asdict() chỉ nhận dataclass instance, nên cần loại class ra.
    """
    return is_dataclass(value) and not isinstance(value, type)

def json_safe(value: Any) -> Any:
    """
    Convert object sang dạng JSON-safe.

    Lý do:
    - WorkflowServiceResponse là dataclass.
    - Một số field có thể là Enum.
    - Một số field sau này có thể là Path/set/tuple.
    """
    if is_dataclass_instance(value):
        return json_safe(asdict(value))

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, set):
        return sorted(json_safe(item) for item in value)

    if isinstance(value, tuple):
        return [json_safe(item) for item in value]

    if isinstance(value, list):
        return [json_safe(item) for item in value]

    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}

    return value

def normalize_cli_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


def is_exit_command(text: str) -> bool:
    lowered = normalize_cli_text(text)
    return lowered in {
        "exit",
        "quit",
        "thoát",
        "thoat",
        "kết thúc",
        "ket thuc",
        "dừng",
        "dung",
        "stop",
        "/exit",
        "/quit",
    }


def is_help_command(text: str) -> bool:
    lowered = normalize_cli_text(text)
    return lowered in {
        "help",
        "/help",
        "?",
        "trợ giúp",
        "tro giup",
    }


def is_new_command(text: str) -> bool:
    lowered = normalize_cli_text(text)
    return lowered in {
        "/new",
        "new",
        "workflow mới",
        "workflow moi",
        "test mới",
        "test moi",
    }


def is_status_command(text: str) -> bool:
    lowered = normalize_cli_text(text)
    return lowered in {
        "/status",
        "status",
        "trạng thái",
        "trang thai",
    }


def is_snapshot_command(text: str) -> bool:
    lowered = normalize_cli_text(text)
    return lowered in {
        "/snapshot",
        "snapshot",
        "debug snapshot",
    }


def is_artifacts_command(text: str) -> bool:
    lowered = normalize_cli_text(text)
    return lowered in {
        "/artifacts",
        "/artifact",
        "artifacts",
        "artifact",
        "reports",
        "report paths",
    }


def is_finalize_command(text: str) -> bool:
    lowered = normalize_cli_text(text)
    return lowered in {
        "/finalize",
        "finalize",
        "save",
        "save report",
        "lưu",
        "luu",
        "chốt",
        "chot",
    }


def is_cancel_command(text: str) -> bool:
    lowered = normalize_cli_text(text)
    return lowered in {
        "/cancel",
        "cancel",
        "hủy",
        "huy",
    }


def parse_rerun_instruction(text: str) -> str | None:
    """
    Parse lệnh rerun semantic.

    Hỗ trợ:
    - /rerun bỏ YT
    - rerun bỏ YT
    - chạy lại nhưng chỉ test positive

    Nếu user chỉ gõ /rerun mà không có instruction, trả chuỗi rỗng để service
    tự trả INVALID_INPUT.
    """
    stripped = text.strip()
    lowered = stripped.lower()

    prefixes = [
        "/rerun",
        "rerun",
        "re-run",
        "retest",
        "chạy lại",
        "chay lai",
        "test lại",
        "test lai",
    ]

    for prefix in prefixes:
        if lowered == prefix:
            return ""

        if lowered.startswith(prefix + " "):
            return stripped[len(prefix):].strip()

    return None


def render_help() -> str:
    return """
HEADLESS WORKFLOW CLI

Mục tiêu:
- Manual verify Bước 9: HeadlessWorkflowService.
- Không gọi trực tiếp FullWorkflowOrchestrator từ CLI này.
- Không sửa core/orchestrator/router/runtime.

Cách dùng:
- Khi chưa có workflow active: nhập yêu cầu test mới.
  Ví dụ:
  test target img_api_staging module image POST
  hãy thử chức năng sinh ảnh của img ở staging
  test target cms_local module posts GET

Lệnh trong lúc có workflow:
- /status                : xem trạng thái workflow, read-only
- /snapshot              : xem snapshot debug, read-only
- /artifacts             : liệt kê report/artifact paths, read-only
- /finalize              : gọi finalize_workflow()
- /cancel                : gọi cancel_workflow()
- /rerun <instruction>   : gọi rerun_workflow()
- /new                   : bỏ active thread hiện tại ở CLI và bắt đầu workflow mới
- /help                  : xem trợ giúp
- /exit                  : thoát

Ghi chú:
- Các input không bắt đầu bằng slash sẽ được gửi vào start_workflow hoặc continue_workflow.
- Sau finalized/cancelled/rerun_requested, CLI vẫn giữ thread để bạn xem /status hoặc /artifacts.
  Gõ /new để bắt đầu workflow khác.
""".strip()


def render_artifact(artifact: WorkflowArtifactView) -> str:
    return (
        f"- [{artifact.stage}] {artifact.artifact_type}: "
        f"{artifact.path} ({artifact.storage_backend})"
    )


def render_error(error: WorkflowErrorResponse) -> str:
    lines: list[str] = []
    lines.append("ERROR")
    lines.append("-" * 100)
    lines.append(f"error_code             : {error.error_code.value}")
    lines.append(f"error_message          : {error.error_message}")
    lines.append(f"recoverable            : {error.recoverable}")

    if error.suggested_next_actions:
        lines.append(
            "suggested_next_actions : "
            + ", ".join(error.suggested_next_actions)
        )

    if error.details:
        lines.append("details                :")
        lines.append(json.dumps(json_safe(error.details), ensure_ascii=False, indent=2))

    return "\n".join(lines)


def render_workflow(workflow: WorkflowView) -> str:
    lines: list[str] = []

    lines.append("WORKFLOW VIEW")
    lines.append("-" * 100)
    lines.append(f"workflow_id              : {workflow.workflow_id}")
    lines.append(f"thread_id                : {workflow.thread_id}")
    lines.append(f"phase                    : {workflow.phase}")
    lines.append(f"current_target           : {workflow.current_target or '-'}")
    lines.append(f"selected_target          : {workflow.selected_target or '-'}")
    lines.append(f"preferred_language       : {workflow.preferred_language}")
    lines.append(f"language_policy          : {workflow.language_policy}")
    lines.append(f"needs_user_input         : {workflow.needs_user_input}")
    lines.append(f"finalized                : {workflow.finalized}")
    lines.append(f"cancelled                : {workflow.cancelled}")
    lines.append(f"rerun_requested          : {workflow.rerun_requested}")

    if workflow.rerun_user_text:
        lines.append(f"rerun_user_text          : {workflow.rerun_user_text}")

    if workflow.available_actions:
        lines.append(
            "available_actions        : "
            + ", ".join(workflow.available_actions)
        )

    if workflow.status_message:
        lines.append(f"status_message           : {workflow.status_message}")

    if workflow.candidate_targets:
        lines.append(
            "candidate_targets        : "
            + ", ".join(workflow.candidate_targets)
        )

    if workflow.selection_question:
        lines.append(f"selection_question       : {workflow.selection_question}")

    if workflow.scope_confirmation_question:
        lines.append(
            f"scope_question           : {workflow.scope_confirmation_question}"
        )

    if workflow.scope_confirmation_summary:
        lines.append(
            f"scope_summary            : {workflow.scope_confirmation_summary}"
        )

    if workflow.canonical_command:
        lines.append(f"canonical_command        : {workflow.canonical_command}")

    if workflow.understanding_explanation:
        lines.append(
            f"understanding            : {workflow.understanding_explanation}"
        )

    lines.append("-" * 100)
    lines.append("ARTIFACTS")
    lines.append("-" * 100)

    if workflow.artifacts:
        lines.extend(render_artifact(item) for item in workflow.artifacts)
    else:
        lines.append("-")

    lines.append("-" * 100)
    lines.append("ASSISTANT MESSAGE")
    lines.append("-" * 100)
    lines.append(workflow.assistant_message or "-")

    return "\n".join(lines)


def render_snapshot(snapshot: WorkflowSnapshotView) -> str:
    lines: list[str] = []

    lines.append("SNAPSHOT VIEW")
    lines.append("-" * 100)
    lines.append(f"workflow_id              : {snapshot.workflow_id}")
    lines.append(f"thread_id                : {snapshot.thread_id}")
    lines.append(f"current_phase            : {snapshot.current_phase}")
    lines.append(f"current_subphase         : {snapshot.current_subphase or '-'}")
    lines.append(f"current_target           : {snapshot.current_target or '-'}")
    lines.append(f"selected_target          : {snapshot.selected_target or '-'}")
    lines.append(f"preferred_language       : {snapshot.preferred_language}")
    lines.append(f"language_policy          : {snapshot.language_policy}")
    lines.append(f"finalized                : {snapshot.finalized}")
    lines.append(f"cancelled                : {snapshot.cancelled}")
    lines.append(f"rerun_requested          : {snapshot.rerun_requested}")
    lines.append(f"active_review_id         : {snapshot.active_review_id or '-'}")
    lines.append(f"active_report_session_id : {snapshot.active_report_session_id or '-'}")

    if snapshot.rerun_user_text:
        lines.append(f"rerun_user_text          : {snapshot.rerun_user_text}")

    if snapshot.original_user_text:
        lines.append(f"original_user_text       : {snapshot.original_user_text}")

    if snapshot.candidate_targets:
        lines.append(
            "candidate_targets        : "
            + ", ".join(snapshot.candidate_targets)
        )

    if snapshot.canonical_command:
        lines.append(f"canonical_command        : {snapshot.canonical_command}")

    if snapshot.understanding_explanation:
        lines.append(
            f"understanding            : {snapshot.understanding_explanation}"
        )

    if snapshot.pending_question:
        lines.append(f"pending_question         : {snapshot.pending_question}")

    if snapshot.last_router_decision:
        lines.append(f"last_router_decision     : {snapshot.last_router_decision}")

    if snapshot.last_scope_user_message:
        lines.append(f"last_scope_user_message  : {snapshot.last_scope_user_message}")

    lines.append("-" * 100)
    lines.append("ARTIFACT REFS")
    lines.append("-" * 100)

    if snapshot.artifact_refs:
        lines.extend(render_artifact(item) for item in snapshot.artifact_refs)
    else:
        lines.append("-")

    return "\n".join(lines)


def render_response(response: WorkflowServiceResponse) -> str:
    lines: list[str] = []

    lines.append("=" * 100)
    lines.append("HEADLESS WORKFLOW SERVICE RESPONSE")
    lines.append("=" * 100)
    lines.append(f"ok        : {response.ok}")
    lines.append(f"operation : {response.operation}")

    actor = response.actor_context
    if actor.actor_id or actor.session_id or actor.user_id or actor.org_id:
        lines.append("-" * 100)
        lines.append("ACTOR CONTEXT")
        lines.append("-" * 100)
        lines.append(f"actor_id   : {actor.actor_id or '-'}")
        lines.append(f"session_id : {actor.session_id or '-'}")
        lines.append(f"user_id    : {actor.user_id or '-'}")
        lines.append(f"org_id     : {actor.org_id or '-'}")

    if response.error is not None:
        lines.append("-" * 100)
        lines.append(render_error(response.error))

    if response.workflow is not None:
        lines.append("-" * 100)
        lines.append(render_workflow(response.workflow))

    if response.snapshot is not None:
        lines.append("-" * 100)
        lines.append(render_snapshot(response.snapshot))

    if response.artifacts and response.workflow is None and response.snapshot is None:
        lines.append("-" * 100)
        lines.append("ARTIFACTS")
        lines.append("-" * 100)
        lines.extend(render_artifact(item) for item in response.artifacts)

    return "\n".join(lines)


def dump_response_json(
    *,
    response: WorkflowServiceResponse,
    output_dir: str = DEBUG_OUTPUT_DIR,
) -> str:
    """
    Dump response để debug manual.

    Tên file dùng thread_id nếu có, fallback unknown.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    thread_id = "unknown"
    if response.workflow is not None:
        thread_id = response.workflow.thread_id
    elif response.snapshot is not None:
        thread_id = response.snapshot.thread_id
    elif response.error is not None:
        maybe_thread_id = response.error.details.get("thread_id")
        if maybe_thread_id:
            thread_id = str(maybe_thread_id)

    output_path = Path(output_dir) / f"headless_workflow_cli_{thread_id}.json"
    output_path.write_text(
        json.dumps(json_safe(response), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(output_path)


def extract_thread_id(response: WorkflowServiceResponse) -> str | None:
    if response.workflow is not None:
        return response.workflow.thread_id

    if response.snapshot is not None:
        return response.snapshot.thread_id

    return None


def extract_phase(response: WorkflowServiceResponse) -> str | None:
    if response.workflow is not None:
        return response.workflow.phase

    if response.snapshot is not None:
        return response.snapshot.current_phase

    return None


def is_terminal_phase_value(phase: str | None) -> bool:
    return phase in {
        "finalized",
        "cancelled",
        "rerun_requested",
        "error",
    }


def print_response_and_dump(
    response: WorkflowServiceResponse,
    *,
    logger: Any,
) -> None:
    print()
    print(render_response(response))

    dump_path = dump_response_json(response=response)
    print(f"\n[debug] Response JSON dump: {dump_path}\n")

    if response.ok:
        phase = extract_phase(response)
        if is_terminal_phase_value(phase):
            logger.info(
                "Headless workflow reached terminal phase.",
                extra={
                    "thread_id": extract_thread_id(response) or "-",
                    "payload_source": "headless_workflow_cli_terminal_phase",
                    "phase": phase or "-",
                },
            )
            print(
                "Workflow đang ở phase kết thúc. "
                "Bạn vẫn có thể dùng /status hoặc /artifacts, hoặc gõ /new để bắt đầu workflow mới."
            )
            print()


def run_cli() -> int:
    setup_logging()
    logger = get_logger(__name__)

    settings = Settings()
    service = HeadlessWorkflowService(settings)

    actor_context = WorkflowActorContext(
        actor_id="manual_cli",
        session_id="manual_headless_workflow_cli",
        user_id="local_user",
        org_id="local_org",
    )

    print("=" * 100)
    print("HEADLESS WORKFLOW CLI")
    print("=" * 100)
    print("Manual adapter để verify HeadlessWorkflowService.")
    print("Gõ /help để xem lệnh.")
    print("Gõ yêu cầu test mới để bắt đầu.")
    print()
    print("Ví dụ:")
    print("- test target img_api_staging module image POST")
    print("- hãy thử chức năng sinh ảnh của img ở staging")
    print("- test target cms_local module posts GET")
    print()

    active_thread_id: str | None = None
    last_phase: str | None = None

    while True:
        try:
            user_input = input("Bạn: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nThoát CLI.")
            return 0

        if not user_input:
            print("Tin nhắn rỗng, hãy nhập lại.")
            continue

        if is_exit_command(user_input):
            print("Thoát CLI.")
            return 0

        if is_help_command(user_input):
            print()
            print(render_help())
            print()
            continue

        if is_new_command(user_input):
            active_thread_id = None
            last_phase = None
            print("Đã reset active thread ở CLI. Nhập yêu cầu test mới để bắt đầu workflow mới.")
            print()
            continue

        if active_thread_id is None:
            if (
                is_status_command(user_input)
                or is_snapshot_command(user_input)
                or is_artifacts_command(user_input)
                or is_finalize_command(user_input)
                or is_cancel_command(user_input)
                or parse_rerun_instruction(user_input) is not None
            ):
                print(
                    "Hiện chưa có workflow active. "
                    "Hãy nhập yêu cầu test mới trước, hoặc gõ /help để xem hướng dẫn."
                )
                print()
                continue

            logger.info(
                "Starting workflow from headless CLI.",
                extra={"payload_source": "headless_workflow_cli_start"},
            )

            response = service.start_workflow(
                StartWorkflowRequest(
                    text=user_input,
                    actor_context=actor_context,
                )
            )

            if response.ok:
                active_thread_id = extract_thread_id(response)
                last_phase = extract_phase(response)

            print_response_and_dump(response, logger=logger)
            continue

        # Từ đây trở xuống là khi đã có active_thread_id.

        if is_status_command(user_input):
            response = service.get_workflow_status(
                thread_id=active_thread_id,
                actor_context=actor_context,
            )
            last_phase = extract_phase(response) or last_phase
            print_response_and_dump(response, logger=logger)
            continue

        if is_snapshot_command(user_input):
            response = service.get_workflow_snapshot(
                thread_id=active_thread_id,
                actor_context=actor_context,
            )
            last_phase = extract_phase(response) or last_phase
            print_response_and_dump(response, logger=logger)
            continue

        if is_artifacts_command(user_input):
            response = service.list_workflow_artifacts(
                thread_id=active_thread_id,
                actor_context=actor_context,
            )
            last_phase = extract_phase(response) or last_phase
            print_response_and_dump(response, logger=logger)
            continue

        if is_finalize_command(user_input):
            response = service.finalize_workflow(
                FinalizeWorkflowRequest(
                    thread_id=active_thread_id,
                    actor_context=actor_context,
                    auto_confirm=True,
                )
            )
            last_phase = extract_phase(response) or last_phase
            print_response_and_dump(response, logger=logger)
            continue

        if is_cancel_command(user_input):
            response = service.cancel_workflow(
                CancelWorkflowRequest(
                    thread_id=active_thread_id,
                    actor_context=actor_context,
                    auto_confirm=True,
                )
            )
            last_phase = extract_phase(response) or last_phase
            print_response_and_dump(response, logger=logger)
            continue

        rerun_instruction = parse_rerun_instruction(user_input)
        if rerun_instruction is not None:
            response = service.rerun_workflow(
                RerunWorkflowRequest(
                    thread_id=active_thread_id,
                    instruction=rerun_instruction,
                    actor_context=actor_context,
                )
            )
            last_phase = extract_phase(response) or last_phase
            print_response_and_dump(response, logger=logger)
            continue

        if is_terminal_phase_value(last_phase):
            print(
                f"Workflow hiện tại đã ở phase `{last_phase}`. "
                "Dùng /status, /artifacts, hoặc /new để bắt đầu workflow mới."
            )
            print()
            continue

        logger.info(
            "Continuing workflow from headless CLI.",
            extra={
                "thread_id": active_thread_id,
                "payload_source": "headless_workflow_cli_continue",
            },
        )

        response = service.continue_workflow(
            ContinueWorkflowRequest(
                thread_id=active_thread_id,
                message=user_input,
                actor_context=actor_context,
            )
        )

        if response.ok:
            active_thread_id = extract_thread_id(response) or active_thread_id
            last_phase = extract_phase(response) or last_phase

        print_response_and_dump(response, logger=logger)

    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())