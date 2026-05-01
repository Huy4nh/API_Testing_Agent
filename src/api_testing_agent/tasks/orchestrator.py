from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
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
from api_testing_agent.core.scope_resolution_agent import ScopeResolutionAgent
from api_testing_agent.core.target_resolution_agent import TargetResolutionAgent
from api_testing_agent.core.target_registry import TargetRegistry
from api_testing_agent.core.testcase_review_graph import (
    TestcaseReviewState,
    build_testcase_review_graph,
)
from api_testing_agent.logging_config import bind_logger, get_logger

import json
from pathlib import Path

from api_testing_agent.core.validation_models import ValidationBatchResult
from api_testing_agent.core.validator import Validator

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
            target_resolution_agent or TargetResolutionAgent(model_name=self._ai_model_name)
        )
        self._scope_resolution_agent = (
            scope_resolution_agent or ScopeResolutionAgent(model_name=self._ai_model_name)
        )
        self._feedback_scope_agent = (
            feedback_scope_agent or FeedbackScopeAgent(model_name=self._ai_model_name)
        )

        self._understanding_service = (
            understanding_service
            or RequestUnderstandingService(
                scope_resolution_agent=self._scope_resolution_agent,
            )
        )
        self._validator = validator or Validator()
        
        self._draft_reporter = TestcaseDraftReporter(output_dir=settings.report_output_dir)
        self._feedback_scope_refiner = FeedbackScopeRefiner(self._feedback_scope_agent)

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

        if decision.mode == "auto_select" and decision.selected_target:
            logger.info(
                "Target auto-selected.",
                extra={"target_name": decision.selected_target},
            )
            return self._continue_after_target_selected(
                thread_id=actual_thread_id,
                raw_text=raw_text,
                selected_target=decision.selected_target,
            )

        candidate_names = [item.name for item in decision.candidates]
        self._pending_target_selections[actual_thread_id] = {
            "raw_text": raw_text,
            "candidate_targets": candidate_names,
            "selection_question": decision.question or "Bạn muốn chọn target nào?",
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
            selection_question=decision.question or "Bạn muốn chọn target nào?",
            message=decision.reason,
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
        candidate_names = list(pending["candidate_targets"])
        question = str(pending["selection_question"])

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
            for name in candidate_names:
                if cleaned.lower() == name.lower():
                    selected = name
                    break

        if selected is None:
            logger.warning("Invalid target selection submitted by user.")
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="pending_target_selection",
                original_user_text=raw_text,
                candidate_targets=candidate_names,
                selection_question=question,
                message=(
                    f"Lựa chọn không hợp lệ: '{cleaned}'. "
                    "Hãy chọn bằng số thứ tự hoặc tên target."
                ),
            )

        self._pending_target_selections.pop(thread_id, None)
        logger.info("Target selected by user.", extra={"target_name": selected})

        return self._continue_after_target_selected(
            thread_id=thread_id,
            raw_text=raw_text,
            selected_target=selected,
        )

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

        target = self._registry.get(selected_target)
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

        return self._start_review_after_understanding(
            understanding=understanding,
            thread_id=thread_id,
            operations=operations,
        )

    def _start_review_after_understanding(
        self,
        *,
        understanding: UnderstandingResult,
        thread_id: str,
        operations: list[Any],
    ) -> ReviewWorkflowResult:
        plan = understanding.plan
        target = self._registry.get(plan.target_name)

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target.name,
            payload_source="start_review_after_understanding",
        )
        logger.info("Starting review graph after understanding phase.")

        filtered_operations = self._filter_operations(operations, plan)
        filtered_operations = filtered_operations[: plan.limit_endpoints]

        logger.info(
            f"Filtered operations count={len(filtered_operations)} from total={len(operations)}."
        )

        if not filtered_operations:
            logger.error("No operations matched the request after filtering.")
            raise ValueError("No operations matched the request.")

        operation_contexts = [
            self._build_operation_context(operation)
            for operation in filtered_operations
        ]

        config = self._graph_config(thread_id)

        initial_state: TestcaseReviewState = {
            "thread_id": thread_id,
            "user_request_text": understanding.original_text,
            "canonical_command": understanding.canonical_command,
            "understanding_explanation": understanding.explanation,
            "target_name": target.name,
            "plan": {
                "test_types": [t.value for t in plan.test_types],
                "ignore_fields": list(plan.ignore_fields),
            },
            "all_operation_contexts": [
                self._build_operation_context(operation)
                for operation in operations
            ],
            "operation_contexts": operation_contexts,
            "feedback_history": [],
            "review_round": 0,
            "scope_note": None,
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

    def _build_review_result_from_snapshot(self, thread_id: str, snapshot: Any) -> ReviewWorkflowResult:
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
    def validate_execution_batch(self, execution_batch_result: Any) -> ValidationBatchResult:
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

    def validate_execution_report_file(self, execution_report_path: str | Path) -> ValidationBatchResult:
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