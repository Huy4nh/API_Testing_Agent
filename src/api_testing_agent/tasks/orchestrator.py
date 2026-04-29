from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

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
from api_testing_agent.core.testcase_review_graph import build_testcase_review_graph
from api_testing_agent.core.target_registry import TargetRegistry

from typing import Any

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
    ) -> None:
        self._settings = settings
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

        self._pending_target_selections: dict[str, dict] = {}

    def set_ai_model(self, model_name: str) -> None:
        cleaned = model_name.strip()
        if not cleaned:
            raise ValueError("Model name must not be empty.")

        self._ai_model_name = cleaned
        self._ai_agent.set_model_name(cleaned)
        self._target_resolution_agent.set_model_name(cleaned)
        self._scope_resolution_agent.set_model_name(cleaned)
        self._feedback_scope_agent.set_model_name(cleaned)

    def start_review_from_text(
        self,
        text: str,
        *,
        thread_id: str | None = None,
    ) -> ReviewWorkflowResult:
        actual_thread_id = thread_id or uuid.uuid4().hex
        raw_text = text.strip()

        available_targets = self._registry.list_names()
        decision = self._target_resolution_agent.decide(
            raw_text=raw_text,
            available_targets=available_targets,
        )

        if decision.mode == "no_match":
            return ReviewWorkflowResult(
                thread_id=actual_thread_id,
                status="target_not_found",
                original_user_text=raw_text,
                candidate_targets=[],
                message=f"Không xác định được target. {decision.reason}",
            )

        if decision.mode == "auto_select" and decision.selected_target:
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
        pending = self._pending_target_selections.get(thread_id)
        if pending is None:
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="target_not_found",
                message="No pending target selection found for this thread.",
            )

        raw_text = pending["raw_text"]
        candidate_names = pending["candidate_targets"]
        question = pending["selection_question"]

        cleaned = selection.strip()
        if cleaned.lower() in {"cancel", "huy", "hủy"}:
            self._pending_target_selections.pop(thread_id, None)
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="cancelled",
                original_user_text=raw_text,
                candidate_targets=candidate_names,
                selection_question=question,
                message="Target selection was cancelled.",
            )

        selected = None
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
        config = {"configurable": {"thread_id": self._review_thread_id(thread_id)}}

        self._review_graph.invoke(
            Command(
                resume={
                    "action": action,
                    "feedback": feedback,
                }
            ),
            config=config,
            version="v2",
        )

        snapshot = self._review_graph.get_state(config)
        values = snapshot.values

        if values.get("cancelled"):
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

        return self._build_review_result_from_snapshot(thread_id, snapshot)

    def _continue_after_target_selected(
        self,
        *,
        thread_id: str,
        raw_text: str,
        selected_target: str,
    ) -> ReviewWorkflowResult:
        target = self._registry.get(selected_target)
        operations = self._ingestor.load_for_target(target)
        operation_hints = self._build_operation_hints(operations)

        try:
            understanding = self._understanding_service.understand(
                raw_text,
                forced_target_name=selected_target,
                operation_hints=operation_hints,
            )
        except InvalidFunctionRequestError as exc:
            return ReviewWorkflowResult(
                thread_id=thread_id,
                status="invalid_function",
                original_user_text=raw_text,
                selected_target=selected_target,
                available_functions=exc.available_functions,
                message=str(exc),
            )

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
        operations: list,
    ) -> ReviewWorkflowResult:
        plan = understanding.plan
        target = self._registry.get(plan.target_name)

        filtered_operations = self._filter_operations(operations, plan)
        filtered_operations = filtered_operations[: plan.limit_endpoints]

        if not filtered_operations:
            raise ValueError("No operations matched the request.")

        operation_contexts = [
            self._build_operation_context(operation)
            for operation in filtered_operations
        ]

        config = {"configurable": {"thread_id": self._review_thread_id(thread_id)}}

        initial_state = {
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

        self._review_graph.invoke(initial_state, config=config, version="v2")
        snapshot = self._review_graph.get_state(config)
        return self._build_review_result_from_snapshot(thread_id, snapshot)

    def _build_operation_hints(self, operations: list) -> list[dict]:
        hints: list[dict] = []
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

    def _build_review_result_from_snapshot(self, thread_id: str, snapshot) -> ReviewWorkflowResult:
        values = snapshot.values
        status = "pending_review" if self._snapshot_has_interrupt(snapshot) else "idle"

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

    def _filter_operations(self, operations, plan):
        filtered = []

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

    def _build_operation_context(self, operation) -> dict:
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

    def _snapshot_has_interrupt(self, snapshot) -> bool:
        for task in getattr(snapshot, "tasks", ()):
            interrupts = getattr(task, "interrupts", ())
            if interrupts:
                return True
        return False

    def _review_thread_id(self, thread_id: str) -> str:
        return f"review::{thread_id}"

    def _create_checkpointer(self, mode: str, sqlite_path: str):
        normalized = mode.strip().lower()

        if normalized == "sqlite":
            from langgraph.checkpoint.sqlite import SqliteSaver

            connection = sqlite3.connect(sqlite_path, check_same_thread=False)
            return SqliteSaver(connection)

        return InMemorySaver()
    
    def get_review_state_values(self, thread_id: str) -> dict[str, Any]:
        config = {"configurable": {"thread_id": self._review_thread_id(thread_id)}}
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