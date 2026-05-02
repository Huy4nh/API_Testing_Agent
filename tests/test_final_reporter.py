from pathlib import Path

from api_testing_agent.core.reporter.final.final_reporter import FinalWorkflowReporter


def test_final_reporter_writes_staged_json_and_md(tmp_path: Path):
    reporter = FinalWorkflowReporter(output_dir=str(tmp_path))

    review_payload = {
        "thread_id": "thread-001",
        "target_name": "img_api_staging",
        "canonical_command": "test target img_api_staging module img yt",
        "understanding_explanation": "resolved img + yt scope",
        "draft_report_json_path": "reports/testcase_drafts/img_api_staging/thread-001/round_02.json",
        "draft_report_md_path": "reports/testcase_drafts/img_api_staging/thread-001/round_02.md",
        "execution_report_json_path": "reports/execution_runs/img_api_staging/thread-001/execution_batch.json",
        "execution_report_md_path": "reports/execution_runs/img_api_staging/thread-001/execution_batch.md",
        "validation_report_json_path": "reports/validation_runs/img_api_staging/thread-001/validation_batch.json",
        "validation_report_md_path": "reports/validation_runs/img_api_staging/thread-001/validation_batch.md",
    }

    execution_batch_result = {
        "thread_id": "thread-001",
        "target_name": "img_api_staging",
        "total_cases": 10,
        "executed_cases": 6,
        "skipped_cases": 4,
        "results": [
            {
                "testcase_id": "yt_case_01",
                "logical_case_name": "YT positive",
                "operation_id": "yt_get_content_YT_post",
                "method": "POST",
                "path": "/YT",
                "test_type": "positive",
                "expected_statuses": [200],
                "actual_status": 500,
                "response_time_ms": 9515.29,
                "skip": False,
                "skip_reason": None,
                "network_error": None,
            }
        ],
    }

    validation_batch_result = {
        "thread_id": "thread-001",
        "pass_cases": 5,
        "fail_cases": 1,
        "skip_cases": 4,
        "error_cases": 0,
        "results": [
            {
                "testcase_id": "yt_case_01",
                "verdict": "fail",
                "summary_message": "Validation failed on: status.",
                "issues": [
                    {"code": "status_mismatch", "message": "Expected status in [200], got 500."}
                ],
            }
        ],
    }

    report = reporter.write_staged(
        review_payload=review_payload,
        execution_batch_result=execution_batch_result,
        validation_batch_result=validation_batch_result,
        original_request="hãy test chức năng sinh ảnh của img",
        review_trace={
            "candidate_targets": ["img_local", "img_api_staging", "img_api_prod"],
            "target_selection_question": "Bạn muốn test trên local, staging hay production?",
            "feedback_history": ["thêm cả yt vào nũa"],
        },
    )

    assert report.summary.thread_id == "thread-001"
    assert report.summary.target_name == "img_api_staging"
    assert report.summary.report_stage == "staged"
    assert Path(str(report.links.final_report_json_path)).exists()
    assert Path(str(report.links.final_report_md_path)).exists()
    assert report.summary.fail_cases == 1
    assert len(report.notable_findings) >= 1