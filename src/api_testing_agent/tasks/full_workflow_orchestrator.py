from __future__ import annotations

import re
import uuid
from typing import Any

from api_testing_agent.config import Settings
from api_testing_agent.core.target_registry import TargetRegistryError
from api_testing_agent.logging_config import bind_logger, get_logger
from api_testing_agent.tasks.conversation_router import ConversationRouter
from api_testing_agent.tasks.hybrid_conversation_router import HybridConversationRouter
from api_testing_agent.tasks.language_support import SupportedLanguage
from api_testing_agent.tasks.operation_catalog_formatter import (
    format_operation_description,
)
from api_testing_agent.tasks.orchestrator import ReviewWorkflowResult, TestOrchestrator
from api_testing_agent.tasks.workflow_language_policy import (
    WorkflowLanguagePolicy,
    WorkflowLanguagePolicyService,
)
from api_testing_agent.tasks.workflow_language_preference import (
    WorkflowLanguagePreferenceResolver,
)
from api_testing_agent.tasks.workflow_models import (
    FullWorkflowResult,
    RouterIntent,
    ScopeRecommendationMode,
    ScopeSelectionMode,
    WorkflowArtifactRefs,
    WorkflowContextSnapshot,
    WorkflowPhase,
    WorkflowScopeCatalogGroup,
    WorkflowScopeCatalogOperation,
    WorkflowScopeRecommendation,
)
from api_testing_agent.tasks.workflow_protocols import (
    ReviewOrchestratorProtocol,
    WorkflowRouterProtocol,
    WorkflowRuntimeBridgeProtocol,
)
from api_testing_agent.tasks.workflow_runtime_bridge import WorkflowRuntimeBridge
from api_testing_agent.tasks.workflow_state_store import (
    InMemoryWorkflowStateStore,
    WorkflowStateStoreProtocol,
)
from api_testing_agent.tasks.workflow_text_localizer import WorkflowTextLocalizer
from api_testing_agent.core.scope_recommendation_agent import ScopeRecommendationAgent

