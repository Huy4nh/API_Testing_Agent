from __future__ import annotations

from datetime import datetime
from typing import Any

from api_testing_agent.core.reporter.final.final_report_models import FinalWorkflowReport
from api_testing_agent.db.sqlite_store import SQLiteStore
from api_testing_agent.logging_config import bind_logger, get_logger


class PersistenceService:
    def __init__(self, store: SQLiteStore) -> None:
        self._store = store
        self._logger = get_logger(__name__)

    def persist_final_workflow_report(
        self,
        *,
        final_report: FinalWorkflowReport,
        execution_batch_result: Any,
        validation_batch_result: Any,
        messages: list[dict[str, str]] | None = None,
    ) -> None:
        summary = final_report.summary
        links = final_report.links

        logger = bind_logger(
            self._logger,
            thread_id=summary.thread_id,
            target_name=summary.target_name,
            payload_source="persist_final_workflow_report",
        )
        logger.info("Persisting finalized workflow report into SQLite.")

        self._store.upsert_workflow_run(
            {
                "thread_id": summary.thread_id,
                "run_id": summary.run_id,
                "target_name": summary.target_name,
                "original_request": summary.original_request,
                "canonical_command": summary.canonical_command,
                "understanding_explanation": summary.understanding_explanation,
                "workflow_status": summary.report_stage,
                "draft_report_json_path": links.draft_report_json_path,
                "draft_report_md_path": links.draft_report_md_path,
                "execution_report_json_path": links.execution_report_json_path,
                "execution_report_md_path": links.execution_report_md_path,
                "validation_report_json_path": links.validation_report_json_path,
                "validation_report_md_path": links.validation_report_md_path,
                "final_report_json_path": links.final_report_json_path,
                "final_report_md_path": links.final_report_md_path,
                "total_cases": summary.total_cases,
                "executed_cases": summary.executed_cases,
                "skipped_cases": summary.skipped_cases,
                "pass_cases": summary.pass_cases,
                "fail_cases": summary.fail_cases,
                "skip_cases_validation": summary.skip_cases_validation,
                "error_cases": summary.error_cases,
                "created_at": summary.generated_at,
            }
        )

        self._store.replace_execution_results(
            thread_id=summary.thread_id,
            rows=list(_safe_get(execution_batch_result, "results", []) or []),
        )
        self._store.replace_validation_results(
            thread_id=summary.thread_id,
            rows=list(_safe_get(validation_batch_result, "results", []) or []),
        )

        for msg in list(messages or []):
            self._store.append_report_session_message(
                thread_id=summary.thread_id,
                role=str(msg.get("role", "unknown")),
                content=str(msg.get("content", "")),
                created_at=datetime.utcnow().isoformat(timespec="seconds"),
            )

        logger.info("Final workflow report persisted successfully.")


def _safe_get(source: Any, key: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)