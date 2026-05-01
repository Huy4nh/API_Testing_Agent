from pathlib import Path

from api_testing_agent.core.reporter.validation.validation_reporter import ValidationReporter
from api_testing_agent.core.validation_models import (
    ValidationBatchResult,
    ValidationCaseResult,
    ValidationIssue,
    ValidationVerdict,
)


def test_validation_reporter_writes_json_and_markdown(tmp_path: Path):
    reporter = ValidationReporter(output_dir=str(tmp_path))

    batch = ValidationBatchResult(
        thread_id="thread-123",
        target_name="img_local",
        total_cases=2,
        validated_cases=2,
        pass_cases=1,
        fail_cases=1,
        skip_cases=0,
        error_cases=0,
        results=[
            ValidationCaseResult(
                testcase_id="case-pass",
                method="GET",
                path="/posts",
                verdict=ValidationVerdict.PASS,
                summary_message="Validation passed.",
                expected_statuses=[200],
                actual_status=200,
                status_check_passed=True,
                schema_check_passed=True,
                required_fields_check_passed=True,
            ),
            ValidationCaseResult(
                testcase_id="case-fail",
                method="GET",
                path="/bad",
                verdict=ValidationVerdict.FAIL,
                summary_message="Validation failed on: status.",
                expected_statuses=[200],
                actual_status=500,
                status_check_passed=False,
                schema_check_passed=None,
                required_fields_check_passed=None,
                issues=[
                    ValidationIssue(
                        code="status_mismatch",
                        message="Expected status in [200], got 500.",
                    )
                ],
            ),
        ],
    )

    artifacts = reporter.write_batch_result(batch)

    json_path = Path(artifacts.json_path)
    md_path = Path(artifacts.md_path)

    assert json_path.exists()
    assert md_path.exists()

    json_text = json_path.read_text(encoding="utf-8")
    md_text = md_path.read_text(encoding="utf-8")

    assert "thread-123" in json_text
    assert "img_local" in json_text
    assert "Validation Report" in md_text
    assert "case-pass" in md_text
    assert "case-fail" in md_text