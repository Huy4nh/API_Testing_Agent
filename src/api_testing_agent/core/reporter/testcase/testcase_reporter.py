from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api_testing_agent.logging_config import bind_logger, get_logger


@dataclass(frozen=True)
class TestcaseDraftReport:
    thread_id: str
    target_name: str
    round_number: int
    markdown_path: str
    json_path: str
    preview_text: str


class TestcaseDraftReporter:
    def __init__(self, output_dir: str, subdir: str = "testcase_drafts") -> None:
        self._root_dir = Path(output_dir) / subdir
        self._root_dir.mkdir(parents=True, exist_ok=True)
        self._logger = get_logger(__name__)

        self._logger.info(
            f"Initialized TestcaseDraftReporter at root_dir={self._root_dir}.",
            extra={"payload_source": "testcase_reporter_init"},
        )

    def write(
        self,
        *,
        thread_id: str,
        target_name: str,
        round_number: int,
        original_user_text: str,
        canonical_command: str,
        understanding_explanation: str | None,
        draft_groups: list[dict[str, Any]],
        feedback_history: list[str],
        plan: dict[str, Any],
        operation_contexts: list[dict[str, Any]],
        scope_note: str | None = None,
    ) -> TestcaseDraftReport:
        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="testcase_reporter_write",
        )
        logger.info(f"Writing testcase draft report for round={round_number}")

        preview_text = self.build_preview_text(
            round_number=round_number,
            original_user_text=original_user_text,
            canonical_command=canonical_command,
            understanding_explanation=understanding_explanation,
            draft_groups=draft_groups,
            feedback_history=feedback_history,
            scope_note=scope_note,
            operation_contexts=operation_contexts,
        )

        thread_dir = self._root_dir / target_name / thread_id
        thread_dir.mkdir(parents=True, exist_ok=True)

        base_name = f"round_{round_number:02d}"
        json_path = thread_dir / f"{base_name}.json"
        md_path = thread_dir / f"{base_name}.md"

        payload = {
            "thread_id": thread_id,
            "target_name": target_name,
            "round_number": round_number,
            "original_user_text": original_user_text,
            "canonical_command": canonical_command,
            "understanding_explanation": understanding_explanation,
            "feedback_history": feedback_history,
            "scope_note": scope_note,
            "plan": plan,
            "operation_contexts": operation_contexts,
            "draft_groups": draft_groups,
            "preview_text": preview_text,
        }

        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        md_path.write_text(
            self._build_markdown(
                thread_id=thread_id,
                target_name=target_name,
                round_number=round_number,
                original_user_text=original_user_text,
                canonical_command=canonical_command,
                understanding_explanation=understanding_explanation,
                draft_groups=draft_groups,
                feedback_history=feedback_history,
                plan=plan,
                scope_note=scope_note,
                operation_contexts=operation_contexts,
            ),
            encoding="utf-8",
        )

        logger.info(f"Testcase draft report written successfully. json_path={json_path}, md_path={md_path}")

        return TestcaseDraftReport(
            thread_id=thread_id,
            target_name=target_name,
            round_number=round_number,
            markdown_path=str(md_path),
            json_path=str(json_path),
            preview_text=preview_text,
        )

    def build_preview_text(
        self,
        *,
        round_number: int,
        original_user_text: str,
        canonical_command: str,
        understanding_explanation: str | None,
        draft_groups: list[dict[str, Any]],
        feedback_history: list[str],
        scope_note: str | None = None,
        operation_contexts: list[dict[str, Any]] | None = None,
    ) -> str:
        lines: list[str] = []
        lines.append(f"Review round: {round_number}")
        lines.append(f"Original request: {original_user_text}")
        lines.append(f"Canonical command: {canonical_command}")

        if understanding_explanation:
            lines.append(f"Understanding: {understanding_explanation}")

        if scope_note:
            lines.append(f"Scope note: {scope_note}")

        if operation_contexts is not None:
            lines.append(f"Active operations: {self._describe_active_operations(operation_contexts)}")

        lines.append("")

        if feedback_history:
            lines.append("Feedback history:")
            for index, item in enumerate(feedback_history, start=1):
                lines.append(f"- {index}. {item}")
            lines.append("")

        if not draft_groups:
            lines.append("Không có testcase draft nào được sinh ra.")
            return "\n".join(lines)

        for group_index, group in enumerate(draft_groups, start=1):
            method = group.get("method", "")
            path = group.get("path", "")
            operation_id = group.get("operation_id", "")

            lines.append(f"{group_index}. {method} {path} (operation_id={operation_id})")

            cases = group.get("cases", [])
            if not cases:
                lines.append("   - Không có case")
                lines.append("")
                continue

            for case_index, case in enumerate(cases, start=1):
                test_type = case.get("test_type", "")
                description = case.get("description", "")
                reasoning = case.get("reasoning_summary", "")
                expected_statuses = case.get("expected_status_codes", [])
                skip = bool(case.get("skip", False))
                skip_reason = case.get("skip_reason", "")

                lines.append(f"   {case_index}. [{test_type}] {description}")

                if reasoning:
                    lines.append(f"      why: {reasoning}")

                if expected_statuses:
                    lines.append(f"      expect: {expected_statuses}")

                if skip:
                    lines.append("      skip: true")
                    if skip_reason:
                        lines.append(f"      skip_reason: {skip_reason}")

            lines.append("")

        return "\n".join(lines)

    def _build_markdown(
        self,
        *,
        thread_id: str,
        target_name: str,
        round_number: int,
        original_user_text: str,
        canonical_command: str,
        understanding_explanation: str | None,
        draft_groups: list[dict[str, Any]],
        feedback_history: list[str],
        plan: dict[str, Any],
        scope_note: str | None = None,
        operation_contexts: list[dict[str, Any]] | None = None,
    ) -> str:
        lines: list[str] = []
        lines.append("# Testcase Draft Report")
        lines.append("")
        lines.append(f"- Thread ID: `{thread_id}`")
        lines.append(f"- Target: `{target_name}`")
        lines.append(f"- Review round: `{round_number}`")
        lines.append(f"- Original request: `{original_user_text}`")
        lines.append(f"- Canonical command: `{canonical_command}`")
        if understanding_explanation:
            lines.append(f"- Understanding: {understanding_explanation}")
        if scope_note:
            lines.append(f"- Scope note: {scope_note}")
        if operation_contexts is not None:
            lines.append(f"- Active operations: {self._describe_active_operations(operation_contexts)}")
        lines.append(f"- Requested test types: `{plan.get('test_types', [])}`")
        lines.append(f"- Ignore fields: `{plan.get('ignore_fields', [])}`")
        lines.append("")

        if feedback_history:
            lines.append("## Feedback History")
            lines.append("")
            for index, item in enumerate(feedback_history, start=1):
                lines.append(f"{index}. {item}")
            lines.append("")

        for group_index, group in enumerate(draft_groups, start=1):
            method = group.get("method", "")
            path = group.get("path", "")
            operation_id = group.get("operation_id", "")

            lines.append(f"## {group_index}. {method} {path}")
            lines.append("")
            lines.append(f"- Operation ID: `{operation_id}`")
            lines.append("")

            cases = group.get("cases", [])
            if not cases:
                lines.append("- Không có testcase draft nào.")
                lines.append("")
                continue

            for case_index, case in enumerate(cases, start=1):
                lines.append(f"### Case {case_index}")
                lines.append("")
                lines.append(f"- Test type: `{case.get('test_type', '')}`")
                lines.append(f"- Description: {case.get('description', '')}")
                lines.append(f"- Reasoning: {case.get('reasoning_summary', '')}")
                lines.append(f"- Expected statuses: `{case.get('expected_status_codes', [])}`")
                lines.append(f"- Skip: `{case.get('skip', False)}`")

                skip_reason = case.get("skip_reason")
                if skip_reason:
                    lines.append(f"- Skip reason: {skip_reason}")

                if case.get("path_params"):
                    lines.append(f"- Path params: `{case.get('path_params')}`")
                if case.get("query_params"):
                    lines.append(f"- Query params: `{case.get('query_params')}`")
                if case.get("headers"):
                    lines.append(f"- Headers: `{case.get('headers')}`")
                if case.get("json_body") is not None:
                    lines.append(f"- JSON body: `{case.get('json_body')}`")

                lines.append("")

        return "\n".join(lines)

    def _describe_active_operations(self, operation_contexts: list[dict[str, Any]]) -> str:
        labels: list[str] = []
        seen: set[tuple[str, str]] = set()

        for item in operation_contexts:
            method = str(item.get("method", "")).upper()
            path = str(item.get("path", ""))
            key = (method, path)

            if key in seen:
                continue

            seen.add(key)
            labels.append(f"{method} {path}")

        return ", ".join(labels) if labels else "(none)"