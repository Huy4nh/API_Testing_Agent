from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from api_testing_agent.application.headless_workflow_service import HeadlessWorkflowService
from api_testing_agent.application.workflow_service_models import (
    CancelWorkflowRequest,
    ContinueWorkflowRequest,
    FinalizeWorkflowRequest,
    RerunWorkflowRequest,
    StartWorkflowRequest,
    WorkflowActorContext,
    WorkflowErrorCode,
)
from api_testing_agent.tasks.workflow_language_policy import WorkflowLanguagePolicy
from api_testing_agent.tasks.workflow_models import (
    FullWorkflowResult,
    WorkflowArtifactRefs,
    WorkflowContextSnapshot,
    WorkflowPhase,
)


@dataclass
class FakeSettings:
    """
    Settings giả cho unit test.

    HeadlessWorkflowService chỉ cần settings khi tự khởi tạo FullWorkflowOrchestrator.
    Trong test ta luôn inject FakeOrchestrator nên object này không cần field thật.
    """

    name: str = "fake-settings"


class FakeOrchestrator:
    """
    Fake orchestrator để test service layer độc lập với:
    - LLM
    - OpenAPI file
    - HTTP execution
    - LangGraph runtime thật

    Mục tiêu test ở đây:
    - service validate input đúng
    - service map result/snapshot sang DTO đúng
    - status/snapshot/artifacts là read-only
    - finalize/cancel/rerun guard phase đúng
    """

    def __init__(self) -> None:
        self.snapshots: dict[str, WorkflowContextSnapshot] = {}
        self.start_calls: list[dict[str, Any]] = []
        self.continue_calls: list[dict[str, Any]] = []
        self.next_continue_results: list[FullWorkflowResult] = []

    def start_from_text(
        self,
        text: str,
        *,
        thread_id: str | None = None,
        language_policy: WorkflowLanguagePolicy | str | None = None,
        selected_language: str | None = None,
    ) -> FullWorkflowResult:
        resolved_thread_id = thread_id or "thread-started"
        self.start_calls.append(
            {
                "text": text,
                "thread_id": thread_id,
                "language_policy": language_policy,
                "selected_language": selected_language,
            }
        )

        snapshot = make_snapshot(
            thread_id=resolved_thread_id,
            phase=WorkflowPhase.PENDING_REVIEW,
            selected_target="img_api_staging",
        )
        self.snapshots[resolved_thread_id] = snapshot

        return make_result(
            thread_id=resolved_thread_id,
            phase=WorkflowPhase.PENDING_REVIEW,
            selected_target="img_api_staging",
            assistant_message="Đây là draft testcase, bạn approve/revise/cancel.",
            available_actions=["approve", "revise", "cancel"],
        )

    def continue_with_message(
        self,
        *,
        thread_id: str,
        message: str,
    ) -> FullWorkflowResult:
        self.continue_calls.append(
            {
                "thread_id": thread_id,
                "message": message,
            }
        )

        if self.next_continue_results:
            result = self.next_continue_results.pop(0)
            self.snapshots[thread_id] = make_snapshot(
                thread_id=thread_id,
                phase=result.phase,
                selected_target=result.selected_target,
                finalized=result.finalized,
                cancelled=result.cancelled,
                rerun_requested=result.phase == WorkflowPhase.RERUN_REQUESTED,
                rerun_user_text=result.rerun_user_text,
            )
            return result

        return make_result(
            thread_id=thread_id,
            phase=WorkflowPhase.PENDING_REVIEW,
            selected_target="img_api_staging",
            assistant_message=f"Received: {message}",
            available_actions=["approve", "revise", "cancel"],
        )

    def get_snapshot(
        self,
        thread_id: str,
    ) -> WorkflowContextSnapshot | None:
        return self.snapshots.get(thread_id)


def make_service(
    fake_orchestrator: FakeOrchestrator,
) -> HeadlessWorkflowService:
    return HeadlessWorkflowService(
        settings=FakeSettings(),  # type: ignore[arg-type]
        orchestrator=fake_orchestrator,
    )


