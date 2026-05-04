from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from api_testing_agent.tasks.orchestrator import ReviewWorkflowResult
from api_testing_agent.tasks.workflow_models import PostApprovalRuntimeResult, ReportInteractionUpdate

from api_testing_agent.tasks.workflow_models import RouterDecision, WorkflowContextSnapshot

@runtime_checkable
class WorkflowRouterProtocol(Protocol):
    def route(
        self,
        *,
        message: str,
        snapshot: WorkflowContextSnapshot | None,
    ) -> RouterDecision:
        ...
        
@runtime_checkable
class ReviewOrchestratorProtocol(Protocol):
    def start_review_from_text(
        self,
        text: str,
        *,
        thread_id: str | None = None,
    ) -> ReviewWorkflowResult: ...

    def resume_target_selection(
        self,
        thread_id: str,
        *,
        selection: str,
    ) -> ReviewWorkflowResult: ...

    def resume_scope_confirmation(
        self,
        thread_id: str,
        *,
        user_message: str,
    ) -> ReviewWorkflowResult: ...

    def resume_review(
        self,
        thread_id: str,
        *,
        action: str,
        feedback: str = "",
    ) -> ReviewWorkflowResult: ...

    def get_review_state_values(self, thread_id: str) -> dict[str, Any]: ...

    def get_approved_execution_payload(self, thread_id: str) -> dict[str, Any]: ...


@runtime_checkable
class WorkflowRuntimeBridgeProtocol(Protocol):
    def normalize_review_input(
        self,
        *,
        raw_action: str,
        thread_id: str,
        target_name: str | None,
        preview_text: str,
        feedback_history: list[str],
    ) -> tuple[str, str]:
        ...

    def run_post_approval(
        self,
        *,
        approved_payload: dict[str, Any],
        original_request: str,
        candidate_targets_history: list[str],
        target_selection_question: str | None,
        review_feedback_history: list[str],
    ) -> PostApprovalRuntimeResult:
        ...

    def continue_report_interaction(
        self,
        *,
        thread_id: str,
        user_message: str,
        previous_assistant_count: int,
    ) -> ReportInteractionUpdate:
        ...

    def persist_finalized_run(
        self,
        *,
        final_report_payload: dict[str, Any],
        finalized_final_report_json_path: str | None,
        finalized_final_report_md_path: str,
        execution_batch_result: Any,
        validation_batch_result: Any,
        messages: list[dict[str, Any]],
    ) -> None:
        ...