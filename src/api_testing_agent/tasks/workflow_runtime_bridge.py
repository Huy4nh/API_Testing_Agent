from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, cast

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from api_testing_agent.config import Settings
from api_testing_agent.core.execution_engine import ExecutionEngine
from api_testing_agent.core.report_context_builder import ReportContextBuilder
from api_testing_agent.core.report_hybrid_ai import (
    ReportHybridAI,
    ReviewActionHybridAIProtocol,
)
from api_testing_agent.core.report_intent_agent import ReportIntentAgent
from api_testing_agent.core.report_interaction_graph import (
    build_report_interaction_graph,
    report_graph_config,
)
from api_testing_agent.core.report_interaction_models import ReportInteractionState
from api_testing_agent.core.reporter.interactive.interactive_report_service import (
    InteractiveReportService,
)
from api_testing_agent.core.unknown_output_description_service import (
    UnknownOutputDescriptionService,
)
from api_testing_agent.core.validator import Validator
from api_testing_agent.logging_config import bind_logger, get_logger
from api_testing_agent.manual_test.report_testcase.manual_review_workflow_test import (
    _build_final_report_payload,
    _normalize_review_input,
    _persist_final_report_to_sqlite,
    _write_execution_reports,
    _write_staged_final_reports,
    _write_validation_reports,
)
from api_testing_agent.tasks.workflow_models import (
    PostApprovalRuntimeResult,
    ReportInteractionUpdate,
)