def make_snapshot(
    *,
    thread_id: str = "thread-1",
    phase: WorkflowPhase = WorkflowPhase.PENDING_REVIEW,
    selected_target: str | None = "img_api_staging",
    finalized: bool = False,
    cancelled: bool = False,
    rerun_requested: bool = False,
    rerun_user_text: str | None = None,
) -> WorkflowContextSnapshot:
    artifacts = WorkflowArtifactRefs(
        draft_report_json_path="reports/testcase_drafts/thread-1/draft.json",
        draft_report_md_path="reports/testcase_drafts/thread-1/draft.md",
        artifact_paths=["reports/misc/extra.txt"],
    )

    return WorkflowContextSnapshot(
        workflow_id="workflow-1",
        thread_id=thread_id,
        phase=phase,
        original_user_text="test target img_api_staging",
        selected_target=selected_target,
        candidate_targets=[selected_target] if selected_target else [],
        canonical_command="test target img_api_staging /img POST",
        understanding_explanation="Matched target and operation.",
        preferred_language="vi",
        language_policy=WorkflowLanguagePolicy.ADAPTIVE,
        artifacts=artifacts,
        finalized=finalized,
        cancelled=cancelled,
        rerun_requested=rerun_requested,
        rerun_user_text=rerun_user_text,
        last_router_reason="test-router-reason",
    )


def make_result(
    *,
    thread_id: str = "thread-1",
    phase: WorkflowPhase = WorkflowPhase.PENDING_REVIEW,
    selected_target: str | None = "img_api_staging",
    assistant_message: str | None = "assistant message",
    finalized: bool = False,
    cancelled: bool = False,
    rerun_user_text: str | None = None,
    available_actions: list[str] | None = None,
) -> FullWorkflowResult:
    return FullWorkflowResult(
        workflow_id="workflow-1",
        thread_id=thread_id,
        phase=phase,
        assistant_message=assistant_message,
        status_message=f"phase={phase.value}",
        selected_target=selected_target,
        candidate_targets=[selected_target] if selected_target else [],
        canonical_command="test target img_api_staging /img POST",
        understanding_explanation="Matched target and operation.",
        preferred_language="vi",
        language_policy=WorkflowLanguagePolicy.ADAPTIVE,
        draft_report_json_path="reports/testcase_drafts/thread-1/draft.json",
        draft_report_md_path="reports/testcase_drafts/thread-1/draft.md",
        finalized=finalized,
        cancelled=cancelled,
        rerun_user_text=rerun_user_text,
        needs_user_input=True,
        available_actions=available_actions or ["continue_workflow"],
    )


def test_start_workflow_success_maps_result_to_workflow_view() -> None:
    fake = FakeOrchestrator()
    service = make_service(fake)

    response = service.start_workflow(
        StartWorkflowRequest(
            text="test target img_api_staging",
            thread_id="thread-custom",
            actor_context=WorkflowActorContext(actor_id="tester"),
        )
    )

    assert response.ok is True
    assert response.error is None
    assert response.workflow is not None
    assert response.workflow.thread_id == "thread-custom"
    assert response.workflow.phase == WorkflowPhase.PENDING_REVIEW.value
    assert response.workflow.selected_target == "img_api_staging"
    assert response.workflow.artifacts

    assert fake.start_calls == [
        {
            "text": "test target img_api_staging",
            "thread_id": "thread-custom",
            "language_policy": None,
            "selected_language": None,
        }
    ]


def test_start_workflow_rejects_empty_text() -> None:
    fake = FakeOrchestrator()
    service = make_service(fake)

    response = service.start_workflow(StartWorkflowRequest(text="   "))

    assert response.ok is False
    assert response.error is not None
    assert response.error.error_code == WorkflowErrorCode.INVALID_INPUT
    assert response.error.recoverable is True
    assert fake.start_calls == []


def test_continue_workflow_returns_not_found_when_thread_missing() -> None:
    fake = FakeOrchestrator()
    service = make_service(fake)

    response = service.continue_workflow(
        ContinueWorkflowRequest(
            thread_id="missing-thread",
            message="approve",
        )
    )

    assert response.ok is False
    assert response.error is not None
    assert response.error.error_code == WorkflowErrorCode.WORKFLOW_NOT_FOUND
    assert fake.continue_calls == []


