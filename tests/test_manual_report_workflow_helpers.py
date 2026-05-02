import sqlite3
from pathlib import Path

from api_testing_agent.manual_test.report_testcase.manual_review_workflow_test import (
    _build_final_report_payload,
    _persist_final_report_to_sqlite,
)


class DummyExecutionCase:
    def __init__(
        self,
        *,
        testcase_id: str,
        logical_case_name: str,
        target_name: str,
        operation_id: str,
        method: str,
        path: str,
        test_type: str,
        expected_statuses: list[int],
        actual_status: int | None,
        response_time_ms: float | None,
        skip: bool = False,
        skip_reason: str | None = None,
        network_error: str | None = None,
        response_json: object | None = None,
        planner_reason: str | None = None,
        planner_confidence: float | None = None,
        payload_source: str | None = None,
    ) -> None:
        self.testcase_id = testcase_id
        self.logical_case_name = logical_case_name
        self.target_name = target_name
        self.operation_id = operation_id
        self.method = method
        self.path = path
        self.test_type = test_type
        self.expected_statuses = expected_statuses
        self.actual_status = actual_status
        self.response_time_ms = response_time_ms
        self.skip = skip
        self.skip_reason = skip_reason
        self.network_error = network_error
        self.response_json = response_json
        self.response_text = None
        self.response_headers = None
        self.final_headers = {}
        self.final_query_params = {}
        self.final_json_body = None
        self.final_url = f"https://example.com{path}"
        self.executed_at = "2026-05-02T12:00:00"
        self.planner_reason = planner_reason
        self.planner_confidence = planner_confidence
        self.payload_source = payload_source


class DummyExecutionBatch:
    def __init__(self) -> None:
        self.thread_id = "thread-001"
        self.target_name = "img_api_staging"
        self.total_cases = 2
        self.executed_cases = 1
        self.skipped_cases = 1
        self.results = [
            DummyExecutionCase(
                testcase_id="tc-1",
                logical_case_name="positive YT",
                target_name="img_api_staging",
                operation_id="yt_post",
                method="POST",
                path="/YT",
                test_type="positive",
                expected_statuses=[200],
                actual_status=500,
                response_time_ms=9000.0,
                response_json={"detail": "server error"},
                planner_reason="deterministic",
                planner_confidence=0.85,
                payload_source="planner",
            )
        ]


class DummyVerdict:
    def __init__(self, value: str) -> None:
        self.value = value


class DummyIssue:
    def __init__(
        self,
        *,
        level: str,
        code: str,
        message: str,
        field: str | None = None,
    ) -> None:
        self.level = level
        self.code = code
        self.message = message
        self.field = field


class DummyValidationCase:
    def __init__(self) -> None:
        self.testcase_id = "tc-1"
        self.logical_case_name = "positive YT"
        self.operation_id = "yt_post"
        self.method = "POST"
        self.path = "/YT"
        self.verdict = DummyVerdict("fail")
        self.summary_message = "Expected status in [200], got 500."
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
                level="warning",
                code="status_mismatch",
                message="Expected status in [200], got 500.",
            )
        ]


class DummyValidationBatch:
    def __init__(self) -> None:
        self.thread_id = "thread-001"
        self.target_name = "img_api_staging"
        self.total_cases = 2
        self.validated_cases = 2
        self.pass_cases = 0
        self.fail_cases = 1
        self.skip_cases = 1
        self.error_cases = 0
        self.results = [DummyValidationCase()]


def test_build_final_report_payload():
    approved_payload = {
        "thread_id": "thread-001",
        "target_name": "img_api_staging",
        "canonical_command": "test target img_api_staging module img yt",
        "understanding_explanation": "resolved img + yt scope",
        "draft_report_json_path": "draft.json",
        "draft_report_md_path": "draft.md",
    }

    execution_batch = DummyExecutionBatch()
    validation_batch = DummyValidationBatch()

    payload = _build_final_report_payload(
        approved_payload=approved_payload,
        execution_batch_result=execution_batch,
        execution_report_paths={"json_path": "execution.json", "md_path": "execution.md"},
        validation_batch_result=validation_batch,
        validation_report_paths={"json_path": "validation.json", "md_path": "validation.md"},
        original_request="hãy test chức năng sinh ảnh của img",
        candidate_targets_history=["img_local", "img_api_staging", "img_api_prod"],
        target_selection_question="Bạn muốn test trên local, staging hay production?",
        review_feedback_history=["thêm cả yt vào nũa"],
    )

    assert payload["summary"]["thread_id"] == "thread-001"
    assert payload["summary"]["target_name"] == "img_api_staging"
    assert payload["summary"]["fail_cases"] == 1
    assert payload["summary"]["skip_cases_validation"] == 1
    assert len(payload["case_summaries"]) == 1
    assert len(payload["notable_findings"]) >= 2


def test_persist_final_report_to_sqlite(tmp_path: Path):
    sqlite_path = tmp_path / "runtime.sqlite3"

    approved_payload = {
        "thread_id": "thread-001",
        "target_name": "img_api_staging",
        "canonical_command": "test target img_api_staging module img yt",
        "understanding_explanation": "resolved img + yt scope",
        "draft_report_json_path": "draft.json",
        "draft_report_md_path": "draft.md",
    }

    execution_batch = DummyExecutionBatch()
    validation_batch = DummyValidationBatch()

    payload = _build_final_report_payload(
        approved_payload=approved_payload,
        execution_batch_result=execution_batch,
        execution_report_paths={"json_path": "execution.json", "md_path": "execution.md"},
        validation_batch_result=validation_batch,
        validation_report_paths={"json_path": "validation.json", "md_path": "validation.md"},
        original_request="hãy test chức năng sinh ảnh của img",
        candidate_targets_history=["img_local", "img_api_staging", "img_api_prod"],
        target_selection_question="Bạn muốn test trên local, staging hay production?",
        review_feedback_history=["thêm cả yt vào nũa"],
    )

    payload["links"]["final_report_json_path"] = "final.json"
    payload["links"]["final_report_md_path"] = "final.md"

    class DummyLogger:
        def info(self, *args, **kwargs):
            return None

    _persist_final_report_to_sqlite(
        sqlite_path=str(sqlite_path),
        final_report_payload=payload,
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