class FullWorkflowOrchestrator:
    def __init__(
        self,
        settings: Settings,
        *,
        review_orchestrator: ReviewOrchestratorProtocol | None = None,
        router: WorkflowRouterProtocol | None = None,
        runtime_bridge: WorkflowRuntimeBridgeProtocol | None = None,
        state_store: WorkflowStateStoreProtocol | None = None,
    ) -> None:
        self._settings = settings
        self._logger = get_logger(__name__)

        self._review_orchestrator: ReviewOrchestratorProtocol = (
            review_orchestrator or TestOrchestrator(settings)
        )
        self._router: WorkflowRouterProtocol = router or HybridConversationRouter(
            deterministic_router=ConversationRouter(),
            model_name=settings.langchain_model_name,
            model_provider=getattr(settings, "langchain_model_provider", None),
        )
        self._scope_recommendation_agent = ScopeRecommendationAgent(
            model_name=settings.langchain_model_name,
            model_provider=getattr(settings, "langchain_model_provider", None),
        )
        self._runtime_bridge: WorkflowRuntimeBridgeProtocol = (
            runtime_bridge or WorkflowRuntimeBridge(settings)
        )
        self._state_store = state_store or InMemoryWorkflowStateStore()

        self._text_localizer = WorkflowTextLocalizer(
            model_name=settings.langchain_model_name,
            model_provider=getattr(settings, "langchain_model_provider", None),
        )
        resolved_default_policy = self._coerce_default_language_policy(
            getattr(settings, "default_language_policy", "adaptive")
        )
        resolved_default_language = self._coerce_default_language(
            getattr(settings, "default_language", "vi")
        )

        self._language_policy_service = WorkflowLanguagePolicyService(
            default_policy=resolved_default_policy,
            default_language=resolved_default_language,
        )
        self._language_preference_resolver = WorkflowLanguagePreferenceResolver(
            policy_service=self._language_policy_service,
        )

        self._logger.info(
            "Initialized FullWorkflowOrchestrator.",
            extra={"payload_source": "full_workflow_orchestrator_init"},
        )

    def _coerce_default_language_policy(
        self,
        value: str | WorkflowLanguagePolicy | None,
    ) -> WorkflowLanguagePolicy:
        if value == WorkflowLanguagePolicy.SESSION_LOCK or value == "session_lock":
            return WorkflowLanguagePolicy.SESSION_LOCK
        return WorkflowLanguagePolicy.ADAPTIVE

    def _coerce_default_language(
        self,
        value: str | None,
    ) -> SupportedLanguage:
        lowered = str(value or "vi").strip().lower()
        return "en" if lowered == "en" else "vi"

    def _coerce_scope_selection_mode(
        self,
        value: ScopeSelectionMode | str | None,
    ) -> ScopeSelectionMode | None:
        if value is None:
            return None
        if isinstance(value, ScopeSelectionMode):
            return value
        lowered = str(value).strip().lower()
        for item in ScopeSelectionMode:
            if item.value == lowered:
                return item
        return None

    def _coerce_scope_catalog_groups(
        self,
        items: list[Any] | None,
    ) -> list[WorkflowScopeCatalogGroup]:
        groups: list[WorkflowScopeCatalogGroup] = []
        for item in list(items or []):
            if isinstance(item, WorkflowScopeCatalogGroup):
                groups.append(item)
                continue

            if isinstance(item, dict):
                groups.append(
                    WorkflowScopeCatalogGroup(
                        group_id=str(item.get("group_id", "")).strip(),
                        title=str(item.get("title", "")).strip(),
                        description=(
                            str(item.get("description")).strip()
                            if item.get("description") is not None
                            else None
                        ),
                        operation_ids=[
                            str(op_id).strip()
                            for op_id in list(item.get("operation_ids", []) or [])
                            if str(op_id).strip()
                        ],
                        tags=[
                            str(tag).strip()
                            for tag in list(item.get("tags", []) or [])
                            if str(tag).strip()
                        ],
                    )
                )
                continue

            groups.append(
                WorkflowScopeCatalogGroup(
                    group_id=str(getattr(item, "group_id", "")).strip(),
                    title=str(getattr(item, "title", "")).strip(),
                    description=(
                        str(getattr(item, "description")).strip()
                        if getattr(item, "description", None) is not None
                        else None
                    ),
                    operation_ids=[
                        str(op_id).strip()
                        for op_id in list(getattr(item, "operation_ids", []) or [])
                        if str(op_id).strip()
                    ],
                    tags=[
                        str(tag).strip()
                        for tag in list(getattr(item, "tags", []) or [])
                        if str(tag).strip()
                    ],
                )
            )
        return groups

    def _coerce_scope_catalog_operations(
        self,
        items: list[Any] | None,
    ) -> list[WorkflowScopeCatalogOperation]:
        operations: list[WorkflowScopeCatalogOperation] = []
        for item in list(items or []):
            if isinstance(item, WorkflowScopeCatalogOperation):
                operations.append(item)
                continue

            if isinstance(item, dict):
                operations.append(
                    WorkflowScopeCatalogOperation(
                        operation_id=str(item.get("operation_id", "")).strip(),
                        method=str(item.get("method", "")).strip().upper(),
                        path=str(item.get("path", "")).strip(),
                        group_id=(
                            str(item.get("group_id")).strip()
                            if item.get("group_id") is not None
                            else None
                        ),
                        group_title=(
                            str(item.get("group_title")).strip()
                            if item.get("group_title") is not None
                            else None
                        ),
                        summary=(
                            str(item.get("summary")).strip()
                            if item.get("summary") is not None
                            else None
                        ),
                        description=(
                            str(item.get("description")).strip()
                            if item.get("description") is not None
                            else None
                        ),
                        tags=[
                            str(tag).strip()
                            for tag in list(item.get("tags", []) or [])
                            if str(tag).strip()
                        ],
                        auth_required=item.get("auth_required"),
                    )
                )
                continue

            operations.append(
                WorkflowScopeCatalogOperation(
                    operation_id=str(getattr(item, "operation_id", "")).strip(),
                    method=str(getattr(item, "method", "")).strip().upper(),
                    path=str(getattr(item, "path", "")).strip(),
                    group_id=(
                        str(getattr(item, "group_id")).strip()
                        if getattr(item, "group_id", None) is not None
                        else None
                    ),
                    group_title=(
                        str(getattr(item, "group_title")).strip()
                        if getattr(item, "group_title", None) is not None
                        else None
                    ),
                    summary=(
                        str(getattr(item, "summary")).strip()
                        if getattr(item, "summary", None) is not None
                        else None
                    ),
                    description=(
                        str(getattr(item, "description")).strip()
                        if getattr(item, "description", None) is not None
                        else None
                    ),
                    tags=[
                        str(tag).strip()
                        for tag in list(getattr(item, "tags", []) or [])
                        if str(tag).strip()
                    ],
                    auth_required=getattr(item, "auth_required", None),
                )
            )
        return operations

    def _normalize_lookup_text(self, value: str) -> str:
        return " ".join(value.strip().lower().split())

    def _localize_for_snapshot(
        self,
        *,
        text: str | None,
        snapshot: WorkflowContextSnapshot | None,
        preferred_language: str,
        text_kind: str,
        target_name: str | None = None,
    ) -> str | None:
        language = "en" if preferred_language == "en" else "vi"
        return self._text_localizer.localize_text(
            text=text,
            target_language=language,
            text_kind=text_kind,
            thread_id=snapshot.thread_id if snapshot else None,
            target_name=target_name or (snapshot.selected_target if snapshot else None),
        )

    def _localize_review_result_fields(
        self,
        *,
        review_result: ReviewWorkflowResult,
        prior_snapshot: WorkflowContextSnapshot | None,
        preferred_language: str,
    ) -> tuple[str | None, str | None, str | None, str | None]:
        selection_question = self._localize_for_snapshot(
            text=review_result.selection_question,
            snapshot=prior_snapshot,
            preferred_language=preferred_language,
            text_kind="selection_question",
            target_name=review_result.selected_target,
        )
        understanding = self._localize_for_snapshot(
            text=review_result.understanding_explanation,
            snapshot=prior_snapshot,
            preferred_language=preferred_language,
            text_kind="understanding",
            target_name=review_result.selected_target,
        )
        preview_text = self._localize_for_snapshot(
            text=review_result.preview_text,
            snapshot=prior_snapshot,
            preferred_language=preferred_language,
            text_kind="review_preview",
            target_name=review_result.selected_target,
        )
        message = self._localize_for_snapshot(
            text=review_result.message,
            snapshot=prior_snapshot,
            preferred_language=preferred_language,
            text_kind="review_message",
            target_name=review_result.selected_target,
        )
        return selection_question, understanding, preview_text, message

    def start_from_text(
        self,
        text: str,
        *,
        thread_id: str | None = None,
        language_policy: WorkflowLanguagePolicy | str | None = None,
        selected_language: SupportedLanguage | None = None,
    ) -> FullWorkflowResult:
        actual_thread_id = thread_id or f"wf-{uuid.uuid4().hex}"
        language_resolution = self._language_preference_resolver.resolve_for_workflow_start(
            user_text=text,
            selected_language=selected_language,
            requested_language_policy=language_policy,
            thread_id=actual_thread_id,
        )

        logger = bind_logger(
            self._logger,
            thread_id=actual_thread_id,
            payload_source="full_workflow_start_from_text",
        )
        logger.info("Starting full workflow from raw text.")

        try:
            review_result = self._review_orchestrator.start_review_from_text(
                text,
                thread_id=actual_thread_id,
            )
            return self._handle_review_result(
                review_result=review_result,
                original_request=text,
                prior_snapshot=None,
                requested_language_policy=language_resolution.language_policy,
                requested_preferred_language=language_resolution.preferred_language,
            )
        except Exception as exc:
            logger.exception(f"Failed to start workflow from text: {exc}")
            language = language_resolution.preferred_language
            return FullWorkflowResult(
                workflow_id="",
                thread_id=actual_thread_id,
                phase=WorkflowPhase.ERROR,
                assistant_message=self._localize(
                    language,
                    f"Khởi tạo workflow thất bại: {exc}",
                    f"Failed to start workflow: {exc}",
                ),
                status_message=self._localize(
                    language,
                    "Workflow khởi tạo thất bại.",
                    "Workflow start failed.",
                ),
                preferred_language=language,
                language_policy=language_resolution.language_policy,
                needs_user_input=True,
                available_actions=["start_new_workflow", "help"],
            )

    def continue_with_message(
        self,
        *,
        thread_id: str,
        message: str,
    ) -> FullWorkflowResult:
        snapshot = self._state_store.get(thread_id)

        if snapshot is not None:
            language_decision = self._language_policy_service.resolve_next_language(
                current_language=snapshot.preferred_language,
                incoming_text=message,
                policy=snapshot.language_policy,
                thread_id=thread_id,
            )
            snapshot.preferred_language = language_decision.language

        route = self._router.route(message=message, snapshot=snapshot)

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=str(snapshot.selected_target if snapshot else "-"),
            payload_source="full_workflow_continue_with_message",
        )
        logger.info(
            f"Continuing workflow with routed intent={route.intent.value}, "
            f"phase={snapshot.phase.value if snapshot else 'none'}."
        )

        if route.intent == RouterIntent.HELP:
            return self._build_help_result(snapshot)

        if route.intent == RouterIntent.STATUS:
            return self._build_status_result(snapshot)

        if route.intent == RouterIntent.SHOW_REVIEW_SCOPE:
            return self._build_review_scope_result(snapshot)

        if route.intent == RouterIntent.SHOW_SCOPE_CATALOG:
            return self._build_scope_confirmation_result(snapshot)

        if route.intent == RouterIntent.SHOW_SCOPE_GROUP_DETAILS:
            return self._build_scope_group_details_result(
                snapshot=snapshot,
                selector=str(route.metadata.get("group_selector") or message).strip(),
            )

        if route.intent == RouterIntent.SHOW_SCOPE_OPERATION_DETAILS:
            return self._build_scope_operation_details_result(
                snapshot=snapshot,
                selector=str(route.metadata.get("operation_selector") or message).strip(),
            )

        if route.intent == RouterIntent.ASK_SCOPE_RECOMMENDATION:
            return self._build_scope_recommendation_result(
                snapshot,
                user_message=message,
            )

        if route.intent == RouterIntent.APPLY_SCOPE_RECOMMENDATION:
            return self._apply_latest_scope_recommendation_result(
                snapshot=snapshot,
                user_message=message,
            )

        if route.intent == RouterIntent.CLARIFY:
            return self._build_clarification_result(
                snapshot,
                route.clarification_question or route.reason,
            )

        if route.intent == RouterIntent.START_NEW_WORKFLOW:
            return self.start_from_text(message)

        if snapshot is None:
            return self.start_from_text(message, thread_id=thread_id)

        try:
            if route.intent == RouterIntent.RESUME_TARGET_SELECTION:
                self._clear_pending_clarification(snapshot)
                attempted_selection = message.strip()

                try:
                    review_result = self._review_orchestrator.resume_target_selection(
                        thread_id,
                        selection=attempted_selection,
                    )
                except TargetRegistryError:
                    logger.warning(
                        "Target selection failed because target does not exist in registry.",
                        extra={"target_name": attempted_selection},
                    )
                    return self._build_invalid_target_selection_result(
                        snapshot=snapshot,
                        attempted_selection=attempted_selection,
                    )

                if (
                    review_result.status == "target_not_found"
                    and snapshot.phase == WorkflowPhase.PENDING_TARGET_SELECTION
                ):
                    logger.warning(
                        "Review orchestrator returned target_not_found while pending target selection; keeping workflow in pending_target_selection.",
                        extra={"target_name": attempted_selection},
                    )
                    return self._build_invalid_target_selection_result(
                        snapshot=snapshot,
                        attempted_selection=attempted_selection,
                        detail_message=review_result.message,
                    )

                return self._handle_review_result(
                    review_result=review_result,
                    original_request=snapshot.original_user_text or "",
                    prior_snapshot=snapshot,
                )

            if route.intent == RouterIntent.RESUME_SCOPE_CONFIRMATION:
                self._clear_pending_clarification(snapshot)

                review_result = self._review_orchestrator.resume_scope_confirmation(
                    thread_id,
                    user_message=message,
                )
                return self._handle_review_result(
                    review_result=review_result,
                    original_request=snapshot.original_user_text or "",
                    prior_snapshot=snapshot,
                )

            if route.intent == RouterIntent.RESUME_REVIEW:
                self._clear_pending_clarification(snapshot)
                action, feedback = self._runtime_bridge.normalize_review_input(
                    raw_action=message,
                    thread_id=thread_id,
                    target_name=snapshot.selected_target,
                    preview_text=snapshot.current_markdown or "",
                    feedback_history=list(snapshot.review_feedback_history),
                )

                if action == "revise" and feedback:
                    snapshot.review_feedback_history.append(feedback)

                review_result = self._review_orchestrator.resume_review(
                    thread_id,
                    action=action,
                    feedback=feedback,
                )
                return self._handle_review_result(
                    review_result=review_result,
                    original_request=snapshot.original_user_text or "",
                    prior_snapshot=snapshot,
                )

            if route.intent == RouterIntent.CONTINUE_REPORT_INTERACTION:
                self._clear_pending_clarification(snapshot)
                return self._continue_report_interaction(
                    snapshot=snapshot,
                    user_message=message,
                )

        except Exception as exc:
            logger.exception(f"Workflow continuation failed: {exc}")
            return self._mark_error_snapshot(
                snapshot=snapshot,
                error_message=self._localize(
                    snapshot.preferred_language if snapshot else "vi",
                    f"Xử lý workflow thất bại: {exc}",
                    f"Workflow processing failed: {exc}",
                ),
            )

        return self._build_clarification_result(
            snapshot,
            self._localize(
                snapshot.preferred_language if snapshot else "vi",
                "Tôi chưa xác định được bước tiếp theo phù hợp. Bạn hãy nói rõ hơn.",
                "I could not determine the next suitable step. Please clarify your request.",
            ),
        )

    def get_snapshot(self, thread_id: str) -> WorkflowContextSnapshot | None:
        return self._state_store.get(thread_id)

    def _handle_review_result(
        self,
        *,
        review_result: ReviewWorkflowResult,
        original_request: str,
        prior_snapshot: WorkflowContextSnapshot | None,
        requested_language_policy: WorkflowLanguagePolicy | str | None = None,
        requested_preferred_language: SupportedLanguage | None = None,
    ) -> FullWorkflowResult:
        workflow_id = (
            prior_snapshot.workflow_id
            if prior_snapshot is not None
            else uuid.uuid4().hex
        )

        selection_question = review_result.selection_question or (
            prior_snapshot.selection_question if prior_snapshot else None
        )
        selected_target = review_result.selected_target or (
            prior_snapshot.selected_target if prior_snapshot else None
        )
        phase = self._map_review_status_to_phase(review_result.status)

        if prior_snapshot is not None:
            preferred_language = prior_snapshot.preferred_language
            language_policy = prior_snapshot.language_policy
        else:
            if requested_preferred_language is not None:
                preferred_language = requested_preferred_language
                language_policy = self._language_policy_service.coerce_policy(
                    requested_language_policy
                )
            else:
                initial_language_decision = self._language_policy_service.resolve_initial_language(
                    user_text=original_request,
                    policy=requested_language_policy,
                    thread_id=review_result.thread_id,
                )
                preferred_language = initial_language_decision.language
                language_policy = initial_language_decision.policy

        (
            localized_selection_question,
            localized_understanding,
            localized_preview_text,
            _localized_message,
        ) = self._localize_review_result_fields(
            review_result=review_result,
            prior_snapshot=prior_snapshot,
            preferred_language=preferred_language,
        )

        if selected_target and phase != WorkflowPhase.PENDING_TARGET_SELECTION:
            selection_question = None

        if phase != WorkflowPhase.PENDING_TARGET_SELECTION:
            localized_selection_question = None

        raw_scope_confirmation_question = getattr(
            review_result,
            "scope_confirmation_question",
            None,
        )
        raw_scope_confirmation_summary = getattr(
            review_result,
            "scope_confirmation_summary",
            None,
        )
        raw_scope_selection_mode = getattr(
            review_result,
            "scope_selection_mode",
            None,
        )
        raw_scope_catalog_groups = getattr(
            review_result,
            "scope_catalog_groups",
            None,
        )
        raw_scope_catalog_operations = getattr(
            review_result,
            "scope_catalog_operations",
            None,
        )
        raw_selected_scope_group_ids = getattr(
            review_result,
            "selected_scope_group_ids",
            None,
        )
        raw_selected_scope_operation_ids = getattr(
            review_result,
            "selected_scope_operation_ids",
            None,
        )
        raw_excluded_scope_group_ids = getattr(
            review_result,
            "excluded_scope_group_ids",
            None,
        )
        raw_excluded_scope_operation_ids = getattr(
            review_result,
            "excluded_scope_operation_ids",
            None,
        )

        localized_scope_confirmation_question = self._localize_for_snapshot(
            text=raw_scope_confirmation_question,
            snapshot=prior_snapshot,
            preferred_language=preferred_language,
            text_kind="scope_confirmation_question",
            target_name=selected_target,
        )
        localized_scope_confirmation_summary = self._localize_for_snapshot(
            text=raw_scope_confirmation_summary,
            snapshot=prior_snapshot,
            preferred_language=preferred_language,
            text_kind="scope_confirmation_summary",
            target_name=selected_target,
        )

        scope_catalog_groups = self._coerce_scope_catalog_groups(
            raw_scope_catalog_groups
            if raw_scope_catalog_groups is not None
            else (
                list(prior_snapshot.scope_catalog_groups)
                if prior_snapshot is not None
                else []
            )
        )
        scope_catalog_operations = self._coerce_scope_catalog_operations(
            raw_scope_catalog_operations
            if raw_scope_catalog_operations is not None
            else (
                list(prior_snapshot.scope_catalog_operations)
                if prior_snapshot is not None
                else []
            )
        )
        scope_selection_mode = self._coerce_scope_selection_mode(
            raw_scope_selection_mode
            if raw_scope_selection_mode is not None
            else (
                prior_snapshot.scope_selection_mode
                if prior_snapshot is not None
                else None
            )
        )

        selected_scope_group_ids = list(
            raw_selected_scope_group_ids
            if raw_selected_scope_group_ids is not None
            else (
                list(prior_snapshot.selected_scope_group_ids)
                if prior_snapshot is not None
                else []
            )
        )
        selected_scope_operation_ids = list(
            raw_selected_scope_operation_ids
            if raw_selected_scope_operation_ids is not None
            else (
                list(prior_snapshot.selected_scope_operation_ids)
                if prior_snapshot is not None
                else []
            )
        )
        excluded_scope_group_ids = list(
            raw_excluded_scope_group_ids
            if raw_excluded_scope_group_ids is not None
            else (
                list(prior_snapshot.excluded_scope_group_ids)
                if prior_snapshot is not None
                else []
            )
        )
        excluded_scope_operation_ids = list(
            raw_excluded_scope_operation_ids
            if raw_excluded_scope_operation_ids is not None
            else (
                list(prior_snapshot.excluded_scope_operation_ids)
                if prior_snapshot is not None
                else []
            )
        )

        snapshot = WorkflowContextSnapshot(
            workflow_id=workflow_id,
            thread_id=review_result.thread_id,
            phase=phase,
            original_user_text=original_request,
            selected_target=selected_target,
            candidate_targets=list(
                review_result.candidate_targets
                or (prior_snapshot.candidate_targets if prior_snapshot else [])
            ),
            selection_question=localized_selection_question or selection_question,
            canonical_command=review_result.canonical_command
            or (prior_snapshot.canonical_command if prior_snapshot else None),
            understanding_explanation=localized_understanding
            or (
                prior_snapshot.understanding_explanation if prior_snapshot else None
            ),
            preferred_language=preferred_language,
            language_policy=language_policy,
            scope_confirmation_question=localized_scope_confirmation_question
            or (
                prior_snapshot.scope_confirmation_question
                if prior_snapshot is not None
                else None
            ),
            scope_confirmation_summary=localized_scope_confirmation_summary
            or (
                prior_snapshot.scope_confirmation_summary
                if prior_snapshot is not None
                else None
            ),
            scope_selection_mode=scope_selection_mode,
            scope_catalog_groups=scope_catalog_groups,
            scope_catalog_operations=scope_catalog_operations,
            selected_scope_group_ids=selected_scope_group_ids,
            selected_scope_operation_ids=selected_scope_operation_ids,
            excluded_scope_group_ids=excluded_scope_group_ids,
            excluded_scope_operation_ids=excluded_scope_operation_ids,
            scope_confirmation_history=list(
                prior_snapshot.scope_confirmation_history
                if prior_snapshot is not None
                else []
            ),
            review_feedback_history=list(
                prior_snapshot.review_feedback_history if prior_snapshot else []
            ),
            artifacts=WorkflowArtifactRefs(
                draft_report_json_path=review_result.draft_report_json_path
                or (
                    prior_snapshot.artifacts.draft_report_json_path
                    if prior_snapshot
                    else None
                ),
                draft_report_md_path=review_result.draft_report_md_path
                or (
                    prior_snapshot.artifacts.draft_report_md_path
                    if prior_snapshot
                    else None
                ),
                execution_report_json_path=(
                    prior_snapshot.artifacts.execution_report_json_path
                    if prior_snapshot
                    else None
                ),
                execution_report_md_path=(
                    prior_snapshot.artifacts.execution_report_md_path
                    if prior_snapshot
                    else None
                ),
                validation_report_json_path=(
                    prior_snapshot.artifacts.validation_report_json_path
                    if prior_snapshot
                    else None
                ),
                validation_report_md_path=(
                    prior_snapshot.artifacts.validation_report_md_path
                    if prior_snapshot
                    else None
                ),
                staged_final_report_json_path=(
                    prior_snapshot.artifacts.staged_final_report_json_path
                    if prior_snapshot
                    else None
                ),
                staged_final_report_md_path=(
                    prior_snapshot.artifacts.staged_final_report_md_path
                    if prior_snapshot
                    else None
                ),
                final_report_json_path=(
                    prior_snapshot.artifacts.final_report_json_path
                    if prior_snapshot
                    else None
                ),
                final_report_md_path=(
                    prior_snapshot.artifacts.final_report_md_path
                    if prior_snapshot
                    else None
                ),
                artifact_paths=list(
                    prior_snapshot.artifacts.artifact_paths if prior_snapshot else []
                ),
            ),
            current_markdown=localized_preview_text
            or (prior_snapshot.current_markdown if prior_snapshot else None),
            messages=list(prior_snapshot.messages if prior_snapshot else []),
            assistant_message_count=(
                prior_snapshot.assistant_message_count if prior_snapshot else 0
            ),
            finalized=False,
            cancelled=review_result.status == "cancelled",
            rerun_requested=(
                prior_snapshot.rerun_requested if prior_snapshot is not None else False
            ),
            rerun_user_text=(
                prior_snapshot.rerun_user_text if prior_snapshot is not None else None
            ),
            pending_router_clarification=(
                prior_snapshot.pending_router_clarification
                if prior_snapshot is not None
                else None
            ),
            last_router_reason=(
                prior_snapshot.last_router_reason if prior_snapshot is not None else None
            ),
        )

        snapshot.last_router_reason = f"review_result_status={review_result.status}"
        self._clear_pending_clarification(snapshot)

        logger = bind_logger(
            self._logger,
            thread_id=snapshot.thread_id,
            target_name=str(snapshot.selected_target or "-"),
            payload_source="full_workflow_handle_review_result",
        )
        logger.info(f"Handling review result status={review_result.status!r}.")

        if snapshot.phase == WorkflowPhase.APPROVED:
            self._state_store.save(snapshot)
            return self._run_post_approval_pipeline(snapshot)

        self._state_store.save(snapshot)

        assistant_message = self._review_assistant_message(snapshot, review_result)
        return self._snapshot_to_result(snapshot, assistant_message=assistant_message)

    def _run_post_approval_pipeline(
        self,
        snapshot: WorkflowContextSnapshot,
    ) -> FullWorkflowResult:
        logger = bind_logger(
            self._logger,
            thread_id=snapshot.thread_id,
            target_name=str(snapshot.selected_target or "-"),
            payload_source="full_workflow_run_post_approval_pipeline",
        )
        logger.info("Running post-approval pipeline.")

        try:
            approved_payload = self._review_orchestrator.get_approved_execution_payload(
                snapshot.thread_id
            )
            approved_payload["preferred_language"] = snapshot.preferred_language

            runtime_result = self._runtime_bridge.run_post_approval(
                approved_payload=approved_payload,
                original_request=snapshot.original_user_text or "",
                candidate_targets_history=list(snapshot.candidate_targets),
                target_selection_question=snapshot.selection_question,
                review_feedback_history=list(snapshot.review_feedback_history),
            )

            snapshot.phase = WorkflowPhase.REPORT_INTERACTION
            snapshot.approved_payload = approved_payload
            snapshot.execution_batch_result = runtime_result.execution_batch_result
            snapshot.validation_batch_result = runtime_result.validation_batch_result
            snapshot.final_report_payload = runtime_result.final_report_payload

            localized_current_markdown = self._localize_for_snapshot(
                text=runtime_result.current_markdown,
                snapshot=snapshot,
                preferred_language=snapshot.preferred_language,
                text_kind="final_report_markdown",
            )
            localized_assistant_messages = [
                self._localize_for_snapshot(
                    text=item,
                    snapshot=snapshot,
                    preferred_language=snapshot.preferred_language,
                    text_kind="report_message",
                )
                or item
                for item in runtime_result.assistant_messages
            ]

            snapshot.current_markdown = (
                localized_current_markdown or runtime_result.current_markdown
            )
            snapshot.messages = list(runtime_result.messages)
            snapshot.assistant_message_count = runtime_result.assistant_message_count

            snapshot.artifacts.execution_report_json_path = (
                runtime_result.execution_report_json_path
            )
            snapshot.artifacts.execution_report_md_path = (
                runtime_result.execution_report_md_path
            )
            snapshot.artifacts.validation_report_json_path = (
                runtime_result.validation_report_json_path
            )
            snapshot.artifacts.validation_report_md_path = (
                runtime_result.validation_report_md_path
            )
            snapshot.artifacts.staged_final_report_json_path = (
                runtime_result.staged_final_report_json_path
            )
            snapshot.artifacts.staged_final_report_md_path = (
                runtime_result.staged_final_report_md_path
            )
            snapshot.artifacts.merge_artifact_paths(runtime_result.artifact_paths)

            self._state_store.save(snapshot)

            assistant_message = (
                "\n\n".join(localized_assistant_messages).strip()
                or self._localize(
                    snapshot.preferred_language,
                    "Tôi đã tạo staged final report và mở phiên tương tác report.",
                    "I created the staged final report and opened the report interaction session.",
                )
            )
            return self._snapshot_to_result(
                snapshot,
                assistant_message=assistant_message,
            )

        except Exception as exc:
            logger.exception(f"Post-approval pipeline failed: {exc}")
            return self._mark_error_snapshot(
                snapshot=snapshot,
                error_message=self._localize(
                    snapshot.preferred_language,
                    f"Pipeline sau approve thất bại: {exc}",
                    f"Post-approval pipeline failed: {exc}",
                ),
            )

    def _continue_report_interaction(
        self,
        *,
        snapshot: WorkflowContextSnapshot,
        user_message: str,
    ) -> FullWorkflowResult:
        logger = bind_logger(
            self._logger,
            thread_id=snapshot.thread_id,
            target_name=str(snapshot.selected_target or "-"),
            payload_source="full_workflow_continue_report_interaction",
        )
        logger.info("Continuing report interaction from full workflow orchestrator.")

        try:
            update = self._runtime_bridge.continue_report_interaction(
                thread_id=snapshot.thread_id,
                user_message=user_message,
                previous_assistant_count=snapshot.assistant_message_count,
            )

            localized_current_markdown = self._localize_for_snapshot(
                text=update.current_markdown,
                snapshot=snapshot,
                preferred_language=snapshot.preferred_language,
                text_kind="final_report_markdown",
            )
            localized_assistant_messages = [
                self._localize_for_snapshot(
                    text=item,
                    snapshot=snapshot,
                    preferred_language=snapshot.preferred_language,
                    text_kind="report_message",
                )
                or item
                for item in update.assistant_messages
            ]
            localized_update_message = self._localize_for_snapshot(
                text=update.message,
                snapshot=snapshot,
                preferred_language=snapshot.preferred_language,
                text_kind="report_message",
            )

            snapshot.current_markdown = (
                localized_current_markdown or update.current_markdown
            )
            snapshot.messages = list(update.messages)
            snapshot.assistant_message_count = update.assistant_message_count
            snapshot.artifacts.merge_artifact_paths(update.artifact_paths)

            assistant_message = (
                "\n\n".join(localized_assistant_messages).strip()
                or localized_update_message
            )

            if update.finalized:
                snapshot.phase = WorkflowPhase.FINALIZED
                snapshot.finalized = True
                snapshot.cancelled = False
                snapshot.rerun_requested = False
                snapshot.artifacts.final_report_json_path = update.final_report_json_path
                snapshot.artifacts.final_report_md_path = update.final_report_md_path

                try:
                    self._runtime_bridge.persist_finalized_run(
                        final_report_payload=snapshot.final_report_payload or {},
                        finalized_final_report_json_path=update.final_report_json_path,
                        finalized_final_report_md_path=update.final_report_md_path or "",
                        execution_batch_result=snapshot.execution_batch_result,
                        validation_batch_result=snapshot.validation_batch_result,
                        messages=list(snapshot.messages),
                    )
                except Exception as exc:
                    logger.exception(f"Persist finalized run failed: {exc}")
                    return self._mark_error_snapshot(
                        snapshot=snapshot,
                        error_message=self._localize(
                            snapshot.preferred_language,
                            f"Lưu final report thất bại: {exc}",
                            f"Failed to persist final report: {exc}",
                        ),
                    )

                self._state_store.save(snapshot)
                return self._snapshot_to_result(
                    snapshot,
                    assistant_message=assistant_message
                    or self._localize(
                        snapshot.preferred_language,
                        "Tôi đã chốt workflow này.",
                        "I finalized this workflow.",
                    ),
                )

            if update.cancelled:
                snapshot.phase = WorkflowPhase.CANCELLED
                snapshot.cancelled = True
                snapshot.finalized = False
                snapshot.rerun_requested = False
                snapshot.rerun_user_text = None

                snapshot.artifacts.artifact_paths = []
                snapshot.artifacts.staged_final_report_json_path = None
                snapshot.artifacts.staged_final_report_md_path = None
                snapshot.artifacts.final_report_json_path = None
                snapshot.artifacts.final_report_md_path = None

                self._state_store.save(snapshot)
                return self._snapshot_to_result(
                    snapshot,
                    assistant_message=assistant_message
                    or self._localize(
                        snapshot.preferred_language,
                        "Workflow đã bị hủy.",
                        "The workflow was cancelled.",
                    ),
                )

            if update.rerun_requested:
                snapshot.phase = WorkflowPhase.RERUN_REQUESTED
                snapshot.rerun_requested = True
                snapshot.rerun_user_text = update.rerun_user_text
                self._state_store.save(snapshot)
                return self._snapshot_to_result(
                    snapshot,
                    assistant_message=assistant_message
                    or self._localize(
                        snapshot.preferred_language,
                        "Đã ghi nhận yêu cầu chạy lại workflow.",
                        "The rerun request has been recorded.",
                    ),
                )

            snapshot.phase = WorkflowPhase.REPORT_INTERACTION
            self._state_store.save(snapshot)
            return self._snapshot_to_result(
                snapshot,
                assistant_message=assistant_message,
            )

        except Exception as exc:
            logger.exception(f"Report interaction failed: {exc}")
            return self._mark_error_snapshot(
                snapshot=snapshot,
                error_message=self._localize(
                    snapshot.preferred_language,
                    f"Tương tác report thất bại: {exc}",
                    f"Report interaction failed: {exc}",
                ),
            )

    def _review_assistant_message(
        self,
        snapshot: WorkflowContextSnapshot,
        review_result: ReviewWorkflowResult,
    ) -> str | None:
        if snapshot.phase == WorkflowPhase.PENDING_TARGET_SELECTION:
            localized_selection = self._localize_for_snapshot(
                text=review_result.selection_question,
                snapshot=snapshot,
                preferred_language=snapshot.preferred_language,
                text_kind="selection_question",
            )
            localized_message = self._localize_for_snapshot(
                text=review_result.message,
                snapshot=snapshot,
                preferred_language=snapshot.preferred_language,
                text_kind="review_message",
            )
            return localized_selection or localized_message

        if snapshot.phase == WorkflowPhase.PENDING_SCOPE_CONFIRMATION:
            return self._build_scope_confirmation_message(
                snapshot=snapshot,
                preface_message=self._localize_for_snapshot(
                    text=review_result.message,
                    snapshot=snapshot,
                    preferred_language=snapshot.preferred_language,
                    text_kind="scope_confirmation_message",
                ),
            )

        if review_result.status == "invalid_function":
            return self._build_invalid_function_message(snapshot, review_result)

        if snapshot.phase == WorkflowPhase.PENDING_REVIEW:
            preview = snapshot.current_markdown or ""
            localized_message = self._localize_for_snapshot(
                text=review_result.message,
                snapshot=snapshot,
                preferred_language=snapshot.preferred_language,
                text_kind="review_message",
            )
            if preview and localized_message:
                return f"{preview}\n\n{localized_message}"
            if preview:
                return preview
            return localized_message

        if snapshot.phase == WorkflowPhase.CANCELLED:
            return review_result.message or self._localize(
                snapshot.preferred_language,
                "Workflow đã bị hủy.",
                "The workflow was cancelled.",
            )

        if snapshot.phase == WorkflowPhase.ERROR:
            return review_result.message or self._localize(
                snapshot.preferred_language,
                "Workflow gặp lỗi.",
                "The workflow encountered an error.",
            )

        return review_result.message

    def _build_invalid_function_message(
        self,
        snapshot: WorkflowContextSnapshot,
        review_result: ReviewWorkflowResult,
    ) -> str:
        lang = snapshot.preferred_language
        target = review_result.selected_target or "unknown_target"
        requested_function = self._extract_requested_function(
            review_result.message or ""
        ) or self._extract_requested_function(snapshot.original_user_text or "")
        available = list(review_result.available_functions or [])

        if lang == "en":
            if requested_function:
                base_message = (
                    f"Function `{requested_function}` was not found in target `{target}`."
                )
            else:
                base_message = (
                    f"The requested function was not found in target `{target}`."
                )
            if not available:
                return base_message
            lines = [base_message, "", f"Available functions in target `{target}`:"]
        else:
            base_message = (
                review_result.message
                or f"Không tìm thấy chức năng yêu cầu trong target `{target}`."
            )
            if not available:
                return base_message
            lines = [base_message, "", f"Các chức năng hiện có của target `{target}` là:"]

        for index, item in enumerate(available, start=1):
            lines.append(f"{index}. {item}")
        return "\n".join(lines)

    def _build_invalid_target_selection_result(
        self,
        *,
        snapshot: WorkflowContextSnapshot,
        attempted_selection: str,
        detail_message: str | None = None,
    ) -> FullWorkflowResult:
        candidate_targets = list(snapshot.candidate_targets or [])
        lang = snapshot.preferred_language

        if lang == "en":
            selection_question = (
                snapshot.selection_question
                or (
                    f"Please choose one of the valid targets: "
                    f"{', '.join(f'`{item}`' for item in candidate_targets)}."
                    if candidate_targets
                    else "Please choose a valid target."
                )
            )
            assistant_message = detail_message or (
                f"Target `{attempted_selection}` does not exist. "
                + (
                    f"Please choose one of: {', '.join(f'`{item}`' for item in candidate_targets)}."
                    if candidate_targets
                    else "Please choose a valid target."
                )
            )
        else:
            selection_question = (
                snapshot.selection_question
                or (
                    f"Bạn hãy chọn một trong các target hợp lệ sau: "
                    f"{', '.join(f'`{item}`' for item in candidate_targets)}."
                    if candidate_targets
                    else "Bạn hãy chọn target hợp lệ."
                )
            )
            assistant_message = detail_message or (
                f"Target `{attempted_selection}` không tồn tại. "
                + (
                    f"Bạn hãy chọn một trong các target sau: {', '.join(f'`{item}`' for item in candidate_targets)}."
                    if candidate_targets
                    else "Bạn hãy chọn target hợp lệ."
                )
            )

        snapshot.phase = WorkflowPhase.PENDING_TARGET_SELECTION
        snapshot.selected_target = None
        snapshot.selection_question = selection_question
        snapshot.last_router_reason = "invalid_target_selection"
        self._clear_pending_clarification(snapshot)
        self._state_store.save(snapshot)

        return self._snapshot_to_result(
            snapshot,
            assistant_message=assistant_message,
        )

    def _build_scope_confirmation_message(
        self,
        *,
        snapshot: WorkflowContextSnapshot,
        preface_message: str | None = None,
    ) -> str:
        lang = snapshot.preferred_language
        lines: list[str] = []

        if preface_message:
            lines.append(preface_message)
            lines.append("")

        if lang == "en":
            lines.append(
                f"Target `{snapshot.selected_target or '-'}` has multiple available capabilities."
            )
            if snapshot.scope_confirmation_summary:
                lines.append(snapshot.scope_confirmation_summary)
            if snapshot.scope_catalog_groups:
                lines.append("")
                lines.append("Function groups:")
                lines.extend(self._render_scope_group_catalog(snapshot))
            elif snapshot.scope_catalog_operations:
                lines.append("")
                lines.append("Available operations:")
                lines.extend(self._render_scope_operation_catalog(snapshot))
            if snapshot.scope_confirmation_question:
                lines.append("")
                lines.append(snapshot.scope_confirmation_question)
            else:
                lines.append("")
                lines.append(
                    "Tell me whether you want to test all functions, a few groups, or some specific operations."
                )
        else:
            lines.append(
                f"Target `{snapshot.selected_target or '-'}` có nhiều chức năng khả dụng."
            )
            if snapshot.scope_confirmation_summary:
                lines.append(snapshot.scope_confirmation_summary)
            if snapshot.scope_catalog_groups:
                lines.append("")
                lines.append("Các nhóm chức năng:")
                lines.extend(self._render_scope_group_catalog(snapshot))
            elif snapshot.scope_catalog_operations:
                lines.append("")
                lines.append("Các operation hiện có:")
                lines.extend(self._render_scope_operation_catalog(snapshot))
            if snapshot.scope_confirmation_question:
                lines.append("")
                lines.append(snapshot.scope_confirmation_question)
            else:
                lines.append("")
                lines.append(
                    "Bạn hãy cho tôi biết muốn test toàn bộ, theo nhóm, hay chỉ một vài operation cụ thể."
                )

        return "\n".join(lines).strip()

    def _render_scope_group_catalog(
        self,
        snapshot: WorkflowContextSnapshot,
    ) -> list[str]:
        operation_lookup = {
            op.operation_id: op for op in snapshot.scope_catalog_operations
        }
        rendered: list[str] = []

        for index, group in enumerate(snapshot.scope_catalog_groups, start=1):
            selected_marker = ""
            if group.group_id in snapshot.selected_scope_group_ids:
                selected_marker = " [selected]"
            if group.group_id in snapshot.excluded_scope_group_ids:
                selected_marker = " [excluded]"

            rendered.append(f"{index}. {group.title}{selected_marker}")
            if group.description:
                rendered.append(f"   - {group.description}")

            if group.operation_ids:
                previews: list[str] = []
                for op_id in group.operation_ids[:3]:
                    operation = operation_lookup.get(op_id)
                    if operation is not None:
                        previews.append(f"{operation.method} {operation.path}")
                    else:
                        previews.append(op_id)
                rendered.append(
                    f"   - Operations: {len(group.operation_ids)}"
                    + (f" | e.g. {', '.join(previews)}" if previews else "")
                )

        return rendered

    def _render_scope_operation_catalog(
        self,
        snapshot: WorkflowContextSnapshot,
    ) -> list[str]:
        rendered: list[str] = []

        for index, operation in enumerate(snapshot.scope_catalog_operations, start=1):
            selected_marker = ""
            if operation.operation_id in snapshot.selected_scope_operation_ids:
                selected_marker = " [selected]"
            if operation.operation_id in snapshot.excluded_scope_operation_ids:
                selected_marker = " [excluded]"

            head = (
                f"{index}. {operation.method} {operation.path}"
                f" (operation_id={operation.operation_id}){selected_marker}"
            )
            rendered.append(head)

            description = operation.description or operation.summary
            if description:
                rendered.append(f"   - {description}")
            elif operation.group_title:
                rendered.append(f"   - Group: {operation.group_title}")

        return rendered

    def _find_scope_group(
        self,
        snapshot: WorkflowContextSnapshot,
        selector: str,
    ) -> WorkflowScopeCatalogGroup | None:
        cleaned = selector.strip()
        if not cleaned:
            return None

        if cleaned.isdigit():
            index = int(cleaned)
            if 1 <= index <= len(snapshot.scope_catalog_groups):
                return snapshot.scope_catalog_groups[index - 1]

        normalized = self._normalize_lookup_text(cleaned)
        for group in snapshot.scope_catalog_groups:
            if normalized == self._normalize_lookup_text(group.group_id):
                return group
            if normalized == self._normalize_lookup_text(group.title):
                return group
            if normalized in self._normalize_lookup_text(group.title):
                return group

        return None

    def _find_scope_operation(
        self,
        snapshot: WorkflowContextSnapshot,
        selector: str,
    ) -> WorkflowScopeCatalogOperation | None:
        cleaned = selector.strip()
        if not cleaned:
            return None

        if cleaned.isdigit():
            index = int(cleaned)
            if 1 <= index <= len(snapshot.scope_catalog_operations):
                return snapshot.scope_catalog_operations[index - 1]

        normalized = self._normalize_lookup_text(cleaned)
        for operation in snapshot.scope_catalog_operations:
            method_path = self._normalize_lookup_text(
                f"{operation.method} {operation.path}"
            )
            if normalized == self._normalize_lookup_text(operation.operation_id):
                return operation
            if normalized == self._normalize_lookup_text(operation.path):
                return operation
            if normalized == method_path:
                return operation
            if normalized in method_path:
                return operation

        return None

    def _build_scope_confirmation_result(
        self,
        snapshot: WorkflowContextSnapshot | None,
        *,
        preface_message: str | None = None,
    ) -> FullWorkflowResult:
        if snapshot is None:
            return FullWorkflowResult(
                workflow_id="",
                thread_id="",
                phase=WorkflowPhase.IDLE,
                assistant_message=self._localize(
                    "vi",
                    "Hiện không có workflow active để xác nhận scope.",
                    "There is no active workflow for scope confirmation.",
                ),
                status_message=self._localize(
                    "vi",
                    "Hiện không có workflow active.",
                    "There is no active workflow.",
                ),
                preferred_language="vi",
                language_policy=WorkflowLanguagePolicy.ADAPTIVE,
                needs_user_input=True,
                available_actions=["start_new_workflow"],
            )

        return self._snapshot_to_result(
            snapshot,
            assistant_message=self._build_scope_confirmation_message(
                snapshot=snapshot,
                preface_message=preface_message,
            ),
        )

    def _build_scope_group_details_result(
        self,
        *,
        snapshot: WorkflowContextSnapshot | None,
        selector: str,
    ) -> FullWorkflowResult:
        if snapshot is None:
            return self._build_scope_confirmation_result(snapshot)

        group = self._find_scope_group(snapshot, selector)
        if group is None:
            return self._build_clarification_result(
                snapshot,
                self._localize(
                    snapshot.preferred_language,
                    "Tôi chưa xác định được nhóm chức năng bạn muốn xem chi tiết.",
                    "I could not determine which function group you want to inspect.",
                ),
            )

        operations = [
            item
            for item in snapshot.scope_catalog_operations
            if item.operation_id in set(group.operation_ids)
        ]

        lines: list[str] = []
        if snapshot.preferred_language == "en":
            lines.append(f"Details for group `{group.title}`:")
            if group.description:
                lines.append(f"- Description: {group.description}")
            if group.tags:
                lines.append(f"- Tags: {', '.join(group.tags)}")
            lines.append("- Operations:")
            for index, operation in enumerate(operations, start=1):
                lines.append(
                    f"  {index}. {operation.method} {operation.path} "
                    f"(operation_id={operation.operation_id})"
                )
                if operation.description or operation.summary:
                    lines.append(
                        f"     - {operation.description or operation.summary}"
                    )
        else:
            lines.append(f"Chi tiết nhóm `{group.title}`:")
            if group.description:
                lines.append(f"- Mô tả: {group.description}")
            if group.tags:
                lines.append(f"- Tags: {', '.join(group.tags)}")
            lines.append("- Các operation:")
            for index, operation in enumerate(operations, start=1):
                lines.append(
                    f"  {index}. {operation.method} {operation.path} "
                    f"(operation_id={operation.operation_id})"
                )
                if operation.description or operation.summary:
                    lines.append(
                        f"     - {operation.description or operation.summary}"
                    )

        return self._snapshot_to_result(
            snapshot,
            assistant_message="\n".join(lines),
        )

    def _build_scope_operation_details_result(
        self,
        *,
        snapshot: WorkflowContextSnapshot | None,
        selector: str,
    ) -> FullWorkflowResult:
        if snapshot is None:
            return self._build_scope_confirmation_result(snapshot)

        operation = self._find_scope_operation(snapshot, selector)
        if operation is None:
            return self._build_clarification_result(
                snapshot,
                self._localize(
                    snapshot.preferred_language,
                    "Tôi chưa xác định được operation bạn muốn xem chi tiết.",
                    "I could not determine which operation you want to inspect.",
                ),
            )

        lines: list[str] = []
        if snapshot.preferred_language == "en":
            lines.append(
                f"Operation details: {operation.method} {operation.path} "
                f"(operation_id={operation.operation_id})"
            )
            if operation.group_title:
                lines.append(f"- Group: {operation.group_title}")
            if operation.description:
                lines.append(f"- Description: {operation.description}")
            elif operation.summary:
                lines.append(f"- Summary: {operation.summary}")
            if operation.tags:
                lines.append(f"- Tags: {', '.join(operation.tags)}")
            if operation.auth_required is not None:
                lines.append(
                    f"- Auth required: {'yes' if operation.auth_required else 'no'}"
                )
        else:
            lines.append(
                f"Chi tiết operation: {operation.method} {operation.path} "
                f"(operation_id={operation.operation_id})"
            )
            if operation.group_title:
                lines.append(f"- Nhóm: {operation.group_title}")
            if operation.description:
                lines.append(f"- Mô tả: {operation.description}")
            elif operation.summary:
                lines.append(f"- Tóm tắt: {operation.summary}")
            if operation.tags:
                lines.append(f"- Tags: {', '.join(operation.tags)}")
            if operation.auth_required is not None:
                lines.append(
                    f"- Cần auth: {'có' if operation.auth_required else 'không'}"
                )

        return self._snapshot_to_result(
            snapshot,
            assistant_message="\n".join(lines),
        )

    def _expand_group_ids_to_operation_ids(
        self,
        *,
        snapshot: WorkflowContextSnapshot,
        group_ids: list[str],
    ) -> list[str]:
        wanted = {str(group_id).strip() for group_id in group_ids if str(group_id).strip()}
        operation_ids: list[str] = []
        seen: set[str] = set()

        for group in snapshot.scope_catalog_groups:
            if group.group_id not in wanted:
                continue
            for operation_id in group.operation_ids:
                cleaned = str(operation_id).strip()
                if not cleaned or cleaned in seen:
                    continue
                seen.add(cleaned)
                operation_ids.append(cleaned)

        return operation_ids

    def _remember_review_scope_recommendation(
        self,
        *,
        thread_id: str,
        recommendation: WorkflowScopeRecommendation,
    ) -> None:
        method = getattr(self._review_orchestrator, "remember_scope_recommendation", None)
        if callable(method):
            method(thread_id, recommendation=recommendation)

    def _compose_scope_selection_message_from_recommendation(
        self,
        recommendation: WorkflowScopeRecommendation,
    ) -> str:
        group_refs = [item for item in recommendation.group_ids if str(item).strip()]
        if not group_refs:
            return "clarify scope"

        if recommendation.mode == ScopeRecommendationMode.DEPRIORITIZE:
            return f"exclude groups: {', '.join(group_refs)}"

        return f"only groups: {', '.join(group_refs)}"

    def _should_apply_top_scope_recommendation_only(
        self,
        *,
        user_message: str,
    ) -> bool:
        normalized = self._normalize_lookup_text(user_message)
        if not normalized:
            return False

        apply_all_markers = [
            "tất cả",
            "tat ca",
            "toàn bộ",
            "toan bo",
            "hết",
            "het",
            "all",
            "everything",
            "entire",
            "full",
            "toàn bộ các nhóm",
            "toan bo cac nhom",
            "test hết",
            "test het",
            "tất cả theo gợi ý",
            "tat ca theo goi y",
            "theo danh sách",
            "theo danh sach",
            "all recommended",
            "full recommendation",
        ]
        if self._contains_any_text(normalized, apply_all_markers):
            return False

        top_only_markers = [
            "ưu tiên thôi",
            "uu tien thoi",
            "cái nào ưu tiên",
            "cai nao uu tien",
            "cái ưu tiên",
            "cai uu tien",
            "ưu tiên nhất",
            "uu tien nhat",
            "quan trọng nhất",
            "quan trong nhat",
            "nhóm đầu tiên",
            "nhom dau tien",
            "cái đầu tiên",
            "cai dau tien",
            "lấy cái đầu",
            "lay cai dau",
            "lấy cái ưu tiên",
            "lay cai uu tien",
            "chọn cái ưu tiên",
            "chon cai uu tien",
            "chọn nhóm ưu tiên",
            "chon nhom uu tien",
            "test nhóm ưu tiên",
            "test nhom uu tien",
            "chỉ nhóm đầu",
            "chi nhom dau",
            "chỉ cái đầu",
            "chi cai dau",
            "chỉ ưu tiên",
            "chi uu tien",
            "top 1",
            "top one",
            "first one",
            "first group",
            "highest priority",
            "most important",
            "only the first",
            "just the first",
            "just top",
            "only top",
            "one priority",
        ]

        return self._contains_any_text(normalized, top_only_markers)

    def _contains_any_text(
        self,
        text: str,
        tokens: list[str],
    ) -> bool:
        return any(token in text for token in tokens)

    def _build_scope_recommendation_result(
        self,
        snapshot: WorkflowContextSnapshot | None,
        *,
        user_message: str,
    ) -> FullWorkflowResult:
        if snapshot is None:
            return self._build_scope_confirmation_result(snapshot)

        recommendation = self._scope_recommendation_agent.recommend(
            user_message=user_message,
            target_name=snapshot.selected_target or "",
            original_request=snapshot.original_user_text,
            preferred_language=snapshot.preferred_language,
            scope_catalog_groups=list(snapshot.scope_catalog_groups),
            scope_catalog_operations=list(snapshot.scope_catalog_operations),
            scope_confirmation_history=list(snapshot.scope_confirmation_history),
        )

        group_lookup = {item.group_id: item for item in snapshot.scope_catalog_groups}

        if recommendation.mode == "deprioritize":
            recommendation_mode = ScopeRecommendationMode.DEPRIORITIZE
            recommendation_group_ids = list(recommendation.deprioritized_group_ids)
        else:
            recommendation_mode = ScopeRecommendationMode.PRIORITIZE
            recommendation_group_ids = list(recommendation.recommended_group_ids)

        recommendation_operation_ids = self._expand_group_ids_to_operation_ids(
            snapshot=snapshot,
            group_ids=recommendation_group_ids,
        )

        lines: list[str] = []
        if snapshot.preferred_language == "en":
            if recommendation.mode == "deprioritize":
                lines.append("Groups that should not be tested first:")
                for group_id in recommendation.deprioritized_group_ids:
                    group = group_lookup.get(group_id)
                    if group is None:
                        continue
                    lines.append(f"- {group.title}")
                    if group.description:
                        lines.append(f"  {group.description}")
            else:
                lines.append("Suggested groups to test first:")
                for group_id in recommendation.recommended_group_ids:
                    group = group_lookup.get(group_id)
                    if group is None:
                        continue
                    lines.append(f"- {group.title}")
                    if group.description:
                        lines.append(f"  {group.description}")

            if recommendation.rationale:
                lines.append("")
                lines.append(f"Why: {recommendation.rationale}")

            if recommendation.follow_up_suggestion:
                lines.append("")
                lines.append(recommendation.follow_up_suggestion)
        else:
            if recommendation.mode == "deprioritize":
                lines.append("Các nhóm không nên test trước:")
                for group_id in recommendation.deprioritized_group_ids:
                    group = group_lookup.get(group_id)
                    if group is None:
                        continue
                    lines.append(f"- {group.title}")
                    if group.description:
                        lines.append(f"  {group.description}")
            else:
                lines.append("Gợi ý các nhóm nên test trước:")
                for group_id in recommendation.recommended_group_ids:
                    group = group_lookup.get(group_id)
                    if group is None:
                        continue
                    lines.append(f"- {group.title}")
                    if group.description:
                        lines.append(f"  {group.description}")

            if recommendation.rationale:
                lines.append("")
                lines.append(f"Lý do: {recommendation.rationale}")

            if recommendation.follow_up_suggestion:
                lines.append("")
                lines.append(recommendation.follow_up_suggestion)

        rendered_message = "\n".join(lines).strip()

        normalized_recommendation = WorkflowScopeRecommendation(
            mode=recommendation_mode,
            group_ids=recommendation_group_ids,
            operation_ids=recommendation_operation_ids,
            rationale=recommendation.rationale or None,
            follow_up_question=recommendation.follow_up_suggestion,
            source_user_message=user_message,
            rendered_message=rendered_message,
        )

        snapshot.latest_scope_recommendation = normalized_recommendation
        snapshot.last_scope_user_message = user_message
        snapshot.scope_confirmation_history.append(user_message)
        snapshot.latest_scope_agent_action = "ask_scope_recommendation"
        snapshot.latest_scope_agent_reason = recommendation.rationale or (
            "Scope recommendation generated."
        )
        self._state_store.save(snapshot)
        self._remember_review_scope_recommendation(
            thread_id=snapshot.thread_id,
            recommendation=normalized_recommendation,
        )

        return self._snapshot_to_result(
            snapshot,
            assistant_message=rendered_message,
        )

    def _apply_latest_scope_recommendation_result(
        self,
        *,
        snapshot: WorkflowContextSnapshot | None,
        user_message: str,
    ) -> FullWorkflowResult:
        if snapshot is None:
            return self._build_scope_confirmation_result(snapshot)

        recommendation = getattr(
            snapshot,
            "latest_scope_recommendation",
            WorkflowScopeRecommendation(),
        )
        if not recommendation.has_payload() or not recommendation.group_ids:
            return self._build_clarification_result(
                snapshot,
                self._localize(
                    snapshot.preferred_language,
                    "Tôi chưa có gợi ý scope gần đây để áp dụng. Bạn muốn tôi gợi ý lại nhóm nên test trước không?",
                    "I do not have a recent scope recommendation to apply. Would you like me to suggest which groups should be tested first again?",
                ),
            )

        apply_top_only = self._should_apply_top_scope_recommendation_only(
            user_message=user_message,
        )

        if recommendation.mode == ScopeRecommendationMode.DEPRIORITIZE:
            excluded_group_ids = list(recommendation.group_ids)
            excluded_operation_ids = self._expand_group_ids_to_operation_ids(
                snapshot=snapshot,
                group_ids=excluded_group_ids,
            )
            all_group_ids = [item.group_id for item in snapshot.scope_catalog_groups]
            all_operation_ids = [
                item.operation_id for item in snapshot.scope_catalog_operations
            ]
            selected_group_ids = [
                item for item in all_group_ids if item not in set(excluded_group_ids)
            ]
            selected_operation_ids = [
                item
                for item in all_operation_ids
                if item not in set(excluded_operation_ids)
            ]
            selection_mode = ScopeSelectionMode.CUSTOM
            applied_recommendation = recommendation

        else:
            recommended_group_ids = [
                str(item).strip()
                for item in list(recommendation.group_ids)
                if str(item).strip()
            ]

            if apply_top_only and recommended_group_ids:
                selected_group_ids = [recommended_group_ids[0]]
                application_reason = self._localize(
                    snapshot.preferred_language,
                    "Người dùng muốn áp dụng nhóm ưu tiên nhất trong gợi ý, không phải toàn bộ danh sách gợi ý.",
                    "The user wants to apply only the top-priority recommended group, not the whole recommendation list.",
                )
            else:
                selected_group_ids = list(recommended_group_ids)
                application_reason = recommendation.rationale or self._localize(
                    snapshot.preferred_language,
                    "Áp dụng toàn bộ danh sách nhóm được gợi ý.",
                    "Applied the full recommended group list.",
                )

            selected_operation_ids = self._expand_group_ids_to_operation_ids(
                snapshot=snapshot,
                group_ids=selected_group_ids,
            )
            excluded_group_ids = []
            excluded_operation_ids = []
            selection_mode = ScopeSelectionMode.GROUPS

            applied_recommendation = WorkflowScopeRecommendation(
                mode=recommendation.mode,
                group_ids=selected_group_ids,
                operation_ids=selected_operation_ids,
                rationale=application_reason,
                follow_up_question=recommendation.follow_up_question,
                source_user_message=user_message,
                rendered_message=recommendation.rendered_message,
            )

        if not selected_operation_ids:
            return self._build_clarification_result(
                snapshot,
                self._localize(
                    snapshot.preferred_language,
                    "Tôi chưa map được gợi ý gần nhất sang operation cụ thể để test. Bạn hãy chọn nhóm hoặc operation rõ hơn.",
                    "I could not map the latest recommendation to concrete operations to test. Please choose groups or operations more explicitly.",
                ),
            )

        snapshot.applied_scope_recommendation = applied_recommendation
        snapshot.selected_scope_group_ids = selected_group_ids
        snapshot.selected_scope_operation_ids = selected_operation_ids
        snapshot.excluded_scope_group_ids = excluded_group_ids
        snapshot.excluded_scope_operation_ids = excluded_operation_ids
        snapshot.scope_selection_mode = selection_mode
        snapshot.latest_scope_selection_source = (
            "applied_top_scope_recommendation"
            if apply_top_only and recommendation.mode != ScopeRecommendationMode.DEPRIORITIZE
            else "applied_scope_recommendation"
        )
        snapshot.latest_scope_agent_action = "apply_scope_recommendation"
        snapshot.latest_scope_agent_reason = applied_recommendation.rationale or (
            "Applied latest scope recommendation."
        )
        snapshot.last_scope_user_message = user_message
        snapshot.scope_confirmation_history.append(user_message)
        self._state_store.save(snapshot)

        synthetic_scope_message = self._compose_scope_selection_message_from_recommendation(
            applied_recommendation
        )

        try:
            review_result = self._review_orchestrator.resume_scope_confirmation(
                snapshot.thread_id,
                user_message=synthetic_scope_message,
            )
        except Exception as exc:
            self._logger.exception(
                f"Failed to apply latest scope recommendation: {exc}"
            )
            return self._mark_error_snapshot(
                snapshot=snapshot,
                error_message=self._localize(
                    snapshot.preferred_language,
                    f"Áp dụng gợi ý scope thất bại: {exc}",
                    f"Failed to apply the scope recommendation: {exc}",
                ),
            )

        return self._handle_review_result(
            review_result=review_result,
            original_request=snapshot.original_user_text or "",
            prior_snapshot=snapshot,
        )

    def _extract_requested_function(self, text: str) -> str | None:
        match = re.search(r"'([^']+)'", text)
        if match:
            return match.group(1).strip()
        return None

    def _snapshot_to_result(
        self,
        snapshot: WorkflowContextSnapshot,
        *,
        assistant_message: str | None = None,
    ) -> FullWorkflowResult:
        localized_assistant_message = self._localize_for_snapshot(
            text=assistant_message,
            snapshot=snapshot,
            preferred_language=snapshot.preferred_language,
            text_kind="assistant_message",
        )

        localized_selection_question = self._localize_for_snapshot(
            text=snapshot.selection_question,
            snapshot=snapshot,
            preferred_language=snapshot.preferred_language,
            text_kind="selection_question",
        )

        localized_understanding = self._localize_for_snapshot(
            text=snapshot.understanding_explanation,
            snapshot=snapshot,
            preferred_language=snapshot.preferred_language,
            text_kind="understanding",
        )

        localized_scope_confirmation_question = self._localize_for_snapshot(
            text=snapshot.scope_confirmation_question,
            snapshot=snapshot,
            preferred_language=snapshot.preferred_language,
            text_kind="scope_confirmation_question",
        )

        localized_scope_confirmation_summary = self._localize_for_snapshot(
            text=snapshot.scope_confirmation_summary,
            snapshot=snapshot,
            preferred_language=snapshot.preferred_language,
            text_kind="scope_confirmation_summary",
        )

        return FullWorkflowResult(
            workflow_id=snapshot.workflow_id,
            thread_id=snapshot.thread_id,
            phase=snapshot.phase,
            assistant_message=localized_assistant_message,
            status_message=self._status_summary(snapshot),
            selected_target=snapshot.selected_target,
            candidate_targets=list(snapshot.candidate_targets),
            selection_question=localized_selection_question,
            canonical_command=snapshot.canonical_command,
            understanding_explanation=localized_understanding,
            preferred_language=snapshot.preferred_language,
            language_policy=snapshot.language_policy,
            scope_confirmation_question=localized_scope_confirmation_question,
            scope_confirmation_summary=localized_scope_confirmation_summary,
            scope_selection_mode=snapshot.scope_selection_mode,
            scope_catalog_groups=list(snapshot.scope_catalog_groups),
            scope_catalog_operations=list(snapshot.scope_catalog_operations),
            selected_scope_group_ids=list(snapshot.selected_scope_group_ids),
            selected_scope_operation_ids=list(snapshot.selected_scope_operation_ids),
            excluded_scope_group_ids=list(snapshot.excluded_scope_group_ids),
            excluded_scope_operation_ids=list(snapshot.excluded_scope_operation_ids),
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
            rerun_user_text=snapshot.rerun_user_text,
            finalized=snapshot.finalized,
            cancelled=snapshot.cancelled,
            needs_user_input=self._needs_user_input(snapshot.phase),
            available_actions=self._available_actions(snapshot.phase),
        )

    def _build_help_result(
        self,
        snapshot: WorkflowContextSnapshot | None,
    ) -> FullWorkflowResult:
        lang = snapshot.preferred_language if snapshot is not None else "vi"
        if snapshot is None:
            return FullWorkflowResult(
                workflow_id="",
                thread_id="",
                phase=WorkflowPhase.IDLE,
                assistant_message=self._localize(
                    lang,
                    "Tôi có thể hỗ trợ review testcase draft, execution, validation, tương tác final report, finalize hoặc rerun. Bạn hãy gửi một yêu cầu test mới để bắt đầu.",
                    "I can help with draft testcase review, execution, validation, final report interaction, finalize, or rerun. Send a new test request to begin.",
                ),
                status_message=self._localize(
                    lang,
                    "Hiện không có workflow active.",
                    "There is no active workflow.",
                ),
                preferred_language=lang,
                language_policy=WorkflowLanguagePolicy.ADAPTIVE,
                needs_user_input=True,
                available_actions=["start_new_workflow"],
            )

        return self._snapshot_to_result(
            snapshot,
            assistant_message=self._localize(
                lang,
                f"Workflow hiện đang ở phase `{snapshot.phase.value}`.\nBạn có thể dùng các action: {', '.join(self._available_actions(snapshot.phase))}.",
                f"The workflow is currently in phase `{snapshot.phase.value}`.\nAvailable actions: {', '.join(self._available_actions(snapshot.phase))}.",
            ),
        )

    def _build_status_result(
        self,
        snapshot: WorkflowContextSnapshot | None,
    ) -> FullWorkflowResult:
        lang = snapshot.preferred_language if snapshot is not None else "vi"
        if snapshot is None:
            return FullWorkflowResult(
                workflow_id="",
                thread_id="",
                phase=WorkflowPhase.IDLE,
                assistant_message=self._localize(
                    lang,
                    "Hiện không có workflow active nào trong session này.",
                    "There is no active workflow in this session.",
                ),
                status_message=self._localize(
                    lang,
                    "Hiện không có workflow active.",
                    "There is no active workflow.",
                ),
                preferred_language=lang,
                language_policy=WorkflowLanguagePolicy.ADAPTIVE,
                needs_user_input=True,
                available_actions=["start_new_workflow"],
            )

        return self._snapshot_to_result(
            snapshot,
            assistant_message=self._status_summary(snapshot),
        )

    def _build_review_scope_result(
        self,
        snapshot: WorkflowContextSnapshot | None,
    ) -> FullWorkflowResult:
        if snapshot is None:
            return FullWorkflowResult(
                workflow_id="",
                thread_id="",
                phase=WorkflowPhase.IDLE,
                assistant_message="There is no active review workflow.",
                status_message="No active workflow.",
                preferred_language="en",
                language_policy=WorkflowLanguagePolicy.ADAPTIVE,
                needs_user_input=True,
                available_actions=["start_new_workflow"],
            )

        lang = snapshot.preferred_language
        review_values = self._review_orchestrator.get_review_state_values(
            snapshot.thread_id
        )
        all_operation_contexts = list(review_values.get("all_operation_contexts", []))
        preview = snapshot.current_markdown or self._localize(
            lang,
            "Chưa có preview draft.",
            "No draft preview is available yet.",
        )

        if lang == "en":
            message_lines = [
                "Here is the current review scope:",
                f"- Phase: `{snapshot.phase.value}`",
                f"- Target: `{snapshot.selected_target or '-'}`",
            ]
            if snapshot.canonical_command:
                message_lines.append(
                    f"- Canonical command: `{snapshot.canonical_command}`"
                )
            if snapshot.understanding_explanation:
                message_lines.append(
                    f"- Understanding: {snapshot.understanding_explanation}"
                )
            if all_operation_contexts:
                message_lines.append("")
                message_lines.append(
                    f"Available functions in target `{snapshot.selected_target or '-'}`:"
                )
                message_lines.extend(
                    self._render_operation_catalog(all_operation_contexts)
                )
            if snapshot.review_feedback_history:
                message_lines.append("")
                message_lines.append("Feedback history:")
                for index, item in enumerate(snapshot.review_feedback_history, start=1):
                    message_lines.append(f"- {index}. {item}")
            message_lines.append("")
            message_lines.append("Current draft preview:")
            message_lines.append(preview)
        else:
            message_lines = [
                "Đây là phạm vi review hiện tại:",
                f"- Phase: `{snapshot.phase.value}`",
                f"- Target: `{snapshot.selected_target or '-'}`",
            ]
            if snapshot.canonical_command:
                message_lines.append(
                    f"- Canonical command: `{snapshot.canonical_command}`"
                )
            if snapshot.understanding_explanation:
                message_lines.append(
                    f"- Understanding: {snapshot.understanding_explanation}"
                )
            if all_operation_contexts:
                message_lines.append("")
                message_lines.append(
                    f"Các chức năng hiện có của target `{snapshot.selected_target or '-'}`:"
                )
                message_lines.extend(
                    self._render_operation_catalog(all_operation_contexts)
                )
            if snapshot.review_feedback_history:
                message_lines.append("")
                message_lines.append("Feedback history:")
                for index, item in enumerate(snapshot.review_feedback_history, start=1):
                    message_lines.append(f"- {index}. {item}")
            message_lines.append("")
            message_lines.append("Preview draft hiện tại:")
            message_lines.append(preview)

        return self._snapshot_to_result(
            snapshot,
            assistant_message="\n".join(message_lines),
        )

    def _render_operation_catalog(self, operation_contexts: list[Any]) -> list[str]:
        rendered: list[str] = []
        seen: set[tuple[str, str]] = set()

        for operation in operation_contexts:
            if isinstance(operation, dict):
                method = str(operation.get("method", "-")).upper()
                path = str(operation.get("path", "-"))
                operation_id = str(operation.get("operation_id", "") or "").strip()
                summary = str(operation.get("summary", "") or "").strip()
                tags = list(operation.get("tags", []) or [])
            else:
                method = str(getattr(operation, "method", "-")).upper()
                path = str(getattr(operation, "path", "-"))
                operation_id = str(getattr(operation, "operation_id", "") or "").strip()
                summary = str(getattr(operation, "summary", "") or "").strip()
                tags = list(getattr(operation, "tags", []) or [])

            key = (method, path)
            if key in seen:
                continue
            seen.add(key)

            head = f"{len(seen)}. {method} {path}"
            if operation_id:
                head += f" (operation_id={operation_id})"
            rendered.append(head)

            description = format_operation_description(
                method=method,
                path=path,
                operation_id=operation_id,
                summary=summary,
                tags=tags,
            )
            rendered.append(f"   - Description: {description}")

        return rendered

    def _build_clarification_result(
        self,
        snapshot: WorkflowContextSnapshot | None,
        question: str,
    ) -> FullWorkflowResult:
        if snapshot is None:
            language = (
                "en"
                if "please" in question.lower() or "clarify" in question.lower()
                else "vi"
            )
            return FullWorkflowResult(
                workflow_id="",
                thread_id="",
                phase=WorkflowPhase.IDLE,
                assistant_message=question,
                status_message=self._localize(
                    language,
                    "Cần làm rõ yêu cầu.",
                    "Clarification is required.",
                ),
                preferred_language=language,
                language_policy=WorkflowLanguagePolicy.ADAPTIVE,
                needs_user_input=True,
                available_actions=["clarify", "start_new_workflow"],
            )

        snapshot.pending_router_clarification = question
        self._state_store.save(snapshot)
        return self._snapshot_to_result(
            snapshot,
            assistant_message=question,
        )

    def _status_summary(self, snapshot: WorkflowContextSnapshot) -> str:
        lang = snapshot.preferred_language
        parts: list[str] = [
            self._localize(
                lang,
                f"Workflow `{snapshot.workflow_id}` đang ở phase `{snapshot.phase.value}`.",
                f"Workflow `{snapshot.workflow_id}` is currently in phase `{snapshot.phase.value}`.",
            )
        ]

        if snapshot.selected_target:
            parts.append(f"Target: `{snapshot.selected_target}`.")

        if snapshot.canonical_command:
            parts.append(f"Canonical command: `{snapshot.canonical_command}`.")

        if snapshot.phase == WorkflowPhase.PENDING_SCOPE_CONFIRMATION:
            if snapshot.scope_confirmation_question:
                parts.append(snapshot.scope_confirmation_question)

        if snapshot.artifacts.staged_final_report_md_path:
            parts.append(
                f"Staged final report: `{snapshot.artifacts.staged_final_report_md_path}`."
            )

        if snapshot.artifacts.final_report_md_path:
            parts.append(f"Final report: `{snapshot.artifacts.final_report_md_path}`.")

        if snapshot.rerun_user_text:
            parts.append(f"Rerun instruction: {snapshot.rerun_user_text}")

        return " ".join(parts)

    def _map_review_status_to_phase(self, status: str) -> WorkflowPhase:
        mapping = {
            "pending_target_selection": WorkflowPhase.PENDING_TARGET_SELECTION,
            "pending_scope_confirmation": WorkflowPhase.PENDING_SCOPE_CONFIRMATION,
            "pending_review": WorkflowPhase.PENDING_REVIEW,
            "approved": WorkflowPhase.APPROVED,
            "cancelled": WorkflowPhase.CANCELLED,
            "target_not_found": WorkflowPhase.ERROR,
            "invalid_function": WorkflowPhase.ERROR,
        }
        return mapping.get(status, WorkflowPhase.ERROR)

    def _available_actions(self, phase: WorkflowPhase) -> list[str]:
        if phase == WorkflowPhase.PENDING_TARGET_SELECTION:
            return ["select_target", "cancel", "status", "help"]

        if phase == WorkflowPhase.PENDING_SCOPE_CONFIRMATION:
            return [
                "resume_scope_confirmation",
                "show_scope_catalog",
                "show_scope_group_details",
                "show_scope_operation_details",
                "ask_scope_recommendation",
                "apply_scope_recommendation",
                "cancel",
                "status",
                "help",
            ]

        if phase == WorkflowPhase.PENDING_REVIEW:
            return [
                "approve",
                "revise",
                "show_review_scope",
                "cancel",
                "status",
                "help",
            ]

        if phase == WorkflowPhase.REPORT_INTERACTION:
            return [
                "ask_report_question",
                "revise_report_text",
                "share_report",
                "rerun",
                "finalize",
                "cancel",
                "status",
                "help",
            ]

        if phase == WorkflowPhase.RERUN_REQUESTED:
            return ["start_new_workflow_from_rerun_text", "status", "help"]

        if phase in {WorkflowPhase.FINALIZED, WorkflowPhase.CANCELLED}:
            return ["start_new_workflow", "status", "help"]

        return ["status", "help"]

    def _needs_user_input(self, phase: WorkflowPhase) -> bool:
        return phase not in {WorkflowPhase.EXECUTING, WorkflowPhase.VALIDATING}

    def _clear_pending_clarification(self, snapshot: WorkflowContextSnapshot) -> None:
        snapshot.pending_router_clarification = None

    def _mark_error_snapshot(
        self,
        *,
        snapshot: WorkflowContextSnapshot | None,
        error_message: str,
    ) -> FullWorkflowResult:
        if snapshot is None:
            return FullWorkflowResult(
                workflow_id="",
                thread_id="",
                phase=WorkflowPhase.ERROR,
                assistant_message=error_message,
                status_message="Workflow error.",
                preferred_language="en",
                language_policy=WorkflowLanguagePolicy.ADAPTIVE,
                needs_user_input=True,
                available_actions=["help", "start_new_workflow"],
            )

        snapshot.phase = WorkflowPhase.ERROR
        snapshot.last_router_reason = error_message
        self._state_store.save(snapshot)
        return self._snapshot_to_result(
            snapshot,
            assistant_message=error_message,
        )

    def _localize(self, preferred_language: str, vi_text: str, en_text: str) -> str:
        return en_text if preferred_language == "en" else vi_text