def test_continue_workflow_rejects_terminal_phase() -> None:
    fake = FakeOrchestrator()
    fake.snapshots["thread-final"] = make_snapshot(
        thread_id="thread-final",
        phase=WorkflowPhase.FINALIZED,
        finalized=True,
    )
    service = make_service(fake)

    response = service.continue_workflow(
        ContinueWorkflowRequest(
            thread_id="thread-final",
            message="hello",
        )
    )

    assert response.ok is False
    assert response.error is not None
    assert response.error.error_code == WorkflowErrorCode.INVALID_PHASE_ACTION
    assert fake.continue_calls == []


def test_get_workflow_status_is_read_only_and_does_not_call_continue() -> None:
    fake = FakeOrchestrator()
    fake.snapshots["thread-1"] = make_snapshot(thread_id="thread-1")
    service = make_service(fake)

    response = service.get_workflow_status(thread_id="thread-1")

    assert response.ok is True
    assert response.workflow is not None
    assert response.snapshot is not None
    assert response.workflow.phase == WorkflowPhase.PENDING_REVIEW.value
    assert response.snapshot.current_phase == WorkflowPhase.PENDING_REVIEW.value

    # Điểm quan trọng nhất: status không được đẩy message "status" vào workflow.
    assert fake.continue_calls == []


def test_get_workflow_snapshot_returns_snapshot_view() -> None:
    fake = FakeOrchestrator()
    fake.snapshots["thread-1"] = make_snapshot(thread_id="thread-1")
    service = make_service(fake)

    response = service.get_workflow_snapshot(thread_id="thread-1")

    assert response.ok is True
    assert response.snapshot is not None
    assert response.snapshot.thread_id == "thread-1"
    assert response.snapshot.current_phase == WorkflowPhase.PENDING_REVIEW.value
    assert response.snapshot.active_review_id == "thread-1"
    assert response.snapshot.active_report_session_id is None


def test_list_workflow_artifacts_returns_artifact_refs() -> None:
    fake = FakeOrchestrator()
    fake.snapshots["thread-1"] = make_snapshot(thread_id="thread-1")
    service = make_service(fake)

    response = service.list_workflow_artifacts(thread_id="thread-1")

    assert response.ok is True
    assert len(response.artifacts) == 3

    artifact_types = {item.artifact_type for item in response.artifacts}
    assert "draft_report_json" in artifact_types
    assert "draft_report_md" in artifact_types
    assert "artifact_path_1" in artifact_types


def test_finalize_workflow_requires_report_interaction_phase() -> None:
    fake = FakeOrchestrator()
    fake.snapshots["thread-review"] = make_snapshot(
        thread_id="thread-review",
        phase=WorkflowPhase.PENDING_REVIEW,
    )
    service = make_service(fake)

    response = service.finalize_workflow(
        FinalizeWorkflowRequest(thread_id="thread-review")
    )

    assert response.ok is False
    assert response.error is not None
    assert response.error.error_code == WorkflowErrorCode.FINALIZE_NOT_ALLOWED
    assert fake.continue_calls == []


def test_finalize_workflow_auto_confirms_when_confirmation_prompt_appears() -> None:
    fake = FakeOrchestrator()
    fake.snapshots["thread-report"] = make_snapshot(
        thread_id="thread-report",
        phase=WorkflowPhase.REPORT_INTERACTION,
    )
    fake.next_continue_results = [
        make_result(
            thread_id="thread-report",
            phase=WorkflowPhase.REPORT_INTERACTION,
            assistant_message="Bạn xác nhận finalize chứ? Trả lời `đồng ý` hoặc `không`.",
            finalized=False,
        ),
        make_result(
            thread_id="thread-report",
            phase=WorkflowPhase.FINALIZED,
            assistant_message="Đã finalize report.",
            finalized=True,
        ),
    ]
    service = make_service(fake)

    response = service.finalize_workflow(
        FinalizeWorkflowRequest(thread_id="thread-report", auto_confirm=True)
    )

    assert response.ok is True
    assert response.workflow is not None
    assert response.workflow.finalized is True
    assert response.workflow.phase == WorkflowPhase.FINALIZED.value

    assert fake.continue_calls == [
        {"thread_id": "thread-report", "message": "lưu"},
        {"thread_id": "thread-report", "message": "đồng ý"},
    ]


