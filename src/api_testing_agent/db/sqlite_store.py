from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from api_testing_agent.logging_config import bind_logger, get_logger


class SQLiteStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._logger = get_logger(__name__)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _init_db(self) -> None:
        logger = bind_logger(self._logger, payload_source="sqlite_init_db")
        logger.info("Initializing SQLite schema.")

        with self._connect() as conn:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    thread_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    original_request TEXT,
                    canonical_command TEXT,
                    understanding_explanation TEXT,
                    workflow_status TEXT NOT NULL,
                    draft_report_json_path TEXT,
                    draft_report_md_path TEXT,
                    execution_report_json_path TEXT,
                    execution_report_md_path TEXT,
                    validation_report_json_path TEXT,
                    validation_report_md_path TEXT,
                    final_report_json_path TEXT,
                    final_report_md_path TEXT,
                    total_cases INTEGER NOT NULL DEFAULT 0,
                    executed_cases INTEGER NOT NULL DEFAULT 0,
                    skipped_cases INTEGER NOT NULL DEFAULT 0,
                    pass_cases INTEGER NOT NULL DEFAULT 0,
                    fail_cases INTEGER NOT NULL DEFAULT 0,
                    skip_cases_validation INTEGER NOT NULL DEFAULT 0,
                    error_cases INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS execution_case_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    testcase_id TEXT NOT NULL,
                    logical_case_name TEXT,
                    target_name TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    test_type TEXT,
                    actual_status INTEGER,
                    response_time_ms REAL,
                    skipped INTEGER NOT NULL DEFAULT 0,
                    skip_reason TEXT,
                    network_error TEXT,
                    response_json_json TEXT,
                    planner_reason TEXT,
                    planner_confidence REAL,
                    payload_source TEXT,
                    FOREIGN KEY(thread_id) REFERENCES workflow_runs(thread_id) ON DELETE CASCADE
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS validation_case_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    testcase_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    summary_message TEXT NOT NULL,
                    status_check_passed INTEGER,
                    schema_check_passed INTEGER,
                    required_fields_check_passed INTEGER,
                    issues_json TEXT NOT NULL,
                    validated_at TEXT,
                    FOREIGN KEY(thread_id) REFERENCES workflow_runs(thread_id) ON DELETE CASCADE
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS report_session_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(thread_id) REFERENCES workflow_runs(thread_id) ON DELETE CASCADE
                )
                '''
            )
            conn.commit()

        logger.info("SQLite schema initialized successfully.")

    def upsert_workflow_run(self, payload: dict[str, Any]) -> None:
        thread_id = str(payload["thread_id"])
        target_name = str(payload["target_name"])
        logger = bind_logger(self._logger, thread_id=thread_id, target_name=target_name, payload_source="sqlite_upsert_workflow_run")
        logger.info("Upserting workflow run.")

        with self._connect() as conn:
            conn.execute(
                '''
                INSERT INTO workflow_runs (
                    thread_id, run_id, target_name, original_request, canonical_command,
                    understanding_explanation, workflow_status,
                    draft_report_json_path, draft_report_md_path,
                    execution_report_json_path, execution_report_md_path,
                    validation_report_json_path, validation_report_md_path,
                    final_report_json_path, final_report_md_path,
                    total_cases, executed_cases, skipped_cases,
                    pass_cases, fail_cases, skip_cases_validation, error_cases, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    target_name=excluded.target_name,
                    original_request=excluded.original_request,
                    canonical_command=excluded.canonical_command,
                    understanding_explanation=excluded.understanding_explanation,
                    workflow_status=excluded.workflow_status,
                    draft_report_json_path=excluded.draft_report_json_path,
                    draft_report_md_path=excluded.draft_report_md_path,
                    execution_report_json_path=excluded.execution_report_json_path,
                    execution_report_md_path=excluded.execution_report_md_path,
                    validation_report_json_path=excluded.validation_report_json_path,
                    validation_report_md_path=excluded.validation_report_md_path,
                    final_report_json_path=excluded.final_report_json_path,
                    final_report_md_path=excluded.final_report_md_path,
                    total_cases=excluded.total_cases,
                    executed_cases=excluded.executed_cases,
                    skipped_cases=excluded.skipped_cases,
                    pass_cases=excluded.pass_cases,
                    fail_cases=excluded.fail_cases,
                    skip_cases_validation=excluded.skip_cases_validation,
                    error_cases=excluded.error_cases,
                    created_at=excluded.created_at
                ''',
                (
                    payload["thread_id"], payload["run_id"], payload["target_name"],
                    payload.get("original_request"), payload.get("canonical_command"), payload.get("understanding_explanation"),
                    payload.get("workflow_status", "finalized"),
                    payload.get("draft_report_json_path"), payload.get("draft_report_md_path"),
                    payload.get("execution_report_json_path"), payload.get("execution_report_md_path"),
                    payload.get("validation_report_json_path"), payload.get("validation_report_md_path"),
                    payload.get("final_report_json_path"), payload.get("final_report_md_path"),
                    int(payload.get("total_cases", 0) or 0),
                    int(payload.get("executed_cases", 0) or 0),
                    int(payload.get("skipped_cases", 0) or 0),
                    int(payload.get("pass_cases", 0) or 0),
                    int(payload.get("fail_cases", 0) or 0),
                    int(payload.get("skip_cases_validation", 0) or 0),
                    int(payload.get("error_cases", 0) or 0),
                    str(payload.get("created_at")),
                ),
            )
            conn.commit()

    def replace_execution_results(self, *, thread_id: str, rows: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM execution_case_results WHERE thread_id = ?", (thread_id,))
            conn.executemany(
                '''
                INSERT INTO execution_case_results (
                    thread_id, testcase_id, logical_case_name, target_name, operation_id, method, path,
                    test_type, actual_status, response_time_ms, skipped, skip_reason,
                    network_error, response_json_json, planner_reason, planner_confidence, payload_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    (
                        thread_id,
                        str(row.get("testcase_id", "")),
                        row.get("logical_case_name"),
                        str(row.get("target_name", "")),
                        str(row.get("operation_id", "")),
                        str(row.get("method", "")),
                        str(row.get("path", "")),
                        row.get("test_type"),
                        self._to_int_or_none(row.get("actual_status")),
                        self._to_float_or_none(row.get("response_time_ms")),
                        1 if bool(row.get("skip", False)) else 0,
                        row.get("skip_reason"),
                        row.get("network_error"),
                        self._to_json_or_none(row.get("response_json")),
                        row.get("planner_reason"),
                        self._to_float_or_none(row.get("planner_confidence")),
                        row.get("payload_source"),
                    )
                    for row in rows
                ],
            )
            conn.commit()

    def replace_validation_results(self, *, thread_id: str, rows: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM validation_case_results WHERE thread_id = ?", (thread_id,))
            conn.executemany(
                '''
                INSERT INTO validation_case_results (
                    thread_id, testcase_id, operation_id, method, path, verdict, summary_message,
                    status_check_passed, schema_check_passed, required_fields_check_passed, issues_json, validated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    (
                        thread_id,
                        str(row.get("testcase_id", "")),
                        str(row.get("operation_id", "")),
                        str(row.get("method", "")),
                        str(row.get("path", "")),
                        str(row.get("verdict", "")),
                        str(row.get("summary_message", "")),
                        self._bool_to_db(row.get("status_check_passed")),
                        self._bool_to_db(row.get("schema_check_passed")),
                        self._bool_to_db(row.get("required_fields_check_passed")),
                        json.dumps(row.get("issues", []), ensure_ascii=False),
                        row.get("validated_at"),
                    )
                    for row in rows
                ],
            )
            conn.commit()

    def append_report_session_message(self, *, thread_id: str, role: str, content: str, created_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO report_session_events (thread_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (thread_id, role, content, created_at),
            )
            conn.commit()

    def delete_all_by_thread_id(self, *, thread_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM workflow_runs WHERE thread_id = ?", (thread_id,))
            conn.commit()

    def _bool_to_db(self, value: Any) -> int | None:
        if value is None:
            return None
        return 1 if bool(value) else 0

    def _to_int_or_none(self, value: Any) -> int | None:
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None

    def _to_float_or_none(self, value: Any) -> float | None:
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    def _to_json_or_none(self, value: Any) -> str | None:
        return None if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True)