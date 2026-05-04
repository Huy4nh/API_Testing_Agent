from pathlib import Path

from api_testing_agent.manual_test.full_workflow.full_workflow_cli import (
    dump_result_json,
    handle_idle_global_input,
    is_terminal_phase,
    render_result,
)
from api_testing_agent.tasks.workflow_models import FullWorkflowResult, WorkflowPhase


def build_result(phase: WorkflowPhase) -> FullWorkflowResult:
    return FullWorkflowResult(
        workflow_id="wf-123",
        thread_id="thread-123",
        phase=phase,
        assistant_message="Đây là phản hồi của assistant.",
        status_message="Workflow status here.",
        selected_target="img_api_staging",
        canonical_command="test target img_api_staging /img POST",
        understanding_explanation="Matched POST /img",
        draft_report_json_path="reports/draft.json",
        draft_report_md_path="reports/draft.md",
        execution_report_json_path="reports/execution.json",
        execution_report_md_path="reports/execution.md",
        validation_report_json_path="reports/validation.json",
        validation_report_md_path="reports/validation.md",
        staged_final_report_json_path="reports/_staging/final.json",
        staged_final_report_md_path="reports/_staging/final.md",
        final_report_json_path="reports/final/final.json" if phase == WorkflowPhase.FINALIZED else None,
        final_report_md_path="reports/final/final.md" if phase == WorkflowPhase.FINALIZED else None,
        rerun_user_text=None,
        finalized=phase == WorkflowPhase.FINALIZED,
        cancelled=phase == WorkflowPhase.CANCELLED,
        needs_user_input=phase not in {WorkflowPhase.FINALIZED, WorkflowPhase.CANCELLED, WorkflowPhase.ERROR},
        available_actions=["status", "help"],
    )


def test_render_result_contains_core_fields():
    result = build_result(WorkflowPhase.PENDING_REVIEW)

    rendered = render_result(result)

    assert "FULL WORKFLOW RESULT" in rendered
    assert "workflow_id        : wf-123" in rendered
    assert "thread_id          : thread-123" in rendered
    assert "phase              : pending_review" in rendered
    assert "selected_target    : img_api_staging" in rendered
    assert "ASSISTANT MESSAGE" in rendered
    assert "Đây là phản hồi của assistant." in rendered


def test_dump_result_json_creates_file(tmp_path: Path):
    result = build_result(WorkflowPhase.REPORT_INTERACTION)

    json_path = dump_result_json(
        thread_id="thread-123",
        result=result,
        output_dir=str(tmp_path),
    )

    output_file = Path(json_path)
    assert output_file.exists()

    content = output_file.read_text(encoding="utf-8")
    assert '"workflow_id": "wf-123"' in content
    assert '"thread_id": "thread-123"' in content
    assert '"phase": "report_interaction"' in content


def test_is_terminal_phase():
    assert is_terminal_phase(WorkflowPhase.FINALIZED) is True
    assert is_terminal_phase(WorkflowPhase.CANCELLED) is True
    assert is_terminal_phase(WorkflowPhase.ERROR) is True

    assert is_terminal_phase(WorkflowPhase.PENDING_REVIEW) is False
    assert is_terminal_phase(WorkflowPhase.REPORT_INTERACTION) is False


def test_handle_idle_global_input_exit():
    handled, should_exit, message = handle_idle_global_input("kết thúc")
    assert handled is True
    assert should_exit is True
    assert message == "Thoát CLI."


def test_handle_idle_global_input_cancel_when_idle():
    handled, should_exit, message = handle_idle_global_input("cancel")
    assert handled is True
    assert should_exit is False
    assert message is not None
    assert "không có workflow active" in message.lower()


def test_handle_idle_global_input_help():
    handled, should_exit, message = handle_idle_global_input("làm sao để dừng")
    assert handled is True
    assert should_exit is False
    assert message is not None
    assert "để thoát cli" in message.lower()