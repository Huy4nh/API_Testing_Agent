from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api_testing_agent.core.validation_models import ValidationBatchResult

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


@dataclass(frozen=True)
class ValidationReportArtifacts:
    json_path: str
    md_path: str


class ValidationReporter:
    def __init__(self, output_dir: str) -> None:
        self._output_dir = Path(output_dir)
        self._logger = get_logger(__name__)

    def write_batch_result(
        self,
        validation_batch_result: ValidationBatchResult,
    ) -> ValidationReportArtifacts:
        target_name = validation_batch_result.target_name or "unknown_target"
        thread_id = validation_batch_result.thread_id or "unknown_thread"

        report_dir = self._output_dir / "validation_runs" / target_name / thread_id
        report_dir.mkdir(parents=True, exist_ok=True)

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="validation_reporter",
        )
        logger.info("Writing validation reports.")

        json_path = report_dir / "validation_batch.json"
        md_path = report_dir / "validation_batch.md"

        json_path.write_text(
            json.dumps(validation_batch_result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        md_path.write_text(
            self._build_markdown(validation_batch_result),
            encoding="utf-8",
        )

        logger.info(
            "Validation reports written.",
            extra={
                "validation_json_path": str(json_path),
                "validation_md_path": str(md_path),
            },
        )

        return ValidationReportArtifacts(
            json_path=str(json_path),
            md_path=str(md_path),
        )

    def _build_markdown(self, validation_batch_result: ValidationBatchResult) -> str:
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
            title = f"{case.method or 'UNKNOWN'} {case.path or ''}".rstrip()
            lines.append(f"## {index}. {title}")
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

        return "\n".join(lines)