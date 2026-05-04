from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from api_testing_agent.config import Settings
from api_testing_agent.core.ai_testcase_agent import AITestCaseAgent
from api_testing_agent.core.feedback_scope_agent import FeedbackScopeAgent
from api_testing_agent.core.feedback_scope_refiner import FeedbackScopeRefiner
from api_testing_agent.core.openapi_ingestor import OpenApiIngestor
from api_testing_agent.core.reporter import TestcaseDraftReporter
from api_testing_agent.core.request_understanding_service import (
    InvalidFunctionRequestError,
    RequestUnderstandingService,
    UnderstandingResult,
)
from api_testing_agent.core.scope_conversation_agent import (
    ScopeConversationAgent,
    ScopeConversationDecision,
)
from api_testing_agent.core.scope_resolution_agent import ScopeResolutionAgent
from api_testing_agent.core.target_registry import TargetRegistry, TargetRegistryError
from api_testing_agent.core.target_resolution_agent import TargetResolutionAgent
from api_testing_agent.core.testcase_review_graph import (
    TestcaseReviewState,
    build_testcase_review_graph,
)
from api_testing_agent.core.validation_models import ValidationBatchResult
from api_testing_agent.core.validator import Validator
from api_testing_agent.logging_config import bind_logger, get_logger
from api_testing_agent.tasks.operation_catalog_formatter import (
    format_operation_description,
)
from api_testing_agent.tasks.workflow_models import (
    ScopeRecommendationMode,
    ScopeSelectionMode,
    WorkflowScopeCatalogGroup,
    WorkflowScopeCatalogOperation,
    WorkflowScopeRecommendation,
)


@dataclass(frozen=True)
class ReviewWorkflowResult:
    thread_id: str
    status: str
    original_user_text: str | None = None
    selected_target: str | None = None
    candidate_targets: list[str] | None = None
    selection_question: str | None = None
    canonical_command: str | None = None
    understanding_explanation: str | None = None
    round_number: int = 0
    preview_text: str | None = None
    draft_report_json_path: str | None = None
    draft_report_md_path: str | None = None
    available_functions: list[str] | None = None
    message: str | None = None

    scope_confirmation_question: str | None = None
    scope_confirmation_summary: str | None = None
    scope_selection_mode: ScopeSelectionMode | str | None = None
    scope_catalog_groups: list[WorkflowScopeCatalogGroup] | None = None
    scope_catalog_operations: list[WorkflowScopeCatalogOperation] | None = None
    selected_scope_group_ids: list[str] | None = None
    selected_scope_operation_ids: list[str] | None = None
    excluded_scope_group_ids: list[str] | None = None
    excluded_scope_operation_ids: list[str] | None = None


@dataclass(frozen=True)
class ScopeConfirmationResolution:
    status: str
    mode: ScopeSelectionMode | None = None
    selected_group_ids: list[str] = field(default_factory=list)
    selected_operation_ids: list[str] = field(default_factory=list)
    excluded_group_ids: list[str] = field(default_factory=list)
    excluded_operation_ids: list[str] = field(default_factory=list)
    message: str | None = None