class WorkflowRuntimeBridge:
    def __init__(
        self,
        settings: Settings,
        *,
        execution_engine: ExecutionEngine | None = None,
        validator: Validator | None = None,
        review_action_ai: ReviewActionHybridAIProtocol | None = None,
        report_hybrid_ai: ReportHybridAI | None = None,
        report_service: InteractiveReportService | None = None,
        report_intent_agent: ReportIntentAgent | None = None,
        report_graph: Any | None = None,
    ) -> None:
        self._settings = settings
        self._logger = get_logger(__name__)

        model_name = settings.langchain_model_name
        model_provider = getattr(settings, "langchain_model_provider", None)

        if execution_engine is None:
            unknown_output_description_service = UnknownOutputDescriptionService(
                model_name=model_name,
                model_provider=model_provider,
            )
            execution_engine = ExecutionEngine(
                timeout_seconds=settings.http_timeout_seconds,
                unknown_output_description_service=unknown_output_description_service,
            )

        self._execution_engine = execution_engine
        self._validator = validator or Validator()

        self._review_action_ai = review_action_ai or ReportHybridAI(
            model_name=model_name,
            model_provider=model_provider,
        )

        self._report_hybrid_ai = report_hybrid_ai or ReportHybridAI(
            model_name=model_name,
            model_provider=model_provider,
        )

        self._report_service = report_service or InteractiveReportService(
            output_dir=settings.report_output_dir,
            context_builder=ReportContextBuilder(),
            hybrid_ai=self._report_hybrid_ai,
        )

        self._report_intent_agent = report_intent_agent or ReportIntentAgent(
            hybrid_ai=self._report_hybrid_ai,
        )

        self._report_graph = report_graph or build_report_interaction_graph(
            intent_agent=self._report_intent_agent,
            report_service=self._report_service,
            checkpointer=self._create_checkpointer(),
        )

    def normalize_review_input(
        self,
        *,
        raw_action: str,
        thread_id: str,
        target_name: str | None,
        preview_text: str,
        feedback_history: list[str],
    ) -> tuple[str, str]:
        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=str(target_name or "-"),
            payload_source="workflow_runtime_bridge_normalize_review_input",
        )
        logger.info("Normalizing review input through runtime bridge.")

        action, feedback = _normalize_review_input(
            raw_action,
            hybrid_ai=self._review_action_ai,
            thread_id=thread_id,
            target_name=target_name,
            preview_text=preview_text,
            feedback_history=feedback_history,
        )
        logger.info(f"Normalized review action={action!r}.")
        return action, feedback

    def run_post_approval(
        self,
        *,
        approved_payload: dict[str, Any],
        original_request: str,
        candidate_targets_history: list[str],
        target_selection_question: str | None,
        review_feedback_history: list[str],
    ) -> PostApprovalRuntimeResult:
        thread_id = str(approved_payload["thread_id"])
        target_name = str(approved_payload["target_name"])

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="workflow_runtime_bridge_run_post_approval",
        )
        logger.info("Running post-approval execution/validation/report pipeline.")

        execution_batch_result = self._execution_engine.execute_approved_draft(
            thread_id=approved_payload["thread_id"],
            target=approved_payload["target"],
            target_name=approved_payload["target_name"],
            operation_contexts=approved_payload["operation_contexts"],
            draft_groups=approved_payload["draft_groups"],
        )

        logger.info(
            "Execution batch finished.",
            extra={
                "target_name": execution_batch_result.target_name,
                "payload_source": "execution_batch",
            },
        )

        execution_report_paths = _write_execution_reports(
            settings=self._settings,
            batch_result=execution_batch_result,
        )

        approved_payload["execution_report_json_path"] = execution_report_paths["json_path"]
        approved_payload["execution_report_md_path"] = execution_report_paths["md_path"]

        validation_batch_result = self._validator.validate_batch(execution_batch_result)

        logger.info(
            "Validation batch finished.",
            extra={
                "target_name": validation_batch_result.target_name or "-",
                "payload_source": "validation_batch",
                "pass_cases": validation_batch_result.pass_cases,
                "fail_cases": validation_batch_result.fail_cases,
                "skip_cases": validation_batch_result.skip_cases,
                "error_cases": validation_batch_result.error_cases,
            },
        )

        validation_report_paths = _write_validation_reports(
            settings=self._settings,
            batch_result=validation_batch_result,
        )

        approved_payload["validation_report_json_path"] = validation_report_paths["json_path"]
        approved_payload["validation_report_md_path"] = validation_report_paths["md_path"]

        final_report_payload = _build_final_report_payload(
            approved_payload=approved_payload,
            execution_batch_result=execution_batch_result,
            execution_report_paths=execution_report_paths,
            validation_batch_result=validation_batch_result,
            validation_report_paths=validation_report_paths,
            original_request=original_request,
            candidate_targets_history=candidate_targets_history,
            target_selection_question=target_selection_question,
            review_feedback_history=review_feedback_history,
        )

        staged_final_report_paths = _write_staged_final_reports(
            settings=self._settings,
            final_report_payload=final_report_payload,
        )

        final_report_payload["links"]["final_report_json_path"] = staged_final_report_paths["json_path"]
        final_report_payload["links"]["final_report_md_path"] = staged_final_report_paths["md_path"]

        interaction_update = self.start_report_interaction_session(
            final_report_payload=final_report_payload,
            approved_payload=approved_payload,
            execution_batch_result=execution_batch_result,
            validation_batch_result=validation_batch_result,
            original_request=original_request,
            candidate_targets_history=candidate_targets_history,
            target_selection_question=target_selection_question,
            review_feedback_history=review_feedback_history,
        )

        return PostApprovalRuntimeResult(
            approved_payload=approved_payload,
            execution_batch_result=execution_batch_result,
            validation_batch_result=validation_batch_result,
            final_report_payload=final_report_payload,
            execution_report_json_path=execution_report_paths["json_path"],
            execution_report_md_path=execution_report_paths["md_path"],
            validation_report_json_path=validation_report_paths["json_path"],
            validation_report_md_path=validation_report_paths["md_path"],
            staged_final_report_json_path=staged_final_report_paths["json_path"],
            staged_final_report_md_path=staged_final_report_paths["md_path"],
            current_markdown=interaction_update.current_markdown,
            messages=interaction_update.messages,
            assistant_messages=interaction_update.assistant_messages,
            assistant_message_count=interaction_update.assistant_message_count,
            artifact_paths=interaction_update.artifact_paths,
        )

    def start_report_interaction_session(
        self,
        *,
        final_report_payload: dict[str, Any],
        approved_payload: dict[str, Any],
        execution_batch_result: Any,
        validation_batch_result: Any,
        original_request: str,
        candidate_targets_history: list[str],
        target_selection_question: str | None,
        review_feedback_history: list[str],
    ) -> ReportInteractionUpdate:
        thread_id = str(final_report_payload["summary"]["thread_id"])
        target_name = str(final_report_payload["summary"]["target_name"])

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="workflow_runtime_bridge_start_report_interaction",
        )
        logger.info("Bootstrapping report interaction graph session.")

        initial_state: ReportInteractionState = {
            "thread_id": thread_id,
            "target_name": target_name,
            "original_request": original_request,
            "canonical_command": approved_payload.get("canonical_command"),
            "understanding_explanation": approved_payload.get("understanding_explanation"),
            "candidate_targets": list(candidate_targets_history or []),
            "target_selection_question": target_selection_question,
            "review_feedback_history": list(review_feedback_history or []),
            "draft_report_json_path": approved_payload.get("draft_report_json_path"),
            "draft_report_md_path": approved_payload.get("draft_report_md_path"),
            "execution_report_json_path": approved_payload.get("execution_report_json_path"),
            "execution_report_md_path": approved_payload.get("execution_report_md_path"),
            "validation_report_json_path": approved_payload.get("validation_report_json_path"),
            "validation_report_md_path": approved_payload.get("validation_report_md_path"),
            "staged_final_report_json_path": final_report_payload["links"]["final_report_json_path"],
            "staged_final_report_md_path": final_report_payload["links"]["final_report_md_path"],
            "final_report_json_path": None,
            "final_report_md_path": None,
            "final_report_markdown": Path(
                str(final_report_payload["links"]["final_report_md_path"])
            ).read_text(encoding="utf-8"),
            "final_report_data": final_report_payload,
            "execution_batch_result": execution_batch_result,
            "validation_batch_result": validation_batch_result,
            "messages": [],
            "finalized": False,
            "cancelled": False,
            "rerun_requested": False,
            "artifact_paths": [],
            "preferred_language": approved_payload.get("preferred_language", "vi"),
            "pending_revision_instruction": None,
            "pending_rerun_instruction": None,
            "latest_user_message": "",
            "last_intent": "",
            "last_intent_reason": "",
            "last_intent_confidence": 0.0,
        }

        config = report_graph_config(thread_id)
        self._report_graph.invoke(cast(ReportInteractionState, initial_state), config=config)

        snapshot = self._report_graph.get_state(config)
        values = dict(snapshot.values)

        assistant_messages = self._extract_new_assistant_messages(
            values=values,
            previous_assistant_count=0,
        )

        return ReportInteractionUpdate(
            thread_id=thread_id,
            target_name=target_name,
            assistant_messages=assistant_messages,
            assistant_message_count=self._count_assistant_messages(values),
            current_markdown=str(values.get("final_report_markdown", "") or ""),
            messages=list(values.get("messages", [])),
            artifact_paths=list(values.get("artifact_paths", [])),
            finalized=bool(values.get("finalized", False)),
            cancelled=bool(values.get("cancelled", False)),
            rerun_requested=bool(values.get("rerun_requested", False)),
            rerun_user_text=values.get("rerun_user_text"),
            final_report_json_path=values.get("final_report_json_path"),
            final_report_md_path=values.get("final_report_md_path"),
            message="Report interaction session initialized.",
        )

    def continue_report_interaction(
        self,
        *,
        thread_id: str,
        user_message: str,
        previous_assistant_count: int,
    ) -> ReportInteractionUpdate:
        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            payload_source="workflow_runtime_bridge_continue_report_interaction",
        )
        logger.info("Continuing report interaction graph session.")

        raw_message = user_message.strip()
        logger.info(
            "Passing raw user message into report graph.",
            extra={
                "payload_source": "workflow_runtime_bridge_pass_raw_report_message",
                "user_message": raw_message,
            },
        )

        config = report_graph_config(thread_id)
        self._report_graph.invoke(
            Command(resume={"message": raw_message}),
            config=config,
        )

        snapshot = self._report_graph.get_state(config)
        values = dict(snapshot.values)

        assistant_messages = self._extract_new_assistant_messages(
            values=values,
            previous_assistant_count=previous_assistant_count,
        )

        target_name = str(values.get("target_name", ""))

        return ReportInteractionUpdate(
            thread_id=thread_id,
            target_name=target_name,
            assistant_messages=assistant_messages,
            assistant_message_count=self._count_assistant_messages(values),
            current_markdown=str(values.get("final_report_markdown", "") or ""),
            messages=list(values.get("messages", [])),
            artifact_paths=list(values.get("artifact_paths", [])),
            finalized=bool(values.get("finalized", False)),
            cancelled=bool(values.get("cancelled", False)),
            rerun_requested=bool(values.get("rerun_requested", False)),
            rerun_user_text=values.get("rerun_user_text"),
            final_report_json_path=values.get("final_report_json_path"),
            final_report_md_path=values.get("final_report_md_path"),
            message="Report interaction session updated.",
        )

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
        thread_id = str(final_report_payload["summary"]["thread_id"])
        target_name = str(final_report_payload["summary"]["target_name"])

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="workflow_runtime_bridge_persist_finalized",
        )
        logger.info("Persisting finalized workflow run to SQLite.")

        sqlite_path = str(getattr(self._settings, "sqlite_path", "./data/runs.sqlite3"))

        _persist_final_report_to_sqlite(
            sqlite_path=sqlite_path,
            final_report_payload=final_report_payload,
            finalized_final_report_json_path=finalized_final_report_json_path,
            finalized_final_report_md_path=finalized_final_report_md_path,
            execution_batch_result=execution_batch_result,
            validation_batch_result=validation_batch_result,
            messages=messages,
            logger=logger,
        )

    def _create_checkpointer(self):
        mode = str(getattr(self._settings, "langgraph_checkpointer", "memory")).strip().lower()
        if mode == "sqlite":
            raw_sqlite_path = getattr(self._settings, "langgraph_sqlite_path", None)
            sqlite_path = str(raw_sqlite_path or "./data/langgraph.sqlite3")
            Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(sqlite_path, check_same_thread=False)
            return SqliteSaver(connection)
        return InMemorySaver()

    def _extract_new_assistant_messages(
        self,
        *,
        values: dict[str, Any],
        previous_assistant_count: int,
    ) -> list[str]:
        messages = list(values.get("messages", []))
        assistant_messages = [
            str(msg.get("content", ""))
            for msg in messages
            if str(msg.get("role", "")).lower() == "assistant"
        ]
        return assistant_messages[previous_assistant_count:]

    def _count_assistant_messages(self, values: dict[str, Any]) -> int:
        return len(
            [
                msg
                for msg in list(values.get("messages", []))
                if str(msg.get("role", "")).lower() == "assistant"
            ]
        )