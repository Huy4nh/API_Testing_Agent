from __future__ import annotations

import unicodedata
from typing import Any, Protocol, cast

from api_testing_agent.application.workflow_service_models import (
    CancelWorkflowRequest,
    ContinueWorkflowRequest,
    FinalizeWorkflowRequest,
    RerunWorkflowRequest,
    StartWorkflowRequest,
    WorkflowActorContext,
    WorkflowArtifactView,
    WorkflowErrorCode,
    WorkflowErrorResponse,
    WorkflowServiceResponse,
    WorkflowSnapshotView,
    WorkflowView,
)
from api_testing_agent.config import Settings
from api_testing_agent.logging_config import bind_logger, get_logger
from api_testing_agent.tasks.full_workflow_orchestrator import FullWorkflowOrchestrator
from api_testing_agent.tasks.language_support import SupportedLanguage
from api_testing_agent.tasks.workflow_language_policy import WorkflowLanguagePolicy
from api_testing_agent.tasks.workflow_models import (
    FullWorkflowResult,
    WorkflowContextSnapshot,
    WorkflowPhase,
)


class WorkflowOrchestratorProtocol(Protocol):
    def start_from_text(
        self,
        text: str,
        *,
        thread_id: str | None = None,
        language_policy: WorkflowLanguagePolicy | str | None = None,
        selected_language: SupportedLanguage | None = None,
    ) -> FullWorkflowResult:
        ...

    def continue_with_message(
        self,
        *,
        thread_id: str,
        message: str,
    ) -> FullWorkflowResult:
        ...

    def get_snapshot(self, thread_id: str) -> WorkflowContextSnapshot | None:
        ...


