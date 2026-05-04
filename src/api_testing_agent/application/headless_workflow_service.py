from __future__ import annotations

from api_testing_agent.application.workflow_service_models import (
    ContinueWorkflowRequest,
    GetWorkflowRequest,
    StartWorkflowRequest,
    WorkflowArtifactDTO,
    WorkflowServiceResponse,
    WorkflowServiceStatus,
    WorkflowStateDTO,
)
from api_testing_agent.config import Settings
from api_testing_agent.logging_config import bind_logger, get_logger
from api_testing_agent.tasks.full_workflow_orchestrator import FullWorkflowOrchestrator
from api_testing_agent.tasks.language_support import coerce_supported_language
from api_testing_agent.tasks.workflow_models import (
    FullWorkflowResult,
    WorkflowContextSnapshot,
)
from api_testing_agent.tasks.workflow_protocols import (
    ReviewOrchestratorProtocol,
    WorkflowRouterProtocol,
    WorkflowRuntimeBridgeProtocol,
)
from api_testing_agent.tasks.workflow_state_store import WorkflowStateStoreProtocol


class HeadlessWorkflowService:
    def __init__(
        self,
        settings: Settings,
        *,
        orchestrator: FullWorkflowOrchestrator | None = None,
        review_orchestrator: ReviewOrchestratorProtocol | None = None,
        router: WorkflowRouterProtocol | None = None,
        runtime_bridge: WorkflowRuntimeBridgeProtocol | None = None,
        state_store: WorkflowStateStoreProtocol | None = None,
    ) -> None:
        self._logger = get_logger(__name__)
        self._settings = settings
        self._orchestrator = orchestrator or FullWorkflowOrchestrator(
            settings,
            review_orchestrator=review_orchestrator,
            router=router,
            runtime_bridge=runtime_bridge,
            state_store=state_store,
        )

        self._logger.info(
            "Initialized HeadlessWorkflowService.",
            extra={"payload_source": "headless_workflow_service_init"},
        )

    def start_workflow(
        self,
        request: StartWorkflowRequest,
    ) -> WorkflowServiceResponse:
        logger = bind_logger(
            self._logger,
            thread_id=request.session_id or "-",
            payload_source="headless_workflow_service_start",
        )
        logger.info("Starting workflow through headless service.")

        try:
            result = self._orchestrator.start_from_text(
                request.user_input,
                thread_id=request.session_id,
                language_policy=request.language_policy,
                selected_language=request.selected_language,
            )
            return self._build_ok_response(result)
        except Exception as exc:
            logger.exception(f"Headless workflow start failed: {exc}")
            return WorkflowServiceResponse(
                status=WorkflowServiceStatus.ERROR,
                state=None,
                error_message=f"Failed to start workflow: {exc}",
            )

    def continue_workflow(
        self,
        request: ContinueWorkflowRequest,
    ) -> WorkflowServiceResponse:
        logger = bind_logger(
            self._logger,
            thread_id=request.thread_id,
            payload_source="headless_workflow_service_continue",
        )
        logger.info("Continuing workflow through headless service.")

        try:
            snapshot = self._orchestrator.get_snapshot(request.thread_id)
            if snapshot is None:
                return WorkflowServiceResponse(
                    status=WorkflowServiceStatus.NOT_FOUND,
                    state=None,
                    error_message=f"Workflow thread `{request.thread_id}` was not found.",
                )

            result = self._orchestrator.continue_with_message(
                thread_id=request.thread_id,
                message=request.user_input,
            )
            return self._build_ok_response(result)
        except Exception as exc:
            logger.exception(f"Headless workflow continuation failed: {exc}")
            return WorkflowServiceResponse(
                status=WorkflowServiceStatus.ERROR,
                state=None,
                error_message=f"Failed to continue workflow: {exc}",
            )

    def get_workflow_status(
        self,
        request: GetWorkflowRequest,
    ) -> WorkflowServiceResponse:
        logger = bind_logger(
            self._logger,
            thread_id=request.thread_id,
            payload_source="headless_workflow_service_get_status",
        )
        logger.info("Getting workflow status through headless service.")

        try:
            snapshot = self._orchestrator.get_snapshot(request.thread_id)
            if snapshot is None:
                return WorkflowServiceResponse(
                    status=WorkflowServiceStatus.NOT_FOUND,
                    state=None,
                    error_message=f"Workflow thread `{request.thread_id}` was not found.",
                )

            state = self._state_from_snapshot(snapshot)
            return WorkflowServiceResponse(
                status=WorkflowServiceStatus.OK,
                state=state,
                error_message=None,
            )
        except Exception as exc:
            logger.exception(f"Headless workflow status lookup failed: {exc}")
            return WorkflowServiceResponse(
                status=WorkflowServiceStatus.ERROR,
                state=None,
                error_message=f"Failed to get workflow status: {exc}",
            )

    def get_workflow_snapshot(
        self,
        request: GetWorkflowRequest,
    ) -> WorkflowServiceResponse:
        return self.get_workflow_status(request)

    def _build_ok_response(
        self,
        result: FullWorkflowResult,
    ) -> WorkflowServiceResponse:
        return WorkflowServiceResponse(
            status=WorkflowServiceStatus.OK,
            state=self._state_from_result(result),
            error_message=None,
        )

    def _state_from_result(
        self,
        result: FullWorkflowResult,
    ) -> WorkflowStateDTO:
        return WorkflowStateDTO(
            workflow_id=result.workflow_id,
            thread_id=result.thread_id,
            phase=result.phase,
            selected_target=result.selected_target,
            canonical_command=result.canonical_command,
            understanding_explanation=result.understanding_explanation,
            preferred_language=coerce_supported_language(
                result.preferred_language,
                fallback="vi",
            ),
            language_policy=result.language_policy,
            finalized=result.finalized,
            cancelled=result.cancelled,
            needs_user_input=result.needs_user_input,
            available_actions=list(result.available_actions),
            assistant_message=result.assistant_message,
            status_message=result.status_message,
            selection_question=result.selection_question,
            rerun_user_text=result.rerun_user_text,
            artifacts=WorkflowArtifactDTO(
                draft_report_json_path=result.draft_report_json_path,
                draft_report_md_path=result.draft_report_md_path,
                execution_report_json_path=result.execution_report_json_path,
                execution_report_md_path=result.execution_report_md_path,
                validation_report_json_path=result.validation_report_json_path,
                validation_report_md_path=result.validation_report_md_path,
                staged_final_report_json_path=result.staged_final_report_json_path,
                staged_final_report_md_path=result.staged_final_report_md_path,
                final_report_json_path=result.final_report_json_path,
                final_report_md_path=result.final_report_md_path,
            ),
        )

    def _state_from_snapshot(
        self,
        snapshot: WorkflowContextSnapshot,
    ) -> WorkflowStateDTO:
        return WorkflowStateDTO(
            workflow_id=snapshot.workflow_id,
            thread_id=snapshot.thread_id,
            phase=snapshot.phase,
            selected_target=snapshot.selected_target,
            canonical_command=snapshot.canonical_command,
            understanding_explanation=snapshot.understanding_explanation,
            preferred_language=coerce_supported_language(
                snapshot.preferred_language,
                fallback="vi",
            ),
            language_policy=snapshot.language_policy,
            finalized=snapshot.finalized,
            cancelled=snapshot.cancelled,
            needs_user_input=snapshot.phase.value not in {"executing", "validating"},
            available_actions=[],
            assistant_message=None,
            status_message=None,
            selection_question=snapshot.selection_question,
            rerun_user_text=snapshot.rerun_user_text,
            artifacts=WorkflowArtifactDTO(
                draft_report_json_path=snapshot.artifacts.draft_report_json_path,
                draft_report_md_path=snapshot.artifacts.draft_report_md_path,
                execution_report_json_path=snapshot.artifacts.execution_report_json_path,
                execution_report_md_path=snapshot.artifacts.execution_report_md_path,
                validation_report_json_path=snapshot.artifacts.validation_report_json_path,
                validation_report_md_path=snapshot.artifacts.validation_report_md_path,
                staged_final_report_json_path=snapshot.artifacts.staged_final_report_json_path,
                staged_final_report_md_path=snapshot.artifacts.staged_final_report_md_path,
                final_report_json_path=snapshot.artifacts.final_report_json_path,
                final_report_md_path=snapshot.artifacts.final_report_md_path,
            ),
        )