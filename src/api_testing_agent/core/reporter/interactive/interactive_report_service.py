from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping, Protocol

from api_testing_agent.core.report_context_builder import ReportContextBuilder
from api_testing_agent.logging_config import bind_logger, get_logger

from api_testing_agent.core.report_hybrid_ai import (
    ReportAnswerHybridAIProtocol,
    ReportRewriteHybridAIProtocol,
)

class InteractiveServiceHybridAIProtocol(
    ReportAnswerHybridAIProtocol,
    ReportRewriteHybridAIProtocol,
    Protocol,
):
    pass

class InteractiveReportService:
    def __init__(
        self,
        *,
        output_dir: str,
        context_builder: ReportContextBuilder | None = None,
        hybrid_ai: InteractiveServiceHybridAIProtocol | None = None,
    ) -> None:
        self._output_dir = Path(output_dir)
        self._builder = context_builder or ReportContextBuilder()
        self._hybrid_ai = hybrid_ai
        self._logger = get_logger(__name__)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def initialize_session(
        self,
        state: Mapping[str, Any],
    ) -> dict[str, Any]:
        thread_id = str(state.get("thread_id", ""))
        target_name = str(state.get("target_name", ""))

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="interactive_report_initialize_session",
        )
        logger.info("Initializing final-report interaction session.")

        context = self._builder.build_context(state=dict(state))
        markdown = str(state.get("final_report_markdown", "") or "")
        if not markdown:
            markdown = context["current_markdown"]

        shareable_summary = self._builder.build_shareable_summary(context)
        artifact_paths = self._collect_artifact_paths(state)

        assistant_response = (
            markdown
            + "\n\n"
            + "Bạn có thể hỏi giải thích report, yêu cầu tôi viết lại report, "
            + "yêu cầu sửa scope để chạy lại, hoặc nói `lưu` / `done` / `hủy`."
        )

        updates = {
            "final_report_markdown": markdown,
            "shareable_summary": shareable_summary,
            "assistant_response": assistant_response,
            "artifact_paths": artifact_paths,
            "pending_revision_instruction": None,
        }

        logger.info("Final-report interaction session initialized.")
        return updates

    def answer_question(
        self,
        state: Mapping[str, Any],
        user_message: str,
    ) -> dict[str, Any]:
        thread_id = str(state.get("thread_id", ""))
        target_name = str(state.get("target_name", ""))

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="interactive_report_answer_question",
        )
        logger.info("Answering question on final report.")

        context = self._builder.build_context(state=dict(state))

        if self._hybrid_ai is not None:
            try:
                answer = self._hybrid_ai.answer_report_question(
                    thread_id=thread_id,
                    target_name=target_name,
                    user_text=user_message,
                    final_report_data=dict(state.get("final_report_data", {}) or {}),
                    current_markdown=str(state.get("final_report_markdown", "") or ""),
                    messages=list(state.get("messages", []) or []),
                )
                return {"assistant_response": answer}
            except Exception as exc:
                logger.warning(f"Hybrid AI answer fallback failed: {exc}")

        answer = self._builder.build_answer(context=context, question=user_message)
        return {"assistant_response": answer}

    def revise_report_text(
        self,
        state: Mapping[str, Any],
        instruction: str,
    ) -> dict[str, Any]:
        thread_id = str(state.get("thread_id", ""))
        target_name = str(state.get("target_name", ""))

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="interactive_report_revise_text",
        )
        logger.info(f"Revising final report markdown with instruction={instruction!r}")

        context = self._builder.build_context(state=dict(state))

        revised_markdown: str
        if self._hybrid_ai is not None:
            try:
                revised_markdown = self._hybrid_ai.rewrite_report(
                    thread_id=thread_id,
                    target_name=target_name,
                    instruction=instruction,
                    final_report_data=dict(state.get("final_report_data", {}) or {}),
                    current_markdown=str(state.get("final_report_markdown", "") or ""),
                    messages=list(state.get("messages", []) or []),
                )
            except Exception as exc:
                logger.warning(f"Hybrid AI rewrite fallback failed: {exc}")
                revised_markdown = self._builder.revise_markdown(
                    context=context,
                    instruction=instruction,
                )
        else:
            revised_markdown = self._builder.revise_markdown(
                context=context,
                instruction=instruction,
            )

        return {
            "final_report_markdown": revised_markdown,
            "assistant_response": (
                "Tôi đã cập nhật cách trình bày final report.\n\n"
                + revised_markdown
            ),
            "pending_revision_instruction": instruction,
        }

    def share_report(self, state: Mapping[str, Any]) -> dict[str, Any]:
        context = self._builder.build_context(state=dict(state))
        shareable_summary = self._builder.build_shareable_summary(context)
        return {
            "shareable_summary": shareable_summary,
            "assistant_response": shareable_summary,
        }

    def build_rerun_request_text(
        self,
        state: Mapping[str, Any],
        instruction: str,
    ) -> str:
        canonical_command = self._safe_str(state.get("canonical_command"))
        original_request = self._safe_str(state.get("original_request"))

        base = canonical_command or original_request or "test lại theo điều chỉnh mới"
        return f"{base}\nĐiều chỉnh bổ sung từ user sau final report: {instruction}"

    def persist_session_snapshot(
        self,
        state: Mapping[str, Any],
    ) -> dict[str, Any]:
        thread_id = str(state.get("thread_id", ""))
        target_name = str(state.get("target_name", ""))

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="interactive_report_persist_snapshot",
        )
        logger.info("Persisting report interaction snapshot.")

        session_dir = self._session_dir(state)
        session_dir.mkdir(parents=True, exist_ok=True)

        json_path = session_dir / "interactive_session.json"
        md_path = session_dir / "interactive_session.md"

        payload = {
            "thread_id": thread_id,
            "target_name": target_name,
            "messages": list(state.get("messages", [])),
            "final_report_markdown": state.get("final_report_markdown", ""),
            "shareable_summary": state.get("shareable_summary"),
            "finalized": bool(state.get("finalized", False)),
            "cancelled": bool(state.get("cancelled", False)),
            "rerun_requested": bool(state.get("rerun_requested", False)),
            "rerun_user_text": state.get("rerun_user_text"),
            "staged_final_report_json_path": state.get("staged_final_report_json_path"),
            "staged_final_report_md_path": state.get("staged_final_report_md_path"),
            "final_report_json_path": state.get("final_report_json_path"),
            "final_report_md_path": state.get("final_report_md_path"),
        }
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        md_lines = [
            "# Report Interaction Session Snapshot",
            "",
            f"- Thread ID: `{thread_id}`",
            f"- Target: `{target_name}`",
            f"- Finalized: `{bool(state.get('finalized', False))}`",
            f"- Cancelled: `{bool(state.get('cancelled', False))}`",
            f"- Rerun requested: `{bool(state.get('rerun_requested', False))}`",
            "",
            "## Current Final Report",
            "",
            str(state.get("final_report_markdown", "")),
            "",
            "## Conversation",
            "",
        ]

        for msg in list(state.get("messages", [])):
            role = str(msg.get("role", "unknown")).upper()
            content = str(msg.get("content", ""))
            md_lines.append(f"### {role}")
            md_lines.append(content)
            md_lines.append("")

        md_path.write_text("\n".join(md_lines), encoding="utf-8")

        return {
            "artifact_paths": self._merge_artifact_paths(
                list(state.get("artifact_paths", [])),
                [str(json_path), str(md_path)],
            ),
        }

    def finalize_session(
        self,
        state: Mapping[str, Any],
    ) -> dict[str, Any]:
        thread_id = str(state.get("thread_id", ""))
        target_name = str(state.get("target_name", ""))

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="interactive_report_finalize",
        )
        logger.info("Finalizing report interaction session.")

        staged_json = Path(str(state.get("staged_final_report_json_path") or ""))
        staged_md = Path(str(state.get("staged_final_report_md_path") or ""))

        final_dir = self._output_dir / "final_runs" / target_name / thread_id
        final_dir.mkdir(parents=True, exist_ok=True)

        final_json = final_dir / "final_summary.json"
        final_md = final_dir / "final_summary.md"

        if staged_json.exists():
            final_json.write_text(staged_json.read_text(encoding="utf-8"), encoding="utf-8")
        if staged_md.exists():
            final_md.write_text(staged_md.read_text(encoding="utf-8"), encoding="utf-8")

        # Nếu user đã revise cách trình bày report thì patch lại file md cuối.
        current_markdown = str(state.get("final_report_markdown", "") or "")
        if current_markdown:
            final_md.write_text(current_markdown, encoding="utf-8")

        logger.info("Report interaction finalized successfully.")
        
        preferred_language = str(state.get("preferred_language", "vi")).strip().lower()

        assistant_response = (
            "I finalized the report. "
            f"The official files are located at `{final_json}` and `{final_md}`."
            if preferred_language == "en"
            else (
                "Tôi đã chốt final report. "
                f"File chính thức nằm tại `{final_json}` và `{final_md}`."
            )
        )

        return {
            "finalized": True,
            "final_report_json_path": str(final_json),
            "final_report_md_path": str(final_md),
            "assistant_response": assistant_response,
            "artifact_paths": self._merge_artifact_paths(
                list(state.get("artifact_paths", [])),
                [str(final_json), str(final_md)],
            ),
        }

    def cancel_session(
        self,
        state: Mapping[str, Any],
    ) -> dict[str, Any]:
        thread_id = str(state.get("thread_id", ""))
        target_name = str(state.get("target_name", ""))

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="interactive_report_cancel",
        )
        logger.info("Cancelling report interaction session and cleaning staging artifacts.")

        artifact_paths = list(state.get("artifact_paths", []))
        for raw_path in artifact_paths:
            self._delete_path_if_exists(Path(raw_path))

        # Xóa riêng thư mục staging final report nếu còn.
        staged_json = self._safe_str(state.get("staged_final_report_json_path"))
        staged_md = self._safe_str(state.get("staged_final_report_md_path"))
        if staged_json:
            self._delete_path_if_exists(Path(staged_json))
        if staged_md:
            self._delete_path_if_exists(Path(staged_md))

        session_dir = self._session_dir(state)
        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)

        logger.info("Report interaction session cancelled and staging artifacts cleaned up.")
        
        preferred_language = str(state.get("preferred_language", "vi")).strip().lower()

        assistant_response = (
            "I cancelled this report session and cleaned all tracked staging artifacts. "
            "No data was finalized or persisted."
            if preferred_language == "en"
            else (
                "Tôi đã hủy phiên report này và xóa toàn bộ artifact staging được theo dõi. "
                "Không có dữ liệu nào được finalize/persist."
            )
        )

        return {
            "cancelled": True,
            "artifact_paths": [],
            "assistant_response": assistant_response,
        }

    def _session_dir(self, state: Mapping[str, Any]) -> Path:
        target_name = str(state.get("target_name", "unknown_target"))
        thread_id = str(state.get("thread_id", "unknown_thread"))
        return self._output_dir / "_staging" / "report_sessions" / target_name / thread_id

    def _collect_artifact_paths(self, state: Mapping[str, Any]) -> list[str]:
        candidates = [
            self._safe_str(state.get("staged_final_report_json_path")),
            self._safe_str(state.get("staged_final_report_md_path")),
            self._safe_str(state.get("draft_report_json_path")),
            self._safe_str(state.get("draft_report_md_path")),
            self._safe_str(state.get("execution_report_json_path")),
            self._safe_str(state.get("execution_report_md_path")),
            self._safe_str(state.get("validation_report_json_path")),
            self._safe_str(state.get("validation_report_md_path")),
            *list(state.get("artifact_paths", [])),
        ]
        return self._merge_artifact_paths([], candidates)

    def _merge_artifact_paths(
        self,
        left: list[str],
        right: list[str],
    ) -> list[str]:
        seen: set[str] = set()
        merged: list[str] = []

        for item in [*left, *right]:
            cleaned = self._safe_str(item)
            if not cleaned:
                continue
            if cleaned in seen:
                continue
            seen.add(cleaned)
            merged.append(cleaned)

        return merged

    def _delete_path_if_exists(self, path: Path) -> None:
        try:
            if not path.exists():
                return

            if path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass

    def _safe_str(self, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)