class HeadlessWorkflowService:
    """
    Headless application-layer contract for workflow control.

    Adapter bên ngoài nên gọi service này, không gọi trực tiếp FullWorkflowOrchestrator.
    Service này có một lớp normalize UX nhẹ để giảm lỗi route trong các phase hội thoại.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        orchestrator: WorkflowOrchestratorProtocol | None = None,
    ) -> None:
        self._settings = settings
        self._logger = get_logger(__name__)

        if orchestrator is not None:
            self._orchestrator: WorkflowOrchestratorProtocol = orchestrator
        else:
            self._orchestrator = cast(
                WorkflowOrchestratorProtocol,
                FullWorkflowOrchestrator(settings),
            )

        self._logger.info(
            "Initialized HeadlessWorkflowService.",
            extra={"payload_source": "headless_workflow_service_init"},
        )

    def start_workflow(
        self,
        request: StartWorkflowRequest,
    ) -> WorkflowServiceResponse:
        logger = self._bind_request_logger(
            operation="start_workflow",
            actor_context=request.actor_context,
            thread_id=request.thread_id,
        )
        logger.info("Starting workflow through headless service.")

        text = request.text.strip()
        if not text:
            logger.warning("Rejected start_workflow because input text is empty.")
            return self._error_response(
                operation="start_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INVALID_INPUT,
                error_message="Workflow input text must not be empty.",
                recoverable=True,
                suggested_next_actions=["start_workflow"],
            )

        try:
            result = self._orchestrator.start_from_text(
                text,
                thread_id=self._clean_optional_text(request.thread_id),
                language_policy=request.language_policy,
                selected_language=request.selected_language,
            )

            logger.info(
                "Workflow started successfully.",
                extra={
                    "thread_id": result.thread_id,
                    "workflow_id": result.workflow_id,
                    "phase": result.phase.value,
                },
            )

            return self._workflow_response(
                operation="start_workflow",
                actor_context=request.actor_context,
                result=result,
            )

        except Exception as exc:
            logger.exception("Headless start_workflow failed.")
            return self._error_response(
                operation="start_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INTERNAL_WORKFLOW_ERROR,
                error_message=f"Failed to start workflow: {exc}",
                recoverable=True,
                suggested_next_actions=["start_workflow", "help"],
            )

    def continue_workflow(
        self,
        request: ContinueWorkflowRequest,
    ) -> WorkflowServiceResponse:
        thread_id = request.thread_id.strip()
        logger = self._bind_request_logger(
            operation="continue_workflow",
            actor_context=request.actor_context,
            thread_id=thread_id,
        )
        logger.info("Continuing workflow through headless service.")

        if not thread_id:
            logger.warning("Rejected continue_workflow because thread_id is empty.")
            return self._error_response(
                operation="continue_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INVALID_INPUT,
                error_message="thread_id must not be empty.",
                recoverable=True,
                suggested_next_actions=["start_workflow"],
            )

        message = request.message.strip()
        if not message:
            logger.warning("Rejected continue_workflow because message is empty.")
            return self._error_response(
                operation="continue_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INVALID_INPUT,
                error_message="Continuation message must not be empty.",
                recoverable=True,
                suggested_next_actions=["continue_workflow", "get_workflow_status"],
                details={"thread_id": thread_id},
            )

        snapshot = self._orchestrator.get_snapshot(thread_id)
        if snapshot is None:
            logger.warning("Workflow not found for continue_workflow.")
            return self._workflow_not_found_response(
                operation="continue_workflow",
                actor_context=request.actor_context,
                thread_id=thread_id,
            )

        if self._is_terminal_phase(snapshot.phase):
            logger.warning(
                "Rejected continue_workflow because workflow is terminal.",
                extra={"phase": snapshot.phase.value},
            )
            return self._error_response(
                operation="continue_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INVALID_PHASE_ACTION,
                error_message=(
                    f"Cannot continue workflow in terminal phase "
                    f"`{snapshot.phase.value}`."
                ),
                recoverable=False,
                suggested_next_actions=["get_workflow_status", "start_workflow"],
                details={"thread_id": thread_id, "phase": snapshot.phase.value},
            )

        try:
            routed_message = self._normalize_continue_message_for_phase(
                snapshot=snapshot,
                message=message,
            )

            if routed_message != message:
                logger.info(
                    "Normalized continuation message before passing to orchestrator.",
                    extra={
                        "phase": snapshot.phase.value,
                        "original_message": message,
                        "routed_message": routed_message,
                    },
                )

            result = self._orchestrator.continue_with_message(
                thread_id=thread_id,
                message=routed_message,
            )

            logger.info(
                "Workflow continued successfully.",
                extra={
                    "thread_id": result.thread_id,
                    "workflow_id": result.workflow_id,
                    "phase": result.phase.value,
                },
            )

            return self._workflow_response(
                operation="continue_workflow",
                actor_context=request.actor_context,
                result=result,
            )

        except Exception as exc:
            logger.exception("Headless continue_workflow failed.")
            return self._error_response(
                operation="continue_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INTERNAL_WORKFLOW_ERROR,
                error_message=f"Failed to continue workflow: {exc}",
                recoverable=True,
                suggested_next_actions=["get_workflow_status", "help"],
                details={"thread_id": thread_id},
            )

    def resume_workflow(
        self,
        *,
        thread_id: str,
        actor_context: WorkflowActorContext = WorkflowActorContext(),
    ) -> WorkflowServiceResponse:
        return self.get_workflow_status(
            thread_id=thread_id,
            actor_context=actor_context,
        )

    def get_workflow_status(
        self,
        *,
        thread_id: str,
        actor_context: WorkflowActorContext = WorkflowActorContext(),
    ) -> WorkflowServiceResponse:
        cleaned_thread_id = thread_id.strip()
        logger = self._bind_request_logger(
            operation="get_workflow_status",
            actor_context=actor_context,
            thread_id=cleaned_thread_id,
        )
        logger.info("Fetching workflow status through headless service.")

        if not cleaned_thread_id:
            logger.warning("Rejected get_workflow_status because thread_id is empty.")
            return self._error_response(
                operation="get_workflow_status",
                actor_context=actor_context,
                error_code=WorkflowErrorCode.INVALID_INPUT,
                error_message="thread_id must not be empty.",
                recoverable=True,
                suggested_next_actions=["start_workflow"],
            )

        snapshot = self._orchestrator.get_snapshot(cleaned_thread_id)
        if snapshot is None:
            logger.warning("Workflow not found for get_workflow_status.")
            return self._workflow_not_found_response(
                operation="get_workflow_status",
                actor_context=actor_context,
                thread_id=cleaned_thread_id,
            )

        snapshot_view = self._snapshot_to_view(snapshot)
        workflow_view = self._snapshot_to_workflow_view(snapshot)

        logger.info(
            "Workflow status fetched successfully.",
            extra={
                "workflow_id": snapshot.workflow_id,
                "phase": snapshot.phase.value,
            },
        )

        return WorkflowServiceResponse(
            ok=True,
            operation="get_workflow_status",
            actor_context=actor_context,
            workflow=workflow_view,
            snapshot=snapshot_view,
            artifacts=list(snapshot_view.artifact_refs),
        )

    def get_workflow_snapshot(
        self,
        *,
        thread_id: str,
        actor_context: WorkflowActorContext = WorkflowActorContext(),
    ) -> WorkflowServiceResponse:
        cleaned_thread_id = thread_id.strip()
        logger = self._bind_request_logger(
            operation="get_workflow_snapshot",
            actor_context=actor_context,
            thread_id=cleaned_thread_id,
        )
        logger.info("Fetching workflow snapshot through headless service.")

        if not cleaned_thread_id:
            logger.warning("Rejected get_workflow_snapshot because thread_id is empty.")
            return self._error_response(
                operation="get_workflow_snapshot",
                actor_context=actor_context,
                error_code=WorkflowErrorCode.INVALID_INPUT,
                error_message="thread_id must not be empty.",
                recoverable=True,
                suggested_next_actions=["start_workflow"],
            )

        snapshot = self._orchestrator.get_snapshot(cleaned_thread_id)
        if snapshot is None:
            logger.warning("Workflow not found for get_workflow_snapshot.")
            return self._workflow_not_found_response(
                operation="get_workflow_snapshot",
                actor_context=actor_context,
                thread_id=cleaned_thread_id,
            )

        snapshot_view = self._snapshot_to_view(snapshot)

        logger.info(
            "Workflow snapshot fetched successfully.",
            extra={
                "workflow_id": snapshot.workflow_id,
                "phase": snapshot.phase.value,
            },
        )

        return WorkflowServiceResponse(
            ok=True,
            operation="get_workflow_snapshot",
            actor_context=actor_context,
            snapshot=snapshot_view,
            artifacts=list(snapshot_view.artifact_refs),
        )

    def cancel_workflow(
        self,
        request: CancelWorkflowRequest,
    ) -> WorkflowServiceResponse:
        thread_id = request.thread_id.strip()
        logger = self._bind_request_logger(
            operation="cancel_workflow",
            actor_context=request.actor_context,
            thread_id=thread_id,
        )
        logger.info("Cancelling workflow through headless service.")

        if not thread_id:
            logger.warning("Rejected cancel_workflow because thread_id is empty.")
            return self._error_response(
                operation="cancel_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INVALID_INPUT,
                error_message="thread_id must not be empty.",
                recoverable=True,
                suggested_next_actions=["start_workflow"],
            )

        snapshot = self._orchestrator.get_snapshot(thread_id)
        if snapshot is None:
            logger.warning("Workflow not found for cancel_workflow.")
            return self._workflow_not_found_response(
                operation="cancel_workflow",
                actor_context=request.actor_context,
                thread_id=thread_id,
            )

        if snapshot.phase.value in {"cancelled", "finalized"}:
            logger.warning(
                "Rejected cancel_workflow because phase is terminal.",
                extra={"phase": snapshot.phase.value},
            )
            return self._error_response(
                operation="cancel_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INVALID_PHASE_ACTION,
                error_message=f"Cannot cancel workflow in phase `{snapshot.phase.value}`.",
                recoverable=False,
                suggested_next_actions=["get_workflow_status", "start_workflow"],
                details={"thread_id": thread_id, "phase": snapshot.phase.value},
            )

        try:
            result = self._orchestrator.continue_with_message(
                thread_id=thread_id,
                message=request.cancel_message,
            )

            if (
                request.auto_confirm
                and not result.cancelled
                and result.phase.value == "report_interaction"
                and self._looks_like_confirmation_prompt(result.assistant_message)
            ):
                logger.info("Auto-confirming cancel confirmation prompt.")
                result = self._orchestrator.continue_with_message(
                    thread_id=thread_id,
                    message=request.confirmation_message,
                )

            logger.info(
                "Cancel workflow request completed.",
                extra={
                    "workflow_id": result.workflow_id,
                    "phase": result.phase.value,
                    "cancelled": result.cancelled,
                },
            )

            return self._workflow_response(
                operation="cancel_workflow",
                actor_context=request.actor_context,
                result=result,
            )

        except Exception as exc:
            logger.exception("Headless cancel_workflow failed.")
            return self._error_response(
                operation="cancel_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INTERNAL_WORKFLOW_ERROR,
                error_message=f"Failed to cancel workflow: {exc}",
                recoverable=True,
                suggested_next_actions=["get_workflow_status", "help"],
                details={"thread_id": thread_id},
            )

    def finalize_workflow(
        self,
        request: FinalizeWorkflowRequest,
    ) -> WorkflowServiceResponse:
        thread_id = request.thread_id.strip()
        logger = self._bind_request_logger(
            operation="finalize_workflow",
            actor_context=request.actor_context,
            thread_id=thread_id,
        )
        logger.info("Finalizing workflow through headless service.")

        if not thread_id:
            logger.warning("Rejected finalize_workflow because thread_id is empty.")
            return self._error_response(
                operation="finalize_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INVALID_INPUT,
                error_message="thread_id must not be empty.",
                recoverable=True,
                suggested_next_actions=["start_workflow"],
            )

        snapshot = self._orchestrator.get_snapshot(thread_id)
        if snapshot is None:
            logger.warning("Workflow not found for finalize_workflow.")
            return self._workflow_not_found_response(
                operation="finalize_workflow",
                actor_context=request.actor_context,
                thread_id=thread_id,
            )

        if snapshot.phase.value == "finalized":
            logger.warning("Rejected finalize_workflow because workflow is already finalized.")
            return self._error_response(
                operation="finalize_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INVALID_PHASE_ACTION,
                error_message="Workflow is already finalized.",
                recoverable=False,
                suggested_next_actions=["get_workflow_status", "start_workflow"],
                details={"thread_id": thread_id, "phase": snapshot.phase.value},
            )

        if snapshot.phase.value == "cancelled":
            logger.warning("Rejected finalize_workflow because workflow is cancelled.")
            return self._error_response(
                operation="finalize_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INVALID_PHASE_ACTION,
                error_message="Cannot finalize a cancelled workflow.",
                recoverable=False,
                suggested_next_actions=["get_workflow_status", "start_workflow"],
                details={"thread_id": thread_id, "phase": snapshot.phase.value},
            )

        if snapshot.phase.value != "report_interaction":
            logger.warning(
                "Rejected finalize_workflow because phase is not report_interaction.",
                extra={"phase": snapshot.phase.value},
            )
            return self._error_response(
                operation="finalize_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.FINALIZE_NOT_ALLOWED,
                error_message="Finalize is only allowed when the workflow is in report_interaction.",
                recoverable=True,
                suggested_next_actions=["continue_workflow", "get_workflow_status"],
                details={"thread_id": thread_id, "phase": snapshot.phase.value},
            )

        try:
            result = self._orchestrator.continue_with_message(
                thread_id=thread_id,
                message=request.finalize_message,
            )

            if (
                request.auto_confirm
                and not result.finalized
                and result.phase.value == "report_interaction"
                and self._looks_like_confirmation_prompt(result.assistant_message)
            ):
                logger.info("Auto-confirming finalize confirmation prompt.")
                result = self._orchestrator.continue_with_message(
                    thread_id=thread_id,
                    message=request.confirmation_message,
                )

            logger.info(
                "Finalize workflow request completed.",
                extra={
                    "workflow_id": result.workflow_id,
                    "phase": result.phase.value,
                    "finalized": result.finalized,
                },
            )

            return self._workflow_response(
                operation="finalize_workflow",
                actor_context=request.actor_context,
                result=result,
            )

        except Exception as exc:
            logger.exception("Headless finalize_workflow failed.")
            return self._error_response(
                operation="finalize_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INTERNAL_WORKFLOW_ERROR,
                error_message=f"Failed to finalize workflow: {exc}",
                recoverable=True,
                suggested_next_actions=["get_workflow_status", "help"],
                details={"thread_id": thread_id},
            )

    def rerun_workflow(
        self,
        request: RerunWorkflowRequest,
    ) -> WorkflowServiceResponse:
        thread_id = request.thread_id.strip()
        logger = self._bind_request_logger(
            operation="rerun_workflow",
            actor_context=request.actor_context,
            thread_id=thread_id,
        )
        logger.info("Requesting rerun through headless service.")

        if not thread_id:
            logger.warning("Rejected rerun_workflow because thread_id is empty.")
            return self._error_response(
                operation="rerun_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INVALID_INPUT,
                error_message="thread_id must not be empty.",
                recoverable=True,
                suggested_next_actions=["start_workflow"],
            )

        snapshot = self._orchestrator.get_snapshot(thread_id)
        if snapshot is None:
            logger.warning("Workflow not found for rerun_workflow.")
            return self._workflow_not_found_response(
                operation="rerun_workflow",
                actor_context=request.actor_context,
                thread_id=thread_id,
            )

        instruction = request.instruction.strip()
        if not instruction:
            logger.warning("Rejected rerun_workflow because instruction is empty.")
            return self._error_response(
                operation="rerun_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INVALID_INPUT,
                error_message="Rerun instruction must not be empty.",
                recoverable=True,
                suggested_next_actions=["rerun_workflow"],
                details={"thread_id": thread_id},
            )

        if snapshot.phase.value != "report_interaction":
            logger.warning(
                "Rejected rerun_workflow because phase is not report_interaction.",
                extra={"phase": snapshot.phase.value},
            )
            return self._error_response(
                operation="rerun_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.RERUN_NOT_ALLOWED,
                error_message="Rerun is only allowed when the workflow is in report_interaction.",
                recoverable=True,
                suggested_next_actions=["get_workflow_status", "continue_workflow"],
                details={"thread_id": thread_id, "phase": snapshot.phase.value},
            )

        rerun_message = instruction
        if not self._looks_like_rerun_message(instruction):
            rerun_message = f"chạy lại với yêu cầu sau: {instruction}"

        try:
            result = self._orchestrator.continue_with_message(
                thread_id=thread_id,
                message=rerun_message,
            )

            logger.info(
                "Rerun workflow request completed.",
                extra={
                    "workflow_id": result.workflow_id,
                    "phase": result.phase.value,
                    "rerun_requested": result.phase.value == "rerun_requested",
                },
            )

            return self._workflow_response(
                operation="rerun_workflow",
                actor_context=request.actor_context,
                result=result,
            )

        except Exception as exc:
            logger.exception("Headless rerun_workflow failed.")
            return self._error_response(
                operation="rerun_workflow",
                actor_context=request.actor_context,
                error_code=WorkflowErrorCode.INTERNAL_WORKFLOW_ERROR,
                error_message=f"Failed to request rerun: {exc}",
                recoverable=True,
                suggested_next_actions=["get_workflow_status", "help"],
                details={"thread_id": thread_id},
            )

    def list_workflow_artifacts(
        self,
        *,
        thread_id: str,
        actor_context: WorkflowActorContext = WorkflowActorContext(),
    ) -> WorkflowServiceResponse:
        cleaned_thread_id = thread_id.strip()
        logger = self._bind_request_logger(
            operation="list_workflow_artifacts",
            actor_context=actor_context,
            thread_id=cleaned_thread_id,
        )
        logger.info("Listing workflow artifacts through headless service.")

        if not cleaned_thread_id:
            logger.warning("Rejected list_workflow_artifacts because thread_id is empty.")
            return self._error_response(
                operation="list_workflow_artifacts",
                actor_context=actor_context,
                error_code=WorkflowErrorCode.INVALID_INPUT,
                error_message="thread_id must not be empty.",
                recoverable=True,
                suggested_next_actions=["start_workflow"],
            )

        snapshot = self._orchestrator.get_snapshot(cleaned_thread_id)
        if snapshot is None:
            logger.warning("Workflow not found for list_workflow_artifacts.")
            return self._workflow_not_found_response(
                operation="list_workflow_artifacts",
                actor_context=actor_context,
                thread_id=cleaned_thread_id,
            )

        artifacts = self._extract_artifacts_from_snapshot(snapshot)

        logger.info(
            "Workflow artifacts listed successfully.",
            extra={
                "workflow_id": snapshot.workflow_id,
                "artifact_count": len(artifacts),
            },
        )

        return WorkflowServiceResponse(
            ok=True,
            operation="list_workflow_artifacts",
            actor_context=actor_context,
            artifacts=artifacts,
            snapshot=self._snapshot_to_view(snapshot),
        )

    def _workflow_response(
        self,
        *,
        operation: str,
        actor_context: WorkflowActorContext,
        result: FullWorkflowResult,
    ) -> WorkflowServiceResponse:
        workflow = self._result_to_view(result)
        return WorkflowServiceResponse(
            ok=True,
            operation=operation,
            actor_context=actor_context,
            workflow=workflow,
            artifacts=list(workflow.artifacts),
        )

    def _error_response(
        self,
        *,
        operation: str,
        actor_context: WorkflowActorContext,
        error_code: WorkflowErrorCode,
        error_message: str,
        recoverable: bool,
        suggested_next_actions: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> WorkflowServiceResponse:
        return WorkflowServiceResponse(
            ok=False,
            operation=operation,
            actor_context=actor_context,
            error=WorkflowErrorResponse(
                error_code=error_code,
                error_message=error_message,
                recoverable=recoverable,
                suggested_next_actions=list(suggested_next_actions or []),
                details=dict(details or {}),
            ),
        )

    def _workflow_not_found_response(
        self,
        *,
        operation: str,
        actor_context: WorkflowActorContext,
        thread_id: str,
    ) -> WorkflowServiceResponse:
        return self._error_response(
            operation=operation,
            actor_context=actor_context,
            error_code=WorkflowErrorCode.WORKFLOW_NOT_FOUND,
            error_message=f"Workflow thread `{thread_id}` was not found.",
            recoverable=True,
            suggested_next_actions=["start_workflow"],
            details={"thread_id": thread_id},
        )

    def _result_to_view(
        self,
        result: FullWorkflowResult,
    ) -> WorkflowView:
        return WorkflowView(
            workflow_id=result.workflow_id,
            thread_id=result.thread_id,
            phase=result.phase.value,
            current_target=result.selected_target,
            assistant_message=result.assistant_message,
            status_message=result.status_message,
            selected_target=result.selected_target,
            candidate_targets=list(result.candidate_targets),
            selection_question=result.selection_question,
            scope_confirmation_question=result.scope_confirmation_question,
            scope_confirmation_summary=result.scope_confirmation_summary,
            canonical_command=result.canonical_command,
            understanding_explanation=result.understanding_explanation,
            preferred_language=result.preferred_language,
            language_policy=self._policy_to_str(result.language_policy),
            available_actions=list(result.available_actions),
            needs_user_input=result.needs_user_input,
            finalized=result.finalized,
            cancelled=result.cancelled,
            rerun_requested=result.phase.value == "rerun_requested",
            rerun_user_text=result.rerun_user_text,
            artifacts=self._extract_artifacts_from_result(result),
        )

    def _snapshot_to_workflow_view(
        self,
        snapshot: WorkflowContextSnapshot,
    ) -> WorkflowView:
        artifacts = self._extract_artifacts_from_snapshot(snapshot)

        return WorkflowView(
            workflow_id=snapshot.workflow_id,
            thread_id=snapshot.thread_id,
            phase=snapshot.phase.value,
            current_target=snapshot.selected_target,
            assistant_message=None,
            status_message=f"Workflow is currently in phase `{snapshot.phase.value}`.",
            selected_target=snapshot.selected_target,
            candidate_targets=list(snapshot.candidate_targets),
            selection_question=snapshot.selection_question,
            scope_confirmation_question=snapshot.scope_confirmation_question,
            scope_confirmation_summary=snapshot.scope_confirmation_summary,
            canonical_command=snapshot.canonical_command,
            understanding_explanation=snapshot.understanding_explanation,
            preferred_language=snapshot.preferred_language,
            language_policy=self._policy_to_str(snapshot.language_policy),
            available_actions=self._available_actions_for_phase(snapshot.phase),
            needs_user_input=self._needs_user_input_for_phase(snapshot.phase),
            finalized=snapshot.finalized,
            cancelled=snapshot.cancelled,
            rerun_requested=snapshot.rerun_requested,
            rerun_user_text=snapshot.rerun_user_text,
            artifacts=artifacts,
        )

    def _snapshot_to_view(
        self,
        snapshot: WorkflowContextSnapshot,
    ) -> WorkflowSnapshotView:
        artifact_refs = self._extract_artifacts_from_snapshot(snapshot)
        phase_value = snapshot.phase.value

        active_report_session_id = None
        if phase_value in {
            "report_interaction",
            "finalized",
            "cancelled",
            "rerun_requested",
        }:
            active_report_session_id = snapshot.thread_id

        active_review_id = None
        if phase_value in {
            "pending_target_selection",
            "pending_scope_confirmation",
            "pending_review",
            "approved",
        }:
            active_review_id = snapshot.thread_id

        pending_question = (
            snapshot.pending_router_clarification
            or snapshot.selection_question
            or snapshot.scope_confirmation_question
        )

        return WorkflowSnapshotView(
            workflow_id=snapshot.workflow_id,
            thread_id=snapshot.thread_id,
            current_phase=snapshot.phase.value,
            current_subphase=None,
            current_target=snapshot.selected_target,
            original_user_text=snapshot.original_user_text,
            selected_target=snapshot.selected_target,
            candidate_targets=list(snapshot.candidate_targets),
            canonical_command=snapshot.canonical_command,
            understanding_explanation=snapshot.understanding_explanation,
            preferred_language=snapshot.preferred_language,
            language_policy=self._policy_to_str(snapshot.language_policy),
            finalized=snapshot.finalized,
            cancelled=snapshot.cancelled,
            rerun_requested=snapshot.rerun_requested,
            rerun_user_text=snapshot.rerun_user_text,
            pending_question=pending_question,
            last_router_decision=snapshot.last_router_reason,
            last_scope_user_message=snapshot.last_scope_user_message,
            artifact_refs=artifact_refs,
            active_review_id=active_review_id,
            active_report_session_id=active_report_session_id,
        )

    def _extract_artifacts_from_result(
        self,
        result: FullWorkflowResult,
    ) -> list[WorkflowArtifactView]:
        items: list[WorkflowArtifactView] = []

        def add_artifact(
            artifact_type: str,
            stage: str,
            path: str | None,
        ) -> None:
            cleaned = str(path or "").strip()
            if not cleaned:
                return
            items.append(
                WorkflowArtifactView(
                    artifact_type=artifact_type,
                    path=cleaned,
                    stage=stage,
                )
            )

        add_artifact("draft_report_json", "review", result.draft_report_json_path)
        add_artifact("draft_report_md", "review", result.draft_report_md_path)
        add_artifact("execution_report_json", "execution", result.execution_report_json_path)
        add_artifact("execution_report_md", "execution", result.execution_report_md_path)
        add_artifact("validation_report_json", "validation", result.validation_report_json_path)
        add_artifact("validation_report_md", "validation", result.validation_report_md_path)
        add_artifact("staged_final_report_json", "staged_final", result.staged_final_report_json_path)
        add_artifact("staged_final_report_md", "staged_final", result.staged_final_report_md_path)
        add_artifact("final_report_json", "finalized", result.final_report_json_path)
        add_artifact("final_report_md", "finalized", result.final_report_md_path)

        return items

    def _extract_artifacts_from_snapshot(
        self,
        snapshot: WorkflowContextSnapshot,
    ) -> list[WorkflowArtifactView]:
        items: list[WorkflowArtifactView] = []

        def add_artifact(
            artifact_type: str,
            stage: str,
            path: str | None,
        ) -> None:
            cleaned = str(path or "").strip()
            if not cleaned:
                return
            items.append(
                WorkflowArtifactView(
                    artifact_type=artifact_type,
                    path=cleaned,
                    stage=stage,
                )
            )

        add_artifact("draft_report_json", "review", snapshot.artifacts.draft_report_json_path)
        add_artifact("draft_report_md", "review", snapshot.artifacts.draft_report_md_path)
        add_artifact("execution_report_json", "execution", snapshot.artifacts.execution_report_json_path)
        add_artifact("execution_report_md", "execution", snapshot.artifacts.execution_report_md_path)
        add_artifact("validation_report_json", "validation", snapshot.artifacts.validation_report_json_path)
        add_artifact("validation_report_md", "validation", snapshot.artifacts.validation_report_md_path)
        add_artifact("staged_final_report_json", "staged_final", snapshot.artifacts.staged_final_report_json_path)
        add_artifact("staged_final_report_md", "staged_final", snapshot.artifacts.staged_final_report_md_path)
        add_artifact("final_report_json", "finalized", snapshot.artifacts.final_report_json_path)
        add_artifact("final_report_md", "finalized", snapshot.artifacts.final_report_md_path)

        for index, path in enumerate(snapshot.artifacts.artifact_paths, start=1):
            cleaned = str(path or "").strip()
            if not cleaned:
                continue
            items.append(
                WorkflowArtifactView(
                    artifact_type=f"artifact_path_{index}",
                    path=cleaned,
                    stage="misc",
                )
            )

        return items

    def _bind_request_logger(
        self,
        *,
        operation: str,
        actor_context: WorkflowActorContext,
        thread_id: str | None = None,
    ):
        return bind_logger(
            self._logger,
            thread_id=thread_id or "-",
            payload_source=f"headless_workflow_service_{operation}",
            actor_id=actor_context.actor_id or "-",
            session_id=actor_context.session_id or "-",
            user_id=actor_context.user_id or "-",
            org_id=actor_context.org_id or "-",
        )

    def _policy_to_str(
        self,
        policy: WorkflowLanguagePolicy | str | None,
    ) -> str:
        if isinstance(policy, WorkflowLanguagePolicy):
            return policy.value
        return str(policy or WorkflowLanguagePolicy.ADAPTIVE.value)

    def _clean_optional_text(self, value: str | None) -> str | None:
        cleaned = str(value or "").strip()
        return cleaned or None

    def _is_terminal_phase(
        self,
        phase: WorkflowPhase,
    ) -> bool:
        return phase.value in {
            "finalized",
            "cancelled",
            "rerun_requested",
            "error",
        }

    def _needs_user_input_for_phase(
        self,
        phase: WorkflowPhase,
    ) -> bool:
        return phase.value in {
            "idle",
            "pending_target_selection",
            "pending_scope_confirmation",
            "pending_review",
            "report_interaction",
            "error",
        }

    def _available_actions_for_phase(
        self,
        phase: WorkflowPhase,
    ) -> list[str]:
        phase_value = phase.value

        if phase_value == "idle":
            return ["start_workflow"]

        if phase_value == "pending_target_selection":
            return ["continue_workflow", "cancel_workflow", "get_workflow_status"]

        if phase_value == "pending_scope_confirmation":
            return ["continue_workflow", "cancel_workflow", "get_workflow_status"]

        if phase_value == "pending_review":
            return ["continue_workflow", "cancel_workflow", "get_workflow_status"]

        if phase_value in {
            "approved",
            "executing",
            "validating",
            "final_report_staged",
        }:
            return ["get_workflow_status", "list_workflow_artifacts"]

        if phase_value == "report_interaction":
            return [
                "continue_workflow",
                "finalize_workflow",
                "cancel_workflow",
                "rerun_workflow",
                "list_workflow_artifacts",
                "get_workflow_status",
            ]

        if phase_value in {
            "finalized",
            "cancelled",
            "rerun_requested",
            "error",
        }:
            return ["get_workflow_status", "list_workflow_artifacts", "start_workflow"]

        return ["get_workflow_status"]

    def _normalize_continue_message_for_phase(
        self,
        *,
        snapshot: WorkflowContextSnapshot,
        message: str,
    ) -> str:
        phase_value = snapshot.phase.value
        cleaned = message.strip()

        if not cleaned:
            return cleaned

        if phase_value == "pending_target_selection":
            return self._normalize_target_selection_message(cleaned)

        if phase_value == "pending_scope_confirmation":
            return self._normalize_pending_scope_confirmation_message(
                snapshot=snapshot,
                message=cleaned,
            )

        if phase_value == "pending_review":
            return self._normalize_pending_review_message(cleaned)

        return cleaned

    def _normalize_target_selection_message(
        self,
        message: str,
    ) -> str:
        normalized = self._normalize_ascii_text(message)

        production_aliases = {
            "product",
            "product env",
            "product environment",
            "production env",
            "production environment",
            "prod env",
            "prod environment",
            "moi truong product",
            "moi truong production",
            "moi truong prod",
        }
        if normalized in production_aliases:
            return "production"

        staging_aliases = {
            "stage",
            "staging env",
            "staging environment",
            "moi truong stage",
            "moi truong staging",
        }
        if normalized in staging_aliases:
            return "staging"

        local_aliases = {
            "local env",
            "local environment",
            "may local",
            "moi truong local",
        }
        if normalized in local_aliases:
            return "local"

        return message

    def _normalize_pending_scope_confirmation_message(
        self,
        *,
        snapshot: WorkflowContextSnapshot,
        message: str,
    ) -> str:
        """
        Normalize input ở phase pending_scope_confirmation.

        Core đang dễ hiểu câu có `POST /img` thành "xem chi tiết operation".
        Vì vậy ở layer headless, nếu user có ý "chỉ chọn endpoint/group này",
        ta chuyển thành "chỉ test nhóm Img" để core chốt scope thay vì show detail.
        """
        normalized = self._normalize_ascii_text(message)

        if self._looks_like_headless_meta_message(normalized):
            return message

        if self._looks_like_scope_recommendation_request(normalized):
            return message

        if self._looks_like_scope_apply_recommendation(normalized):
            return message

        if self._looks_like_all_scope_selection(normalized):
            return message

        selected_group = self._extract_requested_scope_group(normalized)

        if selected_group is not None and self._looks_like_only_scope_selection(normalized):
            return f"chỉ test nhóm {selected_group}, không test các nhóm khác"

        if selected_group is not None and self._looks_like_direct_scope_selection(normalized):
            return f"chọn nhóm {selected_group}"

        if self._looks_like_priority_only_selection(normalized):
            fallback_group = self._infer_priority_group_from_snapshot(snapshot)
            if fallback_group is not None:
                return f"chỉ test nhóm {fallback_group}, không test các nhóm khác"

        return message

    def _normalize_pending_review_message(
        self,
        message: str,
    ) -> str:
        normalized = self._normalize_ascii_text(message)

        if self._looks_like_headless_meta_message(normalized):
            return message

        if self._looks_like_explicit_review_action(normalized):
            return message

        if self._looks_like_review_revise_feedback(normalized):
            return f"sửa scope theo feedback: {message}"

        return message

    def _looks_like_headless_meta_message(
        self,
        normalized: str,
    ) -> bool:
        meta_tokens = {
            "help",
            "tro giup",
            "huong dan",
            "status",
            "trang thai",
            "phase",
            "dang o buoc nao",
            "dang lam gi",
            "scope hien tai",
            "show review scope",
            "show current scope",
            "dang test nhung gi",
            "dang review cai gi",
            "co nhung chuc nang nao",
            "operation nao",
            "endpoint nao",
            "gi vay",
            "la sao",
            "toi khong hieu",
        }
        return normalized in meta_tokens

    def _looks_like_scope_recommendation_request(
        self,
        normalized: str,
    ) -> bool:
        return any(
            token in normalized
            for token in [
                "goi y",
                "recommend",
                "suggest",
                "nen test gi",
                "nen chon gi",
                "ban chon giup",
                "chon giup",
                "dai di",
            ]
        )

    def _looks_like_scope_apply_recommendation(
        self,
        normalized: str,
    ) -> bool:
        return any(
            token in normalized
            for token in [
                "theo goi y",
                "ap dung goi y",
                "lam theo goi y",
                "trien khai goi y",
                "chon theo goi y",
            ]
        )

    def _looks_like_all_scope_selection(
        self,
        normalized: str,
    ) -> bool:
        return any(
            token in normalized
            for token in [
                "tat ca",
                "toan bo",
                "all",
                "all endpoints",
                "test het",
                "test tat ca",
                "test toan bo",
            ]
        )

    def _looks_like_only_scope_selection(
        self,
        normalized: str,
    ) -> bool:
        return any(
            token in normalized
            for token in [
                "chi",
                "thoi",
                "only",
                "just",
                "khong test",
                "khong chon",
                "exclude",
                "giu lai",
                "tap trung",
            ]
        )

    def _looks_like_direct_scope_selection(
        self,
        normalized: str,
    ) -> bool:
        return any(
            token in normalized
            for token in [
                "chon",
                "test",
                "scope",
                "xac nhan",
                "confirm",
                "proceed",
                "lay",
                "giu",
            ]
        )

    def _looks_like_priority_only_selection(
        self,
        normalized: str,
    ) -> bool:
        return any(
            token in normalized
            for token in [
                "uu tien thoi",
                "cai nao uu tien",
                "cai uu tien",
                "nhom uu tien",
                "top 1",
                "dau tien thoi",
                "first one",
                "priority only",
            ]
        )

    def _extract_requested_scope_group(
        self,
        normalized: str,
    ) -> str | None:
        if any(token in normalized for token in ["/img", "post /img", " img", "image", "generate"]):
            return "Img"

        if any(token in normalized for token in ["/fb", "post /fb", " facebook", " fb"]):
            return "Fb"

        if any(token in normalized for token in ["/yt", "post /yt", " youtube", " yt"]):
            return "Yt"

        if any(token in normalized for token in ["/post/x", "post/x", "post x"]):
            return "Post"

        if any(token in normalized for token in ["/x/content", "x/content", "post /x", " x "]):
            return "X"

        return None

    def _infer_priority_group_from_snapshot(
        self,
        snapshot: WorkflowContextSnapshot,
    ) -> str | None:
        selected_target = self._normalize_ascii_text(str(snapshot.selected_target or ""))
        original_text = self._normalize_ascii_text(str(snapshot.original_user_text or ""))
        pending_question = self._normalize_ascii_text(
            str(
                snapshot.pending_router_clarification
                or snapshot.scope_confirmation_question
                or ""
            )
        )

        combined = f"{selected_target} {original_text} {pending_question}"

        if "img" in combined or "/img" in combined:
            return "Img"

        return None

    def _looks_like_explicit_review_action(
        self,
        normalized: str,
    ) -> bool:
        explicit_tokens = [
            "approve",
            "approved",
            "duyet",
            "ok",
            "ok roi",
            "duoc",
            "duoc roi",
            "on",
            "on roi",
            "tot",
            "tot roi",
            "ngon",
            "trien khai",
            "chay di",
            "tiep tuc",
            "revise",
            "sua",
            "chinh",
            "them",
            "bot",
            "doi",
            "update",
            "change",
            "viet lai",
            "cancel",
            "huy",
            "dung",
            "stop",
        ]
        return any(token in normalized for token in explicit_tokens)

    def _looks_like_review_revise_feedback(
        self,
        normalized: str,
    ) -> bool:
        scope_mutation_tokens = [
            "giu lai",
            "chi giu",
            "chi lay",
            "chi test",
            "chi chay",
            "tap trung",
            "focus",
            "only keep",
            "only test",
            "just keep",
            "just test",
            "keep only",
            "remove",
            "exclude",
            "bo ",
            "loai ",
            "khong test",
            "dung test",
        ]

        operation_tokens = [
            "img",
            "image",
            "generate",
            "generation",
            "/img",
            "fb",
            "facebook",
            "/fb",
            "yt",
            "youtube",
            "/yt",
            "x/content",
            "/x",
            "post/x",
            "/post/x",
        ]

        has_scope_mutation = any(token in normalized for token in scope_mutation_tokens)
        has_operation_signal = any(token in normalized for token in operation_tokens)

        if has_scope_mutation and has_operation_signal:
            return True

        if has_operation_signal and any(token in normalized for token in ["thoi", "only", "just"]):
            return True

        return False

    def _normalize_ascii_text(
        self,
        value: str,
    ) -> str:
        lowered = " ".join(value.strip().lower().split())
        normalized = unicodedata.normalize("NFD", lowered)
        without_accents = "".join(
            ch for ch in normalized if unicodedata.category(ch) != "Mn"
        )
        return without_accents.replace("đ", "d")

    def _looks_like_confirmation_prompt(
        self,
        text: str | None,
    ) -> bool:
        cleaned = str(text or "").strip().lower()
        if not cleaned:
            return False

        tokens = [
            "xác nhận",
            "xac nhan",
            "trả lời `đồng ý` hoặc `không`",
            "reply with `yes` or `no`",
            "do you want to finalize",
            "do you want to cancel",
            "bạn xác nhận",
        ]
        return any(token in cleaned for token in tokens)

    def _looks_like_rerun_message(
        self,
        text: str,
    ) -> bool:
        cleaned = text.strip().lower()
        return any(
            token in cleaned
            for token in [
                "chạy lại",
                "chay lai",
                "rerun",
                "re-run",
                "retest",
                "test lại",
                "test lai",
            ]
        )