class TestOrchestrator:
    def __init__(
        self,
        settings: Settings,
        *,
        ai_agent: AITestCaseAgent | None = None,
        target_resolution_agent: TargetResolutionAgent | None = None,
        scope_resolution_agent: ScopeResolutionAgent | None = None,
        feedback_scope_agent: FeedbackScopeAgent | None = None,
        understanding_service: RequestUnderstandingService | None = None,
        validator: Validator | None = None,
    ) -> None:
        self._settings = settings
        self._logger = get_logger(__name__)

        self._registry = TargetRegistry.from_json_file(settings.target_registry_path)
        self._ingestor = OpenApiIngestor(timeout_seconds=settings.http_timeout_seconds)
        self._ai_model_name = settings.langchain_model_name.strip()

        self._ai_agent = ai_agent or AITestCaseAgent(model_name=self._ai_model_name)
        self._target_resolution_agent = (
            target_resolution_agent
            or TargetResolutionAgent(model_name=self._ai_model_name)
        )
        self._scope_conversation_agent = ScopeConversationAgent(
            model_name=self._ai_model_name,
            model_provider=getattr(settings, "langchain_model_provider", None),
        )
        self._scope_resolution_agent = (
            scope_resolution_agent
            or ScopeResolutionAgent(model_name=self._ai_model_name)
        )
        self._feedback_scope_agent = (
            feedback_scope_agent
            or FeedbackScopeAgent(model_name=self._ai_model_name)
        )

        self._understanding_service = (
            understanding_service
            or RequestUnderstandingService(
                scope_resolution_agent=self._scope_resolution_agent,
            )
        )
        self._validator = validator or Validator()

        self._draft_reporter = TestcaseDraftReporter(
            output_dir=settings.report_output_dir
        )
        self._feedback_scope_refiner = FeedbackScopeRefiner(
            self._feedback_scope_agent
        )

        self._checkpointer = self._create_checkpointer(
            settings.langgraph_checkpointer,
            settings.langgraph_sqlite_path,
        )

        self._review_graph = build_testcase_review_graph(
            agent=self._ai_agent,
            draft_reporter=self._draft_reporter,
            feedback_scope_refiner=self._feedback_scope_refiner,
            checkpointer=self._checkpointer,
        )

        self._pending_target_selections: dict[str, dict[str, Any]] = {}
        self._pending_scope_confirmations: dict[str, dict[str, Any]] = {}

        self._logger.info(
            "Initialized TestOrchestrator.",
            extra={"payload_source": "orchestrator_init"},
        )

    def set_ai_model(self, model_name: str) -> None:
        cleaned = model_name.strip()
        if not cleaned:
            raise ValueError("Model name must not be empty.")

        self._ai_model_name = cleaned
        self._ai_agent.set_model_name(cleaned)
        self._target_resolution_agent.set_model_name(cleaned)
        self._scope_resolution_agent.set_model_name(cleaned)
        self._feedback_scope_agent.set_model_name(cleaned)
        self._scope_conversation_agent = ScopeConversationAgent(
            model_name=cleaned,
            model_provider=getattr(self._settings, "langchain_model_provider", None),
        )

        self._logger.info(
            f"Updated AI model to {cleaned}.",
            extra={"payload_source": "set_ai_model"},
        )

    def start_review_from_text(
        self,
        text: str,
        *,
        thread_id: str | None = None,
    ) -> ReviewWorkflowResult:
        actual_thread_id = thread_id or uuid.uuid4().hex
        raw_text = text.strip()

        logger = bind_logger(
            self._logger,
            thread_id=actual_thread_id,
            payload_source="start_review",
        )
        logger.info("Starting review workflow from raw text.")

        available_targets = self._registry.list_names()
        decision = self._target_resolution_agent.decide(
            raw_text=raw_text,
            available_targets=available_targets,
        )

        logger.info(f"Target resolution mode={decision.mode}.")

        if decision.mode == "no_match":
            logger.warning("Target resolution returned no match.")
            return ReviewWorkflowResult(
                thread_id=actual_thread_id,
                status="target_not_found",
                original_user_text=raw_text,
                candidate_targets=[],
                message=f"Không xác định được target. {decision.reason}",
            )

        candidate_names = self._sanitize_candidate_targets(
            [item.name for item in decision.candidates]
        )

        if decision.mode == "auto_select" and decision.selected_target:
            if not self._target_exists(decision.selected_target):
                logger.warning(
                    "Auto-selected target does not exist in registry.",
                    extra={"target_name": decision.selected_target},
                )
                if candidate_names:
                    selection_question = decision.question or self._build_selection_question(
                        candidate_names
                    )
                    self._pending_target_selections[actual_thread_id] = {
                        "raw_text": raw_text,
                        "candidate_targets": candidate_names,
                        "selection_question": selection_question,
                        "reason": decision.reason,
                    }
                    return ReviewWorkflowResult(
                        thread_id=actual_thread_id,
                        status="pending_target_selection",
                        original_user_text=raw_text,
                        candidate_targets=candidate_names,
                        selection_question=selection_question,
                        message=(
                            f"Target `{decision.selected_target}` không tồn tại trong registry. "
                            "Bạn hãy chọn lại target hợp lệ."
                        ),
                    )

                return ReviewWorkflowResult(
                    thread_id=actual_thread_id,
                    status="target_not_found",
                    original_user_text=raw_text,
                    candidate_targets=[],
                    message=f"Target `{decision.selected_target}` không tồn tại trong registry.",
                )

            logger.info(
                "Target auto-selected.",
                extra={"target_name": decision.selected_target},
            )
            return self._continue_after_target_selected(
                thread_id=actual_thread_id,
                raw_text=raw_text,
                selected_target=decision.selected_target,
            )

        if not candidate_names:
            logger.warning(
                "No valid candidate targets remain after registry sanitization."
            )
            return ReviewWorkflowResult(
                thread_id=actual_thread_id,
                status="target_not_found",
                original_user_text=raw_text,
                candidate_targets=[],
                message="Không xác định được target hợp lệ trong registry.",
            )

        selection_question = decision.question or self._build_selection_question(
            candidate_names
        )

        self._pending_target_selections[actual_thread_id] = {
            "raw_text": raw_text,
            "candidate_targets": candidate_names,
            "selection_question": selection_question,
            "reason": decision.reason,
        }

        logger.info(
            "Workflow entered pending_target_selection.",
            extra={"target_name": ",".join(candidate_names)},
        )

        return ReviewWorkflowResult(
            thread_id=actual_thread_id,
            status="pending_target_selection",
            original_user_text=raw_text,
            candidate_targets=candidate_names,
            selection_question=selection_question,
            message=decision.reason,
        )

    def _normalize_selection_text(self, text: str) -> str:
        lowered = text.strip().lower()
        normalized = unicodedata.normalize("NFD", lowered)
        without_accents = "".join(
            ch for ch in normalized if unicodedata.category(ch) != "Mn"
        )
        return " ".join(without_accents.split())

    def _selection_aliases_for_target(self, target_name: str) -> set[str]:
        normalized_target = self._normalize_selection_text(target_name)
        aliases = {normalized_target}

        if normalized_target.endswith("local"):
            aliases.update(
                {
                    "local",
                    "may local",
                    "moi truong local",
                }
            )

        if "staging" in normalized_target:
            aliases.update(
                {
                    "staging",
                    "stage",
                    "moi truong staging",
                }
            )

        if normalized_target.endswith("prod") or "production" in normalized_target:
            aliases.update(
                {
                    "production",
                    "prod",
                    "moi truong production",
                    "moi truong prod",
                }
            )

        if normalized_target == "img_local":
            aliases.update({"img local"})

        if normalized_target == "img_api_staging":
            aliases.update({"img staging", "img api staging"})

        if normalized_target == "img_api_prod":
            aliases.update(
                {
                    "img production",
                    "img prod",
                    "img api prod",
                    "img api production",
                }
            )

        return aliases

    def _resolve_target_selection_alias(
        self,
        *,
        cleaned_selection: str,
        candidate_names: list[str],
    ) -> str | None:
        normalized_selection = self._normalize_selection_text(cleaned_selection)

        for name in candidate_names:
            if normalized_selection in self._selection_aliases_for_target(name):
                return name

        return None

    def _target_exists(self, target_name: str) -> bool:
        return target_name in set(self._registry.list_names())

    def _sanitize_candidate_targets(self, candidate_names: list[str]) -> list[str]:
        registry = getattr(self, "_registry", None)
        if registry is None:
            seen: set[str] = set()
            sanitized: list[str] = []
            for name in candidate_names:
                cleaned = str(name).strip()
                if not cleaned or cleaned in seen:
                    continue
                seen.add(cleaned)
                sanitized.append(cleaned)
            return sanitized

        valid_targets = set(registry.list_names())
        seen: set[str] = set()
        sanitized: list[str] = []

        for name in candidate_names:
            if name in valid_targets and name not in seen:
                sanitized.append(name)
                seen.add(name)

        return sanitized

    def _build_selection_question(self, candidate_names: list[str]) -> str:
        if not candidate_names:
            return "Bạn muốn chọn target nào?"
        return (
            "Bạn muốn chọn target nào? "
            f"Các lựa chọn hợp lệ là: {', '.join(candidate_names)}."
        )

    def _build_invalid_target_selection_message(
        self,
        *,
        selection: str,
        candidate_names: list[str],
    ) -> str:
        if candidate_names:
            return (
                f"Lựa chọn không hợp lệ: '{selection}'. "
                f"Hãy chọn một trong các target hợp lệ sau: {', '.join(candidate_names)}."
            )
        return (
            f"Lựa chọn không hợp lệ: '{selection}'. "
            "Hãy chọn lại target hợp lệ."
        )

    def resume_target_selection(
        self,
        thread_id: str,
        *,
        selection: str,
    ) -> ReviewWorkflowResult:
        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            payload_source="resume_target_selection",
        )
        logger.info("Resuming target selection.")

        pending = self._pending_target_selections.get(thread_id)
        if pending is None:
            logger.warning("No pending target selection found.")
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="target_not_found",
                message="No pending target selection found for this thread.",
            )

        raw_text = str(pending["raw_text"])
        candidate_names = self._sanitize_candidate_targets(
            list(pending["candidate_targets"])
        )
        question = str(
            pending["selection_question"]
            or self._build_selection_question(candidate_names)
        )

        cleaned = selection.strip()
        if cleaned.lower() in {"cancel", "huy", "hủy"}:
            self._pending_target_selections.pop(thread_id, None)
            logger.info("User cancelled target selection.")
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="cancelled",
                original_user_text=raw_text,
                candidate_targets=candidate_names,
                selection_question=question,
                message="Target selection was cancelled.",
            )

        selected: str | None = None
        if cleaned.isdigit():
            index = int(cleaned)
            if 1 <= index <= len(candidate_names):
                selected = candidate_names[index - 1]
        else:
            selected = self._resolve_target_selection_alias(
                cleaned_selection=cleaned,
                candidate_names=candidate_names,
            )

        if selected is None or not self._target_exists(selected):
            logger.warning(
                "Invalid target selection submitted by user.",
                extra={"target_name": cleaned},
            )
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="pending_target_selection",
                original_user_text=raw_text,
                candidate_targets=candidate_names,
                selection_question=question,
                message=self._build_invalid_target_selection_message(
                    selection=cleaned,
                    candidate_names=candidate_names,
                ),
            )

        self._pending_target_selections.pop(thread_id, None)
        logger.info("Target selected by user.", extra={"target_name": selected})

        return self._continue_after_target_selected(
            thread_id=thread_id,
            raw_text=raw_text,
            selected_target=selected,
        )

    def remember_scope_recommendation(
        self,
        thread_id: str,
        *,
        recommendation: WorkflowScopeRecommendation | None,
    ) -> None:
        pending = self._pending_scope_confirmations.get(thread_id)
        if pending is None:
            return
        pending["latest_recommendation"] = recommendation
        self._pending_scope_confirmations[thread_id] = pending

    def clear_scope_recommendation(
        self,
        thread_id: str,
    ) -> None:
        pending = self._pending_scope_confirmations.get(thread_id)
        if pending is None:
            return
        pending["latest_recommendation"] = None
        self._pending_scope_confirmations[thread_id] = pending

    def apply_latest_scope_recommendation(
        self,
        thread_id: str,
        *,
        user_message: str = "",
    ) -> ReviewWorkflowResult:
        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            payload_source="apply_latest_scope_recommendation",
        )
        logger.info("Applying latest scope recommendation.")

        pending = self._pending_scope_confirmations.get(thread_id)
        if pending is None:
            logger.warning("No pending scope confirmation found.")
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="target_not_found",
                message="No pending scope confirmation found for this thread.",
            )

        raw_text = str(pending["raw_text"])
        selected_target = str(pending["selected_target"])
        understanding = cast(UnderstandingResult, pending["understanding"])
        operations = list(pending["operations"])
        scope_catalog_groups = list(pending["scope_catalog_groups"])
        scope_catalog_operations = list(pending["scope_catalog_operations"])
        recommendation = cast(
            WorkflowScopeRecommendation | None,
            pending.get("latest_recommendation"),
        )

        decision = self._scope_conversation_agent.apply_recommendation(
            preferred_language="vi",
            scope_catalog_groups=scope_catalog_groups,
            scope_catalog_operations=scope_catalog_operations,
            latest_recommendation=recommendation,
            user_message=user_message,
        )

        if decision.action != "select_scope":
            pending["scope_confirmation_history"] = list(
                pending.get("scope_confirmation_history", [])
            ) + ([user_message] if user_message.strip() else [])
            self._pending_scope_confirmations[thread_id] = pending
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="pending_scope_confirmation",
                original_user_text=raw_text,
                selected_target=selected_target,
                understanding_explanation=(
                    f"Target `{selected_target}` đã được xác định, "
                    "nhưng phạm vi test vẫn cần được xác nhận rõ hơn."
                ),
                scope_confirmation_question=decision.follow_up_question
                or self._build_scope_confirmation_question(
                    group_count=len(scope_catalog_groups),
                    operation_count=len(scope_catalog_operations),
                ),
                scope_confirmation_summary=decision.reason,
                scope_selection_mode=None,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
                selected_scope_group_ids=[],
                selected_scope_operation_ids=[],
                excluded_scope_group_ids=[],
                excluded_scope_operation_ids=[],
                message=decision.reason,
            )

        return self._finalize_scope_selection(
            thread_id=thread_id,
            raw_text=raw_text,
            selected_target=selected_target,
            understanding=understanding,
            operations=operations,
            scope_catalog_groups=scope_catalog_groups,
            scope_catalog_operations=scope_catalog_operations,
            decision=decision,
            history_append=user_message,
        )

    def apply_structured_scope_selection(
        self,
        thread_id: str,
        *,
        selected_group_ids: list[str] | None = None,
        selected_operation_ids: list[str] | None = None,
        excluded_group_ids: list[str] | None = None,
        excluded_operation_ids: list[str] | None = None,
        scope_selection_mode: ScopeSelectionMode | str | None = None,
        user_message: str = "",
        reason: str | None = None,
    ) -> ReviewWorkflowResult:
        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            payload_source="apply_structured_scope_selection",
        )
        logger.info("Applying structured scope selection.")

        pending = self._pending_scope_confirmations.get(thread_id)
        if pending is None:
            logger.warning("No pending scope confirmation found.")
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="target_not_found",
                message="No pending scope confirmation found for this thread.",
            )

        raw_text = str(pending["raw_text"])
        selected_target = str(pending["selected_target"])
        understanding = cast(UnderstandingResult, pending["understanding"])
        operations = list(pending["operations"])
        scope_catalog_groups = list(pending["scope_catalog_groups"])
        scope_catalog_operations = list(pending["scope_catalog_operations"])

        mode = self._coerce_scope_selection_mode(scope_selection_mode)

        decision = ScopeConversationDecision(
            action="select_scope",
            reason=reason or "Structured scope selection applied.",
            source="structured",
            scope_selection_mode=mode or ScopeSelectionMode.CUSTOM,
            selected_group_ids=list(selected_group_ids or []),
            selected_operation_ids=list(selected_operation_ids or []),
            excluded_group_ids=list(excluded_group_ids or []),
            excluded_operation_ids=list(excluded_operation_ids or []),
        )

        return self._finalize_scope_selection(
            thread_id=thread_id,
            raw_text=raw_text,
            selected_target=selected_target,
            understanding=understanding,
            operations=operations,
            scope_catalog_groups=scope_catalog_groups,
            scope_catalog_operations=scope_catalog_operations,
            decision=decision,
            history_append=user_message,
        )

    def resume_scope_confirmation(
        self,
        thread_id: str,
        *,
        user_message: str,
    ) -> ReviewWorkflowResult:
        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            payload_source="resume_scope_confirmation",
        )
        logger.info("Resuming scope confirmation.")

        pending = self._pending_scope_confirmations.get(thread_id)
        if pending is None:
            logger.warning("No pending scope confirmation found.")
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="target_not_found",
                message="No pending scope confirmation found for this thread.",
            )

        raw_text = str(pending["raw_text"])
        selected_target = str(pending["selected_target"])
        understanding = cast(UnderstandingResult, pending["understanding"])
        operations = list(pending["operations"])
        scope_catalog_groups = list(pending["scope_catalog_groups"])
        scope_catalog_operations = list(pending["scope_catalog_operations"])
        latest_recommendation = cast(
            WorkflowScopeRecommendation | None,
            pending.get("latest_recommendation"),
        )
        history = list(pending.get("scope_confirmation_history", []))
        history.append(user_message)

        decision = self._scope_conversation_agent.interpret_scope_selection(
            original_request=raw_text,
            user_message=user_message,
            selected_target=selected_target,
            preferred_language="vi",
            scope_catalog_groups=scope_catalog_groups,
            scope_catalog_operations=scope_catalog_operations,
            latest_recommendation=latest_recommendation,
            scope_confirmation_history=history,
        )

        if decision.action != "select_scope":
            pending["scope_confirmation_history"] = history
            self._pending_scope_confirmations[thread_id] = pending
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="pending_scope_confirmation",
                original_user_text=raw_text,
                selected_target=selected_target,
                understanding_explanation=(
                    f"Target `{selected_target}` đã được xác định, "
                    "nhưng phạm vi test vẫn cần được xác nhận rõ hơn."
                ),
                scope_confirmation_question=decision.follow_up_question
                or self._build_scope_confirmation_question(
                    group_count=len(scope_catalog_groups),
                    operation_count=len(scope_catalog_operations),
                ),
                scope_confirmation_summary=decision.reason,
                scope_selection_mode=None,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
                selected_scope_group_ids=[],
                selected_scope_operation_ids=[],
                excluded_scope_group_ids=[],
                excluded_scope_operation_ids=[],
                message=decision.reason,
            )

        return self._finalize_scope_selection(
            thread_id=thread_id,
            raw_text=raw_text,
            selected_target=selected_target,
            understanding=understanding,
            operations=operations,
            scope_catalog_groups=scope_catalog_groups,
            scope_catalog_operations=scope_catalog_operations,
            decision=decision,
            history_append=user_message,
        )

    def _finalize_scope_selection(
        self,
        *,
        thread_id: str,
        raw_text: str,
        selected_target: str,
        understanding: UnderstandingResult,
        operations: list[Any],
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        decision: ScopeConversationDecision,
        history_append: str | None = None,
    ) -> ReviewWorkflowResult:
        all_group_ids = [item.group_id for item in scope_catalog_groups]
        all_operation_ids = [item.operation_id for item in scope_catalog_operations]

        selected_group_ids = self._filter_valid_group_ids(
            list(decision.selected_group_ids),
            scope_catalog_groups,
        )
        selected_operation_ids = self._filter_valid_operation_ids(
            list(decision.selected_operation_ids),
            scope_catalog_operations,
        )
        excluded_group_ids = self._filter_valid_group_ids(
            list(decision.excluded_group_ids),
            scope_catalog_groups,
        )
        excluded_operation_ids = self._filter_valid_operation_ids(
            list(decision.excluded_operation_ids),
            scope_catalog_operations,
        )

        if excluded_group_ids and not excluded_operation_ids:
            excluded_operation_ids = self._expand_group_ids_to_operation_ids(
                group_ids=excluded_group_ids,
                scope_catalog_groups=scope_catalog_groups,
            )

        mode = self._coerce_scope_selection_mode(decision.scope_selection_mode)

        if mode == ScopeSelectionMode.ALL:
            selected_group_ids = list(all_group_ids)
            selected_operation_ids = list(all_operation_ids)

        if not selected_operation_ids and selected_group_ids:
            selected_operation_ids = self._expand_group_ids_to_operation_ids(
                group_ids=selected_group_ids,
                scope_catalog_groups=scope_catalog_groups,
            )

        if not selected_group_ids and selected_operation_ids:
            selected_group_ids = self._infer_group_ids_from_operation_ids(
                operation_ids=selected_operation_ids,
                scope_catalog_operations=scope_catalog_operations,
            )

        if (excluded_group_ids or excluded_operation_ids) and not selected_operation_ids:
            selected_group_ids = [
                item for item in all_group_ids if item not in set(excluded_group_ids)
            ]
            selected_operation_ids = [
                item
                for item in all_operation_ids
                if item not in set(excluded_operation_ids)
            ]

        if excluded_operation_ids and selected_operation_ids:
            selected_operation_ids = [
                item
                for item in selected_operation_ids
                if item not in set(excluded_operation_ids)
            ]

        if excluded_group_ids and selected_group_ids:
            selected_group_ids = [
                item for item in selected_group_ids if item not in set(excluded_group_ids)
            ]

        if not selected_group_ids and selected_operation_ids:
            selected_group_ids = self._infer_group_ids_from_operation_ids(
                operation_ids=selected_operation_ids,
                scope_catalog_operations=scope_catalog_operations,
            )

        selected_scope_operation_set = set(selected_operation_ids)
        scoped_operations = [
            operation
            for operation in operations
            if str(operation.operation_id).strip() in selected_scope_operation_set
        ]

        if not scoped_operations:
            pending = self._pending_scope_confirmations.get(thread_id, {})
            history = list(pending.get("scope_confirmation_history", []))
            if history_append and history_append.strip():
                history.append(history_append)
            pending["scope_confirmation_history"] = history
            self._pending_scope_confirmations[thread_id] = pending

            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="pending_scope_confirmation",
                original_user_text=raw_text,
                selected_target=selected_target,
                understanding_explanation=(
                    f"Target `{selected_target}` đã được xác định, "
                    "nhưng selection hiện tại chưa khớp operation nào."
                ),
                scope_confirmation_question=self._build_scope_confirmation_question(
                    group_count=len(scope_catalog_groups),
                    operation_count=len(scope_catalog_operations),
                ),
                scope_confirmation_summary="Selection hiện tại chưa map được sang operation nào hợp lệ.",
                scope_selection_mode=None,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
                selected_scope_group_ids=[],
                selected_scope_operation_ids=[],
                excluded_scope_group_ids=[],
                excluded_scope_operation_ids=[],
                message="Selection hiện tại chưa map được sang operation nào. Bạn hãy chọn lại scope.",
            )

        canonical_command_override = self._build_scoped_canonical_command(
            selected_target=selected_target,
            scoped_operations=scoped_operations,
            understanding=understanding,
        )
        understanding_explanation_override = self._build_scoped_understanding_explanation(
            selected_target=selected_target,
            scoped_operations=scoped_operations,
            selected_group_ids=selected_group_ids,
            excluded_group_ids=excluded_group_ids,
            decision=decision,
        )

        self._pending_scope_confirmations.pop(thread_id, None)

        review_result = self._start_review_after_understanding(
            understanding=understanding,
            thread_id=thread_id,
            operations=scoped_operations,
            selected_target=selected_target,
            respect_plan_filters=False,
            canonical_command_override=canonical_command_override,
            understanding_explanation_override=understanding_explanation_override,
            scope_note=decision.reason,
            all_operations=operations,
        )

        return ReviewWorkflowResult(
            thread_id=review_result.thread_id,
            status=review_result.status,
            original_user_text=review_result.original_user_text,
            selected_target=review_result.selected_target,
            candidate_targets=review_result.candidate_targets,
            selection_question=review_result.selection_question,
            canonical_command=review_result.canonical_command,
            understanding_explanation=review_result.understanding_explanation,
            round_number=review_result.round_number,
            preview_text=review_result.preview_text,
            draft_report_json_path=review_result.draft_report_json_path,
            draft_report_md_path=review_result.draft_report_md_path,
            available_functions=review_result.available_functions,
            message=review_result.message,
            scope_confirmation_question=None,
            scope_confirmation_summary=decision.reason,
            scope_selection_mode=mode or ScopeSelectionMode.CUSTOM,
            scope_catalog_groups=scope_catalog_groups,
            scope_catalog_operations=scope_catalog_operations,
            selected_scope_group_ids=selected_group_ids,
            selected_scope_operation_ids=selected_operation_ids,
            excluded_scope_group_ids=excluded_group_ids,
            excluded_scope_operation_ids=excluded_operation_ids,
        )

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

    def _filter_valid_group_ids(
        self,
        group_ids: list[str],
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
    ) -> list[str]:
        valid = {item.group_id for item in scope_catalog_groups}
        seen: set[str] = set()
        result: list[str] = []
        for item in group_ids:
            cleaned = str(item).strip()
            if cleaned in valid and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result

    def _filter_valid_operation_ids(
        self,
        operation_ids: list[str],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
    ) -> list[str]:
        valid = {item.operation_id for item in scope_catalog_operations}
        seen: set[str] = set()
        result: list[str] = []
        for item in operation_ids:
            cleaned = str(item).strip()
            if cleaned in valid and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result
    def _expand_group_ids_to_operation_ids(
        self,
        *,
        group_ids: list[str],
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
    ) -> list[str]:
        selected_group_set = {
            str(group_id).strip()
            for group_id in group_ids
            if str(group_id).strip()
        }

        if not selected_group_set:
            return []

        seen: set[str] = set()
        operation_ids: list[str] = []

        for group in scope_catalog_groups:
            group_id = str(group.group_id).strip()
            if group_id not in selected_group_set:
                continue

            for operation_id in list(group.operation_ids or []):
                cleaned_operation_id = str(operation_id).strip()
                if not cleaned_operation_id:
                    continue
                if cleaned_operation_id in seen:
                    continue

                seen.add(cleaned_operation_id)
                operation_ids.append(cleaned_operation_id)

        return operation_ids
    def _infer_group_ids_from_operation_ids(
        self,
        *,
        operation_ids: list[str],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
    ) -> list[str]:
        operation_lookup = {
            item.operation_id: item for item in scope_catalog_operations if item.group_id
        }
        seen: set[str] = set()
        result: list[str] = []

        for operation_id in operation_ids:
            operation = operation_lookup.get(operation_id)
            if operation is None or operation.group_id is None:
                continue
            if operation.group_id in seen:
                continue
            seen.add(operation.group_id)
            result.append(operation.group_id)

        return result

    def _format_operation_ref(self, operation: Any) -> str:
        method = str(getattr(operation, "method", "")).upper()
        path = str(getattr(operation, "path", "")).strip()
        return f"{method} {path}".strip()

    def _build_scoped_canonical_command(
        self,
        *,
        selected_target: str,
        scoped_operations: list[Any],
        understanding: UnderstandingResult,
    ) -> str:
        operation_refs = [self._format_operation_ref(item) for item in scoped_operations]
        if len(operation_refs) > 4:
            preview = " | ".join(operation_refs[:4]) + " | ..."
        else:
            preview = " | ".join(operation_refs)

        test_types = []
        try:
            test_types = [item.value for item in list(understanding.plan.test_types)]
        except Exception:
            test_types = []

        suffix = " ".join(test_types).strip()
        base = f"test target {selected_target} scoped {preview}".strip()
        return f"{base} {suffix}".strip()

    def _build_scoped_understanding_explanation(
        self,
        *,
        selected_target: str,
        scoped_operations: list[Any],
        selected_group_ids: list[str],
        excluded_group_ids: list[str],
        decision: ScopeConversationDecision,
    ) -> str:
        operation_refs = [self._format_operation_ref(item) for item in scoped_operations]
        if len(operation_refs) > 3:
            operation_preview = ", ".join(operation_refs[:3]) + ", ..."
        else:
            operation_preview = ", ".join(operation_refs)

        pieces = [
            f"Đã xác định target là `{selected_target}` và đã chốt scope cuối cùng theo xác nhận của người dùng.",
        ]
        if selected_group_ids:
            pieces.append(f"Nhóm đã chọn: {', '.join(selected_group_ids)}.")
        if excluded_group_ids:
            pieces.append(f"Nhóm bị loại trừ: {', '.join(excluded_group_ids)}.")
        if operation_preview:
            pieces.append(f"Operation cuối cùng: {operation_preview}.")
        if decision.reason:
            pieces.append(f"Lý do: {decision.reason}")
        return " ".join(pieces).strip()

    def resume_review(
        self,
        thread_id: str,
        *,
        action: str,
        feedback: str = "",
    ) -> ReviewWorkflowResult:
        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            payload_source="resume_review",
        )
        logger.info(f"Resuming review with action={action}.")

        config = self._graph_config(thread_id)

        self._review_graph.invoke(
            Command(
                resume={
                    "action": action,
                    "feedback": feedback,
                }
            ),
            config=config,
        )

        snapshot = self._review_graph.get_state(config)
        values = dict(snapshot.values)

        if values.get("cancelled"):
            logger.info(
                "Review workflow cancelled.",
                extra={"target_name": str(values.get("target_name", "-"))},
            )
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="cancelled",
                original_user_text=values.get("user_request_text"),
                selected_target=values.get("target_name"),
                canonical_command=values.get("canonical_command"),
                understanding_explanation=values.get("understanding_explanation"),
                round_number=int(values.get("review_round", 0)),
                preview_text=values.get("draft_preview"),
                draft_report_json_path=values.get("draft_report_json_path"),
                draft_report_md_path=values.get("draft_report_md_path"),
                message="Review was cancelled.",
            )

        if values.get("approved"):
            logger.info(
                "Review workflow approved.",
                extra={"target_name": str(values.get("target_name", "-"))},
            )
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="approved",
                original_user_text=values.get("user_request_text"),
                selected_target=values.get("target_name"),
                canonical_command=values.get("canonical_command"),
                understanding_explanation=values.get("understanding_explanation"),
                round_number=int(values.get("review_round", 0)),
                preview_text=values.get("draft_preview"),
                draft_report_json_path=values.get("draft_report_json_path"),
                draft_report_md_path=values.get("draft_report_md_path"),
                message="Review approved.",
            )

        logger.info("Review workflow remains pending_review.")
        return self._build_review_result_from_snapshot(thread_id, snapshot)

    def _continue_after_target_selected(
        self,
        *,
        thread_id: str,
        raw_text: str,
        selected_target: str,
    ) -> ReviewWorkflowResult:
        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=selected_target,
            payload_source="target_selected",
        )
        logger.info("Continuing workflow after target selected.")

        try:
            target = self._registry.get(selected_target)
        except TargetRegistryError:
            logger.error("Selected target does not exist in registry.")
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="target_not_found",
                original_user_text=raw_text,
                selected_target=None,
                message=f"Target '{selected_target}' does not exist.",
            )

        operations = self._ingestor.load_for_target(target)
        operation_hints = self._build_operation_hints(operations)

        logger.info(f"Loaded {len(operations)} operations for selected target.")

        try:
            understanding = self._understanding_service.understand(
                raw_text,
                forced_target_name=selected_target,
                operation_hints=operation_hints,
            )
        except InvalidFunctionRequestError as exc:
            logger.warning("Understanding failed with invalid function request.")
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="invalid_function",
                original_user_text=raw_text,
                selected_target=selected_target,
                available_functions=exc.available_functions,
                message=str(exc),
            )

        logger.info("Understanding service completed successfully.")

        scope_confirmation_result = self._maybe_build_scope_confirmation_result(
            thread_id=thread_id,
            raw_text=raw_text,
            selected_target=selected_target,
            understanding=understanding,
            operations=operations,
        )
        if scope_confirmation_result is not None:
            return scope_confirmation_result

        return self._start_review_after_understanding(
            understanding=understanding,
            thread_id=thread_id,
            operations=operations,
            selected_target=selected_target,
            respect_plan_filters=True,
        )

    def _maybe_build_scope_confirmation_result(
        self,
        *,
        thread_id: str,
        raw_text: str,
        selected_target: str,
        understanding: UnderstandingResult,
        operations: list[Any],
    ) -> ReviewWorkflowResult | None:
        full_scope_catalog_groups, full_scope_catalog_operations = self._build_scope_catalog(
            operations
        )

        filtered_operations = self._filter_operations(operations, understanding.plan)
        narrowed_scope_catalog_groups, narrowed_scope_catalog_operations = self._build_scope_catalog(
            filtered_operations
        )

        decision = self._scope_conversation_agent.should_require_scope_confirmation(
            original_request=raw_text,
            selected_target=selected_target,
            preferred_language="vi",
            scope_catalog_groups=full_scope_catalog_groups,
            scope_catalog_operations=full_scope_catalog_operations,
            understanding_explanation=understanding.explanation,
            canonical_command=understanding.canonical_command,
            narrowed_scope_operation_ids=[
                item.operation_id for item in narrowed_scope_catalog_operations
            ],
            narrowed_scope_group_ids=[
                item.group_id for item in narrowed_scope_catalog_groups
            ],
        )

        if decision.action != "require_scope_confirmation":
            return None

        summary = self._build_scope_confirmation_summary(
            target_name=selected_target,
            group_count=len(full_scope_catalog_groups),
            operation_count=len(full_scope_catalog_operations),
        )
        question = decision.follow_up_question or self._build_scope_confirmation_question(
            group_count=len(full_scope_catalog_groups),
            operation_count=len(full_scope_catalog_operations),
        )

        self._pending_scope_confirmations[thread_id] = {
            "raw_text": raw_text,
            "selected_target": selected_target,
            "understanding": understanding,
            "operations": operations,
            "scope_catalog_groups": full_scope_catalog_groups,
            "scope_catalog_operations": full_scope_catalog_operations,
            "scope_confirmation_history": [],
            "latest_recommendation": None,
        }

        return ReviewWorkflowResult(
            thread_id=thread_id,
            status="pending_scope_confirmation",
            original_user_text=raw_text,
            selected_target=selected_target,
            understanding_explanation=(
                f"Target `{selected_target}` đã được xác định, "
                "nhưng phạm vi chức năng cần test chưa đủ rõ nên cần xác nhận scope trước khi sinh testcase."
            ),
            scope_confirmation_question=question,
            scope_confirmation_summary=summary,
            scope_selection_mode=None,
            scope_catalog_groups=full_scope_catalog_groups,
            scope_catalog_operations=full_scope_catalog_operations,
            selected_scope_group_ids=[],
            selected_scope_operation_ids=[],
            excluded_scope_group_ids=[],
            excluded_scope_operation_ids=[],
            message=decision.reason or (
                f"Target `{selected_target}` có nhiều chức năng. "
                "Tôi cần bạn xác nhận muốn test toàn bộ, theo nhóm, hay một vài operation cụ thể."
            ),
        )

    def _humanize_catalog_group_title(self, raw_value: str) -> str:
        cleaned = raw_value.strip().replace("_", " ").replace("-", " ")
        cleaned = " ".join(cleaned.split())
        if not cleaned:
            return "General"
        return cleaned.title()

    def _derive_operation_group_key(self, operation: Any) -> tuple[str, str]:
        tags = list(getattr(operation, "tags", []) or [])
        if tags:
            raw = str(tags[0]).strip()
            return raw.lower(), self._humanize_catalog_group_title(raw)

        path = str(getattr(operation, "path", "")).strip("/")
        first_segment = path.split("/", 1)[0] if path else "general"
        raw = first_segment or "general"
        return raw.lower(), self._humanize_catalog_group_title(raw)

    def _build_scope_catalog(
        self,
        operations: list[Any],
    ) -> tuple[list[WorkflowScopeCatalogGroup], list[WorkflowScopeCatalogOperation]]:
        groups_map: dict[str, WorkflowScopeCatalogGroup] = {}
        scope_operations: list[WorkflowScopeCatalogOperation] = []

        for operation in operations:
            group_key, group_title = self._derive_operation_group_key(operation)

            if group_key not in groups_map:
                groups_map[group_key] = WorkflowScopeCatalogGroup(
                    group_id=group_key,
                    title=group_title,
                    description=f"Operations related to {group_title.lower()}",
                    operation_ids=[],
                    tags=list(getattr(operation, "tags", []) or []),
                )

            operation_id = str(operation.operation_id).strip()
            method = str(operation.method.value).upper()
            path = str(operation.path).strip()
            summary = str(getattr(operation, "summary", "") or "").strip()
            tags = list(getattr(operation, "tags", []) or [])

            description = format_operation_description(
                method=method,
                path=path,
                operation_id=operation_id,
                summary=summary,
                tags=tags,
            )

            scope_operation = WorkflowScopeCatalogOperation(
                operation_id=operation_id,
                method=method,
                path=path,
                group_id=group_key,
                group_title=group_title,
                summary=summary or None,
                description=description,
                tags=tags,
                auth_required=getattr(operation, "auth_required", None),
            )
            scope_operations.append(scope_operation)
            groups_map[group_key].operation_ids.append(operation_id)

        scope_groups = list(groups_map.values())
        scope_groups.sort(key=lambda item: item.title.lower())
        scope_operations.sort(
            key=lambda item: (item.group_title or "", item.path, item.method)
        )
        return scope_groups, scope_operations

    def _build_scope_confirmation_summary(
        self,
        *,
        target_name: str,
        group_count: int,
        operation_count: int,
    ) -> str:
        return (
            f"Target `{target_name}` hiện có khoảng {operation_count} operation "
            f"được gom thành {group_count} nhóm chức năng. "
            "Trước khi sinh testcase, bạn hãy xác nhận muốn test toàn bộ, "
            "theo nhóm, hay theo một số operation cụ thể."
        )

    def _build_scope_confirmation_question(
        self,
        *,
        group_count: int,
        operation_count: int,
    ) -> str:
        return (
            f"Hiện có {group_count} nhóm chức năng / {operation_count} operation. "
            "Bạn muốn test toàn bộ, chỉ một vài nhóm, hay một số operation cụ thể? "
            "Bạn cũng có thể hỏi xem chi tiết một nhóm trước khi quyết định."
        )

    def _start_review_after_understanding(
        self,
        *,
        understanding: UnderstandingResult,
        thread_id: str,
        operations: list[Any],
        selected_target: str,
        respect_plan_filters: bool = True,
        canonical_command_override: str | None = None,
        understanding_explanation_override: str | None = None,
        scope_note: str | None = None,
        all_operations: list[Any] | None = None,
    ) -> ReviewWorkflowResult:
        plan = understanding.plan
        all_available_operations = list(all_operations or operations)

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=selected_target,
            payload_source="start_review_after_understanding",
        )

        if plan.target_name != selected_target:
            logger.warning(
                "Understanding plan target_name differs from selected target; using selected target instead.",
                extra={"resolved_target_name": plan.target_name},
            )

        try:
            target = self._registry.get(selected_target)
        except TargetRegistryError:
            logger.error("Selected target disappeared from registry before review start.")
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="target_not_found",
                original_user_text=understanding.original_text,
                selected_target=None,
                canonical_command=understanding.canonical_command,
                understanding_explanation=understanding.explanation,
                message=f"Target '{selected_target}' does not exist.",
            )

        logger.info("Starting review graph after understanding phase.")

        if respect_plan_filters:
            filtered_operations = self._filter_operations(operations, plan)
            filtered_operations = filtered_operations[: plan.limit_endpoints]
        else:
            filtered_operations = list(operations)
            if plan.limit_endpoints and len(filtered_operations) > plan.limit_endpoints:
                filtered_operations = filtered_operations[: plan.limit_endpoints]

        logger.info(
            "Filtered operations count="
            f"{len(filtered_operations)} from input_scope={len(operations)}, "
            f"all_available={len(all_available_operations)}."
        )

        if not filtered_operations:
            logger.error("No operations matched the request after filtering.")
            raise ValueError("No operations matched the request.")

        operation_contexts = [
            self._build_operation_context(operation)
            for operation in filtered_operations
        ]

        all_operation_contexts = [
            self._build_operation_context(operation)
            for operation in all_available_operations
        ]

        config = self._graph_config(thread_id)

        initial_state: TestcaseReviewState = {
            "thread_id": thread_id,
            "user_request_text": understanding.original_text,
            "canonical_command": canonical_command_override
            or understanding.canonical_command,
            "understanding_explanation": understanding_explanation_override
            or understanding.explanation,
            "target_name": target.name,
            "plan": {
                "test_types": [t.value for t in plan.test_types],
                "ignore_fields": list(plan.ignore_fields),
            },
            "all_operation_contexts": all_operation_contexts,
            "operation_contexts": operation_contexts,
            "feedback_history": [],
            "review_round": 0,
            "scope_note": scope_note,
            "approved": False,
            "cancelled": False,
        }

        self._review_graph.invoke(initial_state, config=config)
        snapshot = self._review_graph.get_state(config)

        logger.info("Initial review graph invocation completed.")

        return self._build_review_result_from_snapshot(thread_id, snapshot)

    def _build_operation_hints(self, operations: list[Any]) -> list[dict[str, Any]]:
        hints: list[dict[str, Any]] = []
        for operation in operations:
            hints.append(
                {
                    "operation_id": operation.operation_id,
                    "method": operation.method.value.upper(),
                    "path": operation.path,
                    "tags": operation.tags,
                    "summary": operation.summary,
                }
            )
        return hints

    def _build_review_result_from_snapshot(
        self,
        thread_id: str,
        snapshot: Any,
    ) -> ReviewWorkflowResult:
        values = dict(snapshot.values)
        status = "pending_review" if self._snapshot_has_interrupt(snapshot) else "idle"

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=str(values.get("target_name", "-")),
            payload_source="snapshot_to_result",
        )
        logger.info(f"Building ReviewWorkflowResult from snapshot with status={status}.")

        return ReviewWorkflowResult(
            thread_id=thread_id,
            status=status,
            original_user_text=values.get("user_request_text"),
            selected_target=values.get("target_name"),
            canonical_command=values.get("canonical_command"),
            understanding_explanation=values.get("understanding_explanation"),
            round_number=int(values.get("review_round", 0)),
            preview_text=values.get("draft_preview"),
            draft_report_json_path=values.get("draft_report_json_path"),
            draft_report_md_path=values.get("draft_report_md_path"),
            available_functions=None,
            message=None,
        )

    def _filter_operations(self, operations: list[Any], plan: Any) -> list[Any]:
        filtered: list[Any] = []

        for operation in operations:
            if plan.methods and operation.method not in plan.methods:
                continue

            if plan.tags:
                operation_tags_lower = {tag.lower() for tag in operation.tags}
                plan_tags_lower = {tag.lower() for tag in plan.tags}
                if not operation_tags_lower.intersection(plan_tags_lower):
                    continue

            if plan.paths and operation.path not in plan.paths:
                continue

            filtered.append(operation)

        return filtered

    def _build_operation_context(self, operation: Any) -> dict[str, Any]:
        return {
            "operation_id": operation.operation_id,
            "method": operation.method.value.upper(),
            "path": operation.path,
            "tags": operation.tags,
            "summary": operation.summary,
            "auth_required": operation.auth_required,
            "parameters": [
                {
                    "name": p.name,
                    "location": p.location.value,
                    "required": p.required,
                    "schema": p.schema,
                }
                for p in operation.parameters
            ],
            "request_body": {
                "required": operation.request_body.required,
                "content_type": operation.request_body.content_type,
                "schema": operation.request_body.schema,
            }
            if operation.request_body
            else None,
            "responses": operation.responses,
        }

    def _snapshot_has_interrupt(self, snapshot: Any) -> bool:
        for task in getattr(snapshot, "tasks", ()):
            interrupts = getattr(task, "interrupts", ())
            if interrupts:
                return True
        return False

    def _review_thread_id(self, thread_id: str) -> str:
        return f"review::{thread_id}"

    def _graph_config(self, thread_id: str) -> RunnableConfig:
        return cast(
            RunnableConfig,
            {"configurable": {"thread_id": self._review_thread_id(thread_id)}},
        )

    def _create_checkpointer(self, mode: str, sqlite_path: str):
        normalized = mode.strip().lower()

        if normalized == "sqlite":
            from langgraph.checkpoint.sqlite import SqliteSaver

            connection = sqlite3.connect(sqlite_path, check_same_thread=False)
            return SqliteSaver(connection)

        return InMemorySaver()

    def get_review_state_values(self, thread_id: str) -> dict[str, Any]:
        config = self._graph_config(thread_id)
        snapshot = self._review_graph.get_state(config)
        return dict(snapshot.values)

    def get_approved_execution_payload(self, thread_id: str) -> dict[str, Any]:
        values = self.get_review_state_values(thread_id)

        if not values.get("approved"):
            raise ValueError("Review has not been approved yet.")

        target_name = str(values.get("target_name", "")).strip()
        if not target_name:
            raise ValueError("Approved review is missing target_name.")

        target = self._registry.get(target_name)

        return {
            "thread_id": thread_id,
            "target": target,
            "target_name": target_name,
            "canonical_command": values.get("canonical_command", ""),
            "understanding_explanation": values.get("understanding_explanation"),
            "operation_contexts": list(values.get("operation_contexts", [])),
            "draft_groups": list(values.get("draft_groups", [])),
            "draft_report_json_path": values.get("draft_report_json_path"),
            "draft_report_md_path": values.get("draft_report_md_path"),
        }

    def validate_execution_batch(
        self,
        execution_batch_result: Any,
    ) -> ValidationBatchResult:
        thread_id = self._extract_runtime_value(execution_batch_result, "thread_id")
        target_name = self._extract_runtime_value(execution_batch_result, "target_name")

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="orchestrator_validate_execution_batch",
        )
        logger.info("Starting validation from execution batch.")

        validation_batch = self._validator.validate_batch(execution_batch_result)

        logger.info(
            "Finished validation from execution batch.",
            extra={
                "pass_cases": validation_batch.pass_cases,
                "fail_cases": validation_batch.fail_cases,
                "skip_cases": validation_batch.skip_cases,
                "error_cases": validation_batch.error_cases,
            },
        )
        return validation_batch

    def validate_execution_report_file(
        self,
        execution_report_path: str | Path,
    ) -> ValidationBatchResult:
        report_path = Path(execution_report_path)

        logger = bind_logger(
            self._logger,
            report_path=str(report_path),
            payload_source="orchestrator_validate_execution_report_file",
        )
        logger.info("Loading execution report file for validation.")

        if not report_path.exists():
            raise FileNotFoundError(f"Execution report not found: {report_path}")

        payload = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Execution report JSON root must be an object.")

        return self.validate_execution_batch(payload)

    def _extract_runtime_value(self, source: Any, key: str) -> Any:
        if isinstance(source, dict):
            return source.get(key)
        return getattr(source, key, None)