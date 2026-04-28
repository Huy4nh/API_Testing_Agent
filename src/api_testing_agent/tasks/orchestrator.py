from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from api_testing_agent.config import Settings
from api_testing_agent.core.ai_testcase_agent import AITestCaseAgent
from api_testing_agent.core.nl_interpreter import NaturalLanguageInterpreter
from api_testing_agent.core.openapi_ingestor import OpenApiIngestor
from api_testing_agent.core.reporter import TestcaseDraftReporter
from api_testing_agent.core.request_understanding_service import (
    InvalidFunctionRequestError,
    RequestUnderstandingService,
    UnderstandingResult,
)
from api_testing_agent.core.scope_resolution_agent import ScopeResolutionAgent
from api_testing_agent.core.target_candidate_service import CandidateScore, TargetCandidateService
from api_testing_agent.core.target_disambiguation_agent import TargetDisambiguationAgent
from api_testing_agent.core.target_registry import TargetRegistry
from api_testing_agent.core.testcase_generator import TestCaseGenerator
from api_testing_agent.core.testcase_review_graph import build_testcase_review_graph


from api_testing_agent.core.feedback_scope_agent import FeedbackScopeAgent
from api_testing_agent.core.feedback_scope_refiner import FeedbackScopeRefiner
@dataclass(frozen=True)
class ReviewWorkflowResult:
    thread_id: str
    status: str
    original_user_text: str | None = None
    selected_target: str | None = None
    candidate_targets: list[str] | None = None
    selection_question: str | None = None
    canonical_command: str | None = None
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
        target_disambiguation_agent: TargetDisambiguationAgent | None = None,
        scope_resolution_agent: ScopeResolutionAgent | None = None,
        understanding_service: RequestUnderstandingService | None = None,
    ) -> None:
        self._settings = settings
        self._registry = TargetRegistry.from_json_file(settings.target_registry_path)
        self._ingestor = OpenApiIngestor(timeout_seconds=settings.http_timeout_seconds)

        self._rule_generator = TestCaseGenerator()
        self._generator_mode = settings.testcase_generator_mode.strip().lower()
        self._ai_model_name = settings.langchain_model_name.strip()

        self._ai_agent = ai_agent or AITestCaseAgent(model_name=self._ai_model_name)
        self._target_disambiguation_agent = (
            target_disambiguation_agent
            or TargetDisambiguationAgent(model_name=self._ai_model_name)
        )
        self._scope_resolution_agent = (
            scope_resolution_agent
            or ScopeResolutionAgent(model_name=self._ai_model_name)
        )

        self._understanding_service = (
            understanding_service
            or RequestUnderstandingService(
                nl_interpreter=NaturalLanguageInterpreter(),
                scope_resolution_agent=self._scope_resolution_agent,
            )
        )

        self._draft_reporter = TestcaseDraftReporter(output_dir=settings.report_output_dir)
        self._candidate_service = TargetCandidateService(self._registry.list_names())

        self._checkpointer = self._create_checkpointer(
            settings.langgraph_checkpointer,
            settings.langgraph_sqlite_path,
        )

        self._feedback_scope_agent = FeedbackScopeAgent(model_name=self._ai_model_name)
        self._feedback_scope_refiner = FeedbackScopeRefiner(self._feedback_scope_agent)

        self._review_graph = build_testcase_review_graph(
            agent=self._ai_agent,
            draft_reporter=self._draft_reporter,
            feedback_scope_refiner=self._feedback_scope_refiner,
            checkpointer=self._checkpointer,
        )

        # giữ nguyên flow chọn target hiện tại
        self._pending_target_selections: dict[str, dict] = {}

    def list_targets(self) -> list[str]:
        return self._registry.list_names()

    def get_generator_mode(self) -> str:
        return self._generator_mode

    def set_generator_mode(self, mode: str) -> None:
        normalized = mode.strip().lower()
        if normalized not in {"rule", "ai"}:
            raise ValueError("Mode must be either 'rule' or 'ai'.")
        self._generator_mode = normalized

    def get_ai_model(self) -> str:
        return self._ai_model_name

    def set_ai_model(self, model_name: str) -> None:
        cleaned = model_name.strip()
        if hasattr(self._feedback_scope_agent, "set_model_name"):
            self._feedback_scope_agent.set_model_name(cleaned)
        if not cleaned:
            raise ValueError("Model name must not be empty.")

        self._ai_model_name = cleaned
        self._ai_agent.set_model_name(cleaned)

        if hasattr(self._target_disambiguation_agent, "set_model_name"):
            self._target_disambiguation_agent.set_model_name(cleaned)

        if hasattr(self._scope_resolution_agent, "set_model_name"):
            self._scope_resolution_agent.set_model_name(cleaned)

    def run_from_text(self, text: str):
        raise NotImplementedError(
            "Result execution branch is intentionally disabled in this review-only step. "
            "Use start_review_from_text()/resume_target_selection()/resume_review() instead."
        )

    def start_review_from_text(
        self,
        text: str,
        *,
        thread_id: str | None = None,
    ) -> ReviewWorkflowResult:
        actual_thread_id = thread_id or uuid.uuid4().hex
        raw_text = text.strip()

        candidates = self._candidate_service.find_candidates(raw_text)

        if not candidates:
            return ReviewWorkflowResult(
                thread_id=actual_thread_id,
                status="target_not_found",
                original_user_text=raw_text,
                candidate_targets=[],
                message="Could not resolve a target from the request.",
            )

        if len(candidates) == 1:
            selected_target = candidates[0].name
            return self._continue_after_target_selected(
                thread_id=actual_thread_id,
                raw_text=raw_text,
                selected_target=selected_target,
            )

        ranked_names, question = self._rank_target_candidates(raw_text, candidates)
        self._pending_target_selections[actual_thread_id] = {
            "raw_text": raw_text,
            "candidate_targets": ranked_names,
            "selection_question": question,
        }

        return ReviewWorkflowResult(
            thread_id=actual_thread_id,
            status="pending_target_selection",
            original_user_text=raw_text,
            candidate_targets=ranked_names,
            selection_question=question,
            message=None,
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

        selected = self._candidate_service.parse_user_selection(
            cleaned,
            candidate_names,
        )

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
                round_number=int(values.get("review_round", 0)),
                preview_text=values.get("draft_preview"),
                draft_report_json_path=values.get("draft_report_json_path"),
                draft_report_md_path=values.get("draft_report_md_path"),
                message=(
                    "Review approved. This branch stops here intentionally and does not "
                    "execute requests or build final result reports yet."
                ),
            )

        return self._build_review_result_from_snapshot(thread_id, snapshot)

    def get_review_preview(self, thread_id: str) -> ReviewWorkflowResult:
        config = {"configurable": {"thread_id": self._review_thread_id(thread_id)}}
        snapshot = self._review_graph.get_state(config)
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
            understanding = self._understand_request(
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

        # Nếu user không chỉ rõ chức năng, canonical command sẽ là dạng broad:
        # test target <target_name>
        # đây là hành vi đúng theo rule mới
        return self._start_review_after_understanding(
            understanding=understanding,
            thread_id=thread_id,
            selected_target=selected_target,
            operations=operations,
        )

    def _rank_target_candidates(
        self,
        raw_text: str,
        candidates: list[CandidateScore],
    ) -> tuple[list[str], str]:
        candidate_payload = [
            {
                "name": item.name,
                "score": item.score,
                "reason": item.reason,
            }
            for item in candidates
        ]

        if self._target_disambiguation_agent is None:
            return (
                [item.name for item in candidates],
                "Tôi thấy nhiều target gần giống nhau. Bạn muốn chọn target nào?",
            )

        try:
            decision = self._target_disambiguation_agent.decide(
                raw_text=raw_text,
                candidate_payload=candidate_payload,
            )
        except Exception:
            return (
                [item.name for item in candidates],
                "Tôi thấy nhiều target gần giống nhau. Bạn muốn chọn target nào?",
            )

        candidate_map = {item.name: item for item in candidates}
        ranked_names: list[str] = []

        for candidate in decision.candidates:
            if candidate.name in candidate_map:
                ranked_names.append(candidate.name)

        for item in candidates:
            if item.name not in ranked_names:
                ranked_names.append(item.name)

        question = decision.question or "Tôi thấy nhiều target gần giống nhau. Bạn muốn chọn target nào?"
        return ranked_names, question

    def _understand_request(
        self,
        text: str,
        *,
        forced_target_name: str,
        operation_hints: list[dict],
    ) -> UnderstandingResult:
        return self._understanding_service.understand(
            text,
            forced_target_name=forced_target_name,
            operation_hints=operation_hints,
        )

    def _start_review_after_understanding(
        self,
        *,
        understanding: UnderstandingResult,
        thread_id: str,
        selected_target: str,
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
            "target_name": target.name,
            "plan": {
                "test_types": [t.value for t in plan.test_types],
                "ignore_fields": list(plan.ignore_fields),
            },
            "all_operation_contexts": operation_contexts,
            "operation_contexts": operation_contexts,
            "feedback_history": [],
            "review_round": 0,
            "scope_note": None,
            "approved": False,
            "cancelled": False,
        }

        self._review_graph.invoke(initial_state, config=config)
        snapshot = self._review_graph.get_state(config)
        review_result = self._build_review_result_from_snapshot(thread_id, snapshot)

        return ReviewWorkflowResult(
            thread_id=review_result.thread_id,
            status=review_result.status,
            original_user_text=review_result.original_user_text,
            selected_target=selected_target,
            candidate_targets=None,
            selection_question=None,
            canonical_command=review_result.canonical_command,
            round_number=review_result.round_number,
            preview_text=review_result.preview_text,
            draft_report_json_path=review_result.draft_report_json_path,
            draft_report_md_path=review_result.draft_report_md_path,
            available_functions=None,
            message=review_result.message,
        )

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