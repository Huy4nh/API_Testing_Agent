from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api_testing_agent.core.validation_models import ValidationBatchResult
from api_testing_agent.core.validator import Validator

try:
    from api_testing_agent.logging_config import bind_logger as _project_bind_logger
    from api_testing_agent.logging_config import get_logger as _project_get_logger
except Exception:  # pragma: no cover
    _project_bind_logger = None
    _project_get_logger = None


def get_logger(name: str) -> Any:
    if _project_get_logger is not None:
        return _project_get_logger(name)
    return logging.getLogger(name)


def bind_logger(logger: Any, **context: Any) -> Any:
    if _project_bind_logger is not None:
        return _project_bind_logger(logger, **context)
    return logger


LOGGER = get_logger(__name__)


def load_execution_batch_report(path: str | Path) -> dict[str, Any]:
    report_path = Path(path)
    logger = bind_logger(LOGGER, report_path=str(report_path))
    logger.info("Loading execution batch report.")

    if not report_path.exists():
        raise FileNotFoundError(f"Execution report not found: {report_path}")

    content = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError("Execution report JSON root must be an object.")

    return content


def validate_execution_batch_result(execution_batch_result: Any) -> ValidationBatchResult:
    logger = bind_logger(LOGGER)
    logger.info("Validating execution batch result.")

    validator = Validator()
    validation_batch = validator.validate_batch(execution_batch_result)

    logger.info(
        "Validation batch completed.",
        extra={
            "total_cases": validation_batch.total_cases,
            "pass_cases": validation_batch.pass_cases,
            "fail_cases": validation_batch.fail_cases,
            "skip_cases": validation_batch.skip_cases,
            "error_cases": validation_batch.error_cases,
        },
    )
    return validation_batch


def write_validation_json_report(
    validation_batch_result: ValidationBatchResult,
    output_dir: str | Path,
) -> Path:
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    thread_part = validation_batch_result.thread_id or "no_thread"
    file_path = report_dir / f"validation_{timestamp}_{thread_part}.json"

    file_path.write_text(
        json.dumps(validation_batch_result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return file_path


def write_validation_markdown_report(
    validation_batch_result: ValidationBatchResult,
    output_dir: str | Path,
) -> Path:
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    thread_part = validation_batch_result.thread_id or "no_thread"
    file_path = report_dir / f"validation_{timestamp}_{thread_part}.md"

    lines: list[str] = []
    lines.append("# Validation Report")
    lines.append("")
    lines.append(f"- Generated at: `{validation_batch_result.generated_at}`")
    lines.append(f"- Thread ID: `{validation_batch_result.thread_id}`")
    lines.append(f"- Target: `{validation_batch_result.target_name}`")
    lines.append(f"- Total cases: `{validation_batch_result.total_cases}`")
    lines.append(f"- Validated cases: `{validation_batch_result.validated_cases}`")
    lines.append(f"- Pass: `{validation_batch_result.pass_cases}`")
    lines.append(f"- Fail: `{validation_batch_result.fail_cases}`")
    lines.append(f"- Skip: `{validation_batch_result.skip_cases}`")
    lines.append(f"- Error: `{validation_batch_result.error_cases}`")
    lines.append("")

    for index, case in enumerate(validation_batch_result.results, start=1):
        lines.append(f"## {index}. {case.method or 'UNKNOWN'} {case.path or ''}".rstrip())
        lines.append(f"- Testcase ID: `{case.testcase_id}`")
        lines.append(f"- Logical name: `{case.logical_case_name}`")
        lines.append(f"- Operation ID: `{case.operation_id}`")
        lines.append(f"- Test type: `{case.test_type}`")
        lines.append(f"- Verdict: `{case.verdict.value}`")
        lines.append(f"- Summary: {case.summary_message}")
        lines.append(f"- Actual status: `{case.actual_status}`")
        lines.append(f"- Expected statuses: `{case.expected_statuses}`")
        lines.append(f"- Status check: `{case.status_check_passed}`")
        lines.append(f"- Schema check: `{case.schema_check_passed}`")
        lines.append(f"- Required fields check: `{case.required_fields_check_passed}`")
        lines.append(f"- Missing required fields: `{case.missing_required_fields}`")
        lines.append(f"- Final URL: `{case.final_url}`")
        lines.append(f"- Response time ms: `{case.response_time_ms}`")

        if case.issues:
            lines.append("- Issues:")
            for issue in case.issues:
                lines.append(f"  - [{issue.level}] {issue.code}: {issue.message}")

        lines.append("")

    file_path.write_text("\n".join(lines), encoding="utf-8")
    return file_path


def run_validation_from_execution_report(
    execution_report_path: str | Path,
    output_dir: str | Path,
) -> ValidationBatchResult:
    logger = bind_logger(
        LOGGER,
        execution_report_path=str(execution_report_path),
        output_dir=str(output_dir),
    )
    logger.info("Running validation from execution report file.")

    execution_batch_result = load_execution_batch_report(execution_report_path)
    validation_batch_result = validate_execution_batch_result(execution_batch_result)

    json_path = write_validation_json_report(validation_batch_result, output_dir)
    md_path = write_validation_markdown_report(validation_batch_result, output_dir)

    logger.info(
        "Validation reports generated.",
        extra={
            "validation_json_report": str(json_path),
            "validation_markdown_report": str(md_path),
        },
    )
    return validation_batch_result


def main() -> None:
    parser = argparse.ArgumentParser(description="Manual validation workflow test.")
    parser.add_argument(
        "--execution-report",
        required=True,
        help="Path to execution batch JSON report.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/validation",
        help="Directory to write validation reports.",
    )
    args = parser.parse_args()

    validation_batch_result = run_validation_from_execution_report(
        execution_report_path=args.execution_report,
        output_dir=args.output_dir,
    )

    print("=" * 80)
    print("VALIDATION DONE")
    print("Thread ID:", validation_batch_result.thread_id)
    print("Target:", validation_batch_result.target_name)
    print("Total:", validation_batch_result.total_cases)
    print("Validated:", validation_batch_result.validated_cases)
    print("Pass:", validation_batch_result.pass_cases)
    print("Fail:", validation_batch_result.fail_cases)
    print("Skip:", validation_batch_result.skip_cases)
    print("Error:", validation_batch_result.error_cases)


if __name__ == "__main__":
    main()