import sqlite3
from pathlib import Path

from api_testing_agent.manual_test.report_testcase.manual_review_workflow_test import (
    _build_final_report_payload,
    _persist_final_report_to_sqlite,
)


class DummyExecutionCase:
    def __init__(self, *, testcase_id: str, path: str, actual_status: int | None, verdict_name: str | None = None):
        self.testcase_id = testcase_id
        self.logical_case_name = "demo case"
        self.target_name = "img_api_staging"
        self.operation_id = "op_demo"
        self.method = "POST"
        self.path = path
        self.test_type = "positive"
        self.expected_statuses = [200]
        self.actual_status = actual_status
        self.response_time_ms = 100.0
        self.skip = False
        self.skip_reason = None
        self.network_error = None
        self.response_json = None
        self.planner_reason = None
        self.planner_confidence = None
        self.payload_source = "planner"


class DummyExecutionBatch:
    def __init__(self):
        self.thread_id = "thread-001"
        self.target_name = "img_api_staging"
        self.total_cases = 1
        self.executed_cases = 1
        self.skipped_cases = 0
        self.results = [
            DummyExecutionCase(
                testcase_id="tc-1",
                path="/YT",
                actual_status=500,
            )
        ]


class DummyVerdict:
    def __init__(self, value: str):
        self.value = value


class DummyIssue:
    def __init__(self, *, level: str, code: str, message: str):
        self.level = level
        self.code = code
        self.message = message


class DummyValidationCase:
    def __init__(self):
        self.testcase_id = "tc-1"
        self.logical_case_name = "demo case"
        self.operation_id = "op_demo"
        self.method = "POST"
        self.path = "/YT"
        self.verdict = DummyVerdict("fail")
        self.summary_message = "Validation failed on: status."
        self.expected_statuses = [200]
        self.actual_status = 500
        self.status_check_passed = False
        self.schema_check_passed = None
        self.required_fields_check_passed = None
        self.expected_required_fields = []
        self.missing_required_fields = []
        self.network_error = None
        self.skip_reason = None
        self.issues = [
            DummyIssue(
                level="error",
                code="status_mismatch",
                message="Expected status in [200], got 500.",
            )
        ]


class DummyValidationBatch:
    def __init__(self):
        self.thread_id = "thread-001"
        self.target_name = "img_api_staging"
        self.total_cases = 1
        self.validated_cases = 1
        self.pass_cases = 0
        self.fail_cases = 1
        self.skip_cases = 0
        self.error_cases = 0
        self.results = [DummyValidationCase()]


class DummyLogger:
    def info(self, *args, **kwargs):
        return None


def test_finalize_then_persist(tmp_path: Path):
    sqlite_path = tmp_path / "runs.sqlite3"

    approved_payload = {
        "thread_id": "thread-001",
        "target_name": "img_api_staging",
        "canonical_command": "test target img_api_staging /YT POST",
        "understanding_explanation": "resolved YT scope",
        "draft_report_json_path": "draft.json",
        "draft_report_md_path": "draft.md",
        "execution_report_json_path": "execution.json",
        "execution_report_md_path": "execution.md",
        "validation_report_json_path": "validation.json",
        "validation_report_md_path": "validation.md",
    }

    execution_batch = DummyExecutionBatch()
    validation_batch = DummyValidationBatch()

    final_report_payload = _build_final_report_payload(
        approved_payload=approved_payload,
        execution_batch_result=execution_batch,
        execution_report_paths={"json_path": "execution.json", "md_path": "execution.md"},
        validation_batch_result=validation_batch,
        validation_report_paths={"json_path": "validation.json", "md_path": "validation.md"},
        original_request="hãy test yt",
        candidate_targets_history=["img_local", "img_api_staging"],
        target_selection_question="Bạn muốn test target nào?",
        review_feedback_history=["thêm yt vào"],
    )

    _persist_final_report_to_sqlite(
        sqlite_path=str(sqlite_path),
        final_report_payload=final_report_payload,
        finalized_final_report_json_path="final.json",
        finalized_final_report_md_path="final.md",
        execution_batch_result=execution_batch,
        validation_batch_result=validation_batch,
        messages=[],
        logger=DummyLogger(),
    )

    conn = sqlite3.connect(str(sqlite_path))
    workflow_count = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
    execution_count = conn.execute("SELECT COUNT(*) FROM execution_case_results").fetchone()[0]
    validation_count = conn.execute("SELECT COUNT(*) FROM validation_case_results").fetchone()[0]
    conn.close()

    assert workflow_count == 1
    assert execution_count == 1
    assert validation_count == 1


def test_cancel_means_no_persist(tmp_path: Path):
    sqlite_path = tmp_path / "runs.sqlite3"

    # Không gọi _persist_final_report_to_sqlite nghĩa là DB vẫn chưa có row nào
    conn = sqlite3.connect(str(sqlite_path))
    conn.execute(
        """
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
        """
    )
    conn.commit()

    workflow_count = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
    conn.close()

    assert workflow_count == 0