def test_cancel_workflow_rejects_finalized_phase() -> None:
    fake = FakeOrchestrator()
    fake.snapshots["thread-final"] = make_snapshot(
        thread_id="thread-final",
        phase=WorkflowPhase.FINALIZED,
        finalized=True,
    )
    service = make_service(fake)

    response = service.cancel_workflow(
        CancelWorkflowRequest(thread_id="thread-final")
    )

    assert response.ok is False
    assert response.error is not None
    assert response.error.error_code == WorkflowErrorCode.INVALID_PHASE_ACTION
    assert fake.continue_calls == []


def test_cancel_workflow_auto_confirms_when_confirmation_prompt_appears() -> None:
    fake = FakeOrchestrator()
    fake.snapshots["thread-report"] = make_snapshot(
        thread_id="thread-report",
        phase=WorkflowPhase.REPORT_INTERACTION,
    )
    fake.next_continue_results = [
        make_result(
            thread_id="thread-report",
            phase=WorkflowPhase.REPORT_INTERACTION,
            assistant_message="Bạn xác nhận hủy chứ? Trả lời `đồng ý` hoặc `không`.",
            cancelled=False,
        ),
        make_result(
            thread_id="thread-report",
            phase=WorkflowPhase.CANCELLED,
            assistant_message="Đã hủy report session.",
            cancelled=True,
        ),
    ]
    service = make_service(fake)

    response = service.cancel_workflow(
        CancelWorkflowRequest(thread_id="thread-report", auto_confirm=True)
    )

    assert response.ok is True
    assert response.workflow is not None
    assert response.workflow.cancelled is True
    assert response.workflow.phase == WorkflowPhase.CANCELLED.value

    assert fake.continue_calls == [
        {"thread_id": "thread-report", "message": "hủy"},
        {"thread_id": "thread-report", "message": "đồng ý"},
    ]


def test_rerun_workflow_requires_report_interaction_phase() -> None:
    fake = FakeOrchestrator()
    fake.snapshots["thread-review"] = make_snapshot(
        thread_id="thread-review",
        phase=WorkflowPhase.PENDING_REVIEW,
    )
    service = make_service(fake)

    response = service.rerun_workflow(
        RerunWorkflowRequest(
            thread_id="thread-review",
            instruction="bỏ YT và chạy lại",
        )
    )

    assert response.ok is False
    assert response.error is not None
    assert response.error.error_code == WorkflowErrorCode.RERUN_NOT_ALLOWED
    assert fake.continue_calls == []


def test_rerun_workflow_wraps_plain_instruction_into_rerun_message() -> None:
    fake = FakeOrchestrator()
    fake.snapshots["thread-report"] = make_snapshot(
        thread_id="thread-report",
        phase=WorkflowPhase.REPORT_INTERACTION,
    )
    fake.next_continue_results = [
        make_result(
            thread_id="thread-report",
            phase=WorkflowPhase.RERUN_REQUESTED,
            assistant_message="Đã chuẩn bị rerun.",
            rerun_user_text="chạy lại với yêu cầu sau: bỏ YT",
        )
    ]
    service = make_service(fake)

    response = service.rerun_workflow(
        RerunWorkflowRequest(
            thread_id="thread-report",
            instruction="bỏ YT",
        )
    )

    assert response.ok is True
    assert response.workflow is not None
    assert response.workflow.rerun_requested is True
    assert response.workflow.phase == WorkflowPhase.RERUN_REQUESTED.value

    assert fake.continue_calls == [
        {
            "thread_id": "thread-report",
            "message": "chạy lại với yêu cầu sau: bỏ YT",
        }
    ]


def test_rerun_workflow_keeps_instruction_when_it_already_looks_like_rerun() -> None:
    fake = FakeOrchestrator()
    fake.snapshots["thread-report"] = make_snapshot(
        thread_id="thread-report",
        phase=WorkflowPhase.REPORT_INTERACTION,
    )
    fake.next_continue_results = [
        make_result(
            thread_id="thread-report",
            phase=WorkflowPhase.RERUN_REQUESTED,
            assistant_message="Đã chuẩn bị rerun.",
            rerun_user_text="chạy lại nhưng chỉ test positive",
        )
    ]
    service = make_service(fake)

    response = service.rerun_workflow(
        RerunWorkflowRequest(
            thread_id="thread-report",
            instruction="chạy lại nhưng chỉ test positive",
        )
    )

    assert response.ok is True
    assert fake.continue_calls == [
        {
            "thread_id": "thread-report",
            "message": "chạy lại nhưng chỉ test positive",
        }
    ]