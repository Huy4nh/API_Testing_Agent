from __future__ import annotations

from typing import Any

from api_testing_agent.logging_config import bind_logger, get_logger


class ReportContextBuilder:
    def __init__(self) -> None:
        self._logger = get_logger(__name__)

    def build_context(
        self,
        *,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        thread_id = str(state.get("thread_id", ""))
        target_name = str(state.get("target_name", ""))

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=target_name,
            payload_source="build_report_context",
        )
        logger.info("Building report interaction context.")

        final_report_data = dict(state.get("final_report_data", {}) or {})
        summary = dict(final_report_data.get("summary", {}) or {})
        case_summaries = list(final_report_data.get("case_summaries", []) or [])
        findings = list(final_report_data.get("notable_findings", []) or [])
        links = dict(final_report_data.get("links", {}) or {})

        context = {
            "thread_id": thread_id,
            "target_name": target_name,
            "summary": summary,
            "case_summaries": case_summaries,
            "notable_findings": findings,
            "links": links,
            "original_request": state.get("original_request"),
            "canonical_command": state.get("canonical_command"),
            "understanding_explanation": state.get("understanding_explanation"),
            "candidate_targets": list(state.get("candidate_targets", []) or []),
            "target_selection_question": state.get("target_selection_question"),
            "review_feedback_history": list(state.get("review_feedback_history", []) or []),
            "conversation_turns": len(list(state.get("messages", []) or [])),
            "current_markdown": state.get("final_report_markdown", ""),
        }

        logger.info("Report interaction context built successfully.")
        return context

    def build_shareable_summary(
        self,
        context: dict[str, Any],
    ) -> str:
        summary = context["summary"]
        return (
            f"Target `{summary.get('target_name') or context['target_name']}` "
            f"đã chạy {summary.get('total_cases', 0)} case. "
            f"Pass={summary.get('pass_cases', 0)}, "
            f"Fail={summary.get('fail_cases', 0)}, "
            f"Skip={summary.get('skip_cases_validation', 0)}, "
            f"Error={summary.get('error_cases', 0)}."
        )

    def build_answer(
        self,
        *,
        context: dict[str, Any],
        question: str,
    ) -> str:
        lowered = question.strip().lower()
        summary = context["summary"]
        findings = list(context["notable_findings"])
        case_summaries = list(context["case_summaries"])
        current_markdown = str(context.get("current_markdown", "") or "")

        # User muốn xem lại bản final report hiện tại
        if self._contains_any(
            lowered,
            [
                "show",
                "show lại",
                "show lai",
                "hiển thị",
                "hien thi",
                "xem lại",
                "xem lai",
                "bản trình bày",
                "ban trinh bay",
                "report đâu",
                "report dau",
                "show cho tôi",
                "show cho toi",
            ],
        ):
            if current_markdown:
                return current_markdown
            return "Hiện chưa có bản markdown final report hiện tại để hiển thị lại."

        # User chỉ đang xác nhận nhẹ sau report
        if self._contains_any(
            lowered,
            [
                "tốt rồi",
                "tot roi",
                "ổn rồi",
                "on roi",
                "được rồi",
                "duoc roi",
            ],
        ):
            return (
                "Đã ổn. Nếu bạn muốn chốt và lưu, hãy nói `lưu`. "
                "Nếu muốn sửa tiếp report hoặc hỏi thêm, cứ nói tự nhiên."
            )

        if self._contains_any(lowered, ["tóm tắt", "tom tat", "summary"]):
            return self.build_shareable_summary(context)

        if self._contains_any(lowered, ["yt", "/yt", "500", "fail"]):
            yt_fails = [
                item for item in case_summaries
                if str(item.get("path", "")).lower() == "/yt"
                and str(item.get("verdict", "")).lower() in {"fail", "error"}
            ]
            if yt_fails:
                first = yt_fails[0]
                return (
                    f"Case `/YT` hiện fail với actual_status={first.get('actual_status')} "
                    f"và summary='{first.get('summary_message')}'. "
                    "Điều này nghiêng về API/backend issue hơn là lỗi orchestration nếu payload đã hợp lệ."
                )
            return "Hiện không thấy fail case nào của `/YT` trong final report hiện tại."

        if self._contains_any(lowered, ["skip", "bỏ qua", "bo qua"]):
            skip_cases = [
                item for item in case_summaries
                if bool(item.get("skipped")) or str(item.get("verdict", "")).lower() == "skip"
            ]
            if not skip_cases:
                return "Không có case nào bị skip trong final report hiện tại."
            lines = ["Các case bị skip nổi bật:"]
            for item in skip_cases[:8]:
                lines.append(
                    f"- {item.get('method')} {item.get('path')} | testcase_id={item.get('testcase_id')} | skip_reason={item.get('skip_reason')}"
                )
            return "\n".join(lines)

        if self._contains_any(lowered, ["target", "môi trường", "moi truong", "staging", "local", "prod"]):
            return (
                f"Target đã chọn là `{summary.get('selected_target') or context['target_name']}`. "
                f"Các candidate targets trước đó là {summary.get('candidate_targets') or context.get('candidate_targets') or []}."
            )

        if self._contains_any(lowered, ["feedback", "yt vào", "vì sao có yt", "vi sao co yt"]):
            feedback_history = summary.get("feedback_history") or context.get("review_feedback_history") or []
            if feedback_history:
                return (
                    "Trong review trace có feedback history như sau:\n- "
                    + "\n- ".join(feedback_history)
                    + "\nVì vậy final report có thêm scope liên quan tới `/YT`."
                )
            return "Không có feedback history nào được lưu trong final report hiện tại."

        if self._contains_any(lowered, ["slow", "chậm", "cham", "response time"]):
            slow_findings = [
                item for item in findings
                if str(item.get("title", "")).lower() == "slow response"
            ]
            if slow_findings:
                return "Các finding về slow response:\n- " + "\n- ".join(
                    str(item.get("detail", "")) for item in slow_findings[:8]
                )
            return "Không có finding slow response nào trong final report hiện tại."

        return (
            f"Tổng quan hiện tại: total={summary.get('total_cases', 0)}, "
            f"executed={summary.get('executed_cases', 0)}, "
            f"pass={summary.get('pass_cases', 0)}, "
            f"fail={summary.get('fail_cases', 0)}, "
            f"skip={summary.get('skip_cases_validation', 0)}, "
            f"error={summary.get('error_cases', 0)}. "
            "Bạn có thể hỏi cụ thể hơn về fail, skip, target, feedback history, hoặc yêu cầu tôi viết lại report."
        )

    def revise_markdown(
        self,
        *,
        context: dict[str, Any],
        instruction: str,
    ) -> str:
        lowered = instruction.strip().lower()
        summary = context["summary"]
        findings = list(context["notable_findings"])
        case_summaries = list(context["case_summaries"])

        if any(token in lowered for token in ["gọn", "gon", "ngắn", "ngan", "ngắn gọn", "ngan gon", "concise", "short"]):
            return (
                "# Final Workflow Report (Ngắn gọn)\n\n"
                f"- Target: `{summary.get('target_name')}`\n"
                f"- Original request: {summary.get('original_request')}\n"
                f"- Executed/Total: `{summary.get('executed_cases', 0)}/{summary.get('total_cases', 0)}`\n"
                f"- Pass/Fail/Skip/Error: `{summary.get('pass_cases', 0)}/{summary.get('fail_cases', 0)}/{summary.get('skip_cases_validation', 0)}/{summary.get('error_cases', 0)}`\n"
                f"- Feedback history: `{summary.get('feedback_history', [])}`\n"
                f"- Top findings: `{len(findings)}` finding(s)\n"
            )

        if any(token in lowered for token in ["chi tiết", "chi tiet", "detailed", "dài hơn", "dai hon", "kỹ hơn", "ky hon"]):
            lines = [
                "# Final Workflow Report (Chi tiết)",
                "",
                f"- Target: `{summary.get('target_name')}`",
                f"- Original request: {summary.get('original_request')}",
                f"- Selected target: `{summary.get('selected_target')}`",
                f"- Candidate targets: `{summary.get('candidate_targets', [])}`",
                f"- Canonical command: `{summary.get('canonical_command')}`",
                f"- Understanding explanation: {summary.get('understanding_explanation')}",
                "",
                "## Summary",
                f"- Total cases: `{summary.get('total_cases', 0)}`",
                f"- Executed cases: `{summary.get('executed_cases', 0)}`",
                f"- Pass: `{summary.get('pass_cases', 0)}`",
                f"- Fail: `{summary.get('fail_cases', 0)}`",
                f"- Skip: `{summary.get('skip_cases_validation', 0)}`",
                f"- Error: `{summary.get('error_cases', 0)}`",
                "",
                "## Notable Findings",
            ]
            if findings:
                for item in findings[:8]:
                    lines.append(f"- [{item.get('severity', 'info')}] {item.get('title')}: {item.get('detail')}")
            else:
                lines.append("- None")

            lines.append("")
            lines.append("## Case Overview")
            for item in case_summaries[:10]:
                lines.append(
                    f"- {item.get('method')} {item.get('path')} | verdict={item.get('verdict')} | actual_status={item.get('actual_status')} | summary={item.get('summary_message')}"
                )
            return "\n".join(lines)

        if any(token in lowered for token in ["bullet", "gạch đầu dòng", "gach dau dong"]):
            lines = [
                "# Final Workflow Report (Bullets)",
                "",
                f"- Target: `{summary.get('target_name')}`",
                f"- Original request: {summary.get('original_request')}",
                f"- Executed/Total: `{summary.get('executed_cases', 0)}/{summary.get('total_cases', 0)}`",
                f"- Pass/Fail/Skip/Error: `{summary.get('pass_cases', 0)}/{summary.get('fail_cases', 0)}/{summary.get('skip_cases_validation', 0)}/{summary.get('error_cases', 0)}`",
                "- Notable findings:",
            ]
            if findings:
                for item in findings[:8]:
                    lines.append(f"  - [{item.get('severity', 'info')}] {item.get('title')}: {item.get('detail')}")
            else:
                lines.append("  - None")
            return "\n".join(lines)

        if any(token in lowered for token in ["dễ hiểu", "de hieu", "không kỹ thuật", "khong ky thuat"]):
            return (
                "# Báo cáo dễ hiểu\n\n"
                f"Hệ thống `{summary.get('target_name')}` đã được kiểm thử với "
                f"{summary.get('total_cases', 0)} bài kiểm tra. "
                f"Kết quả là {summary.get('pass_cases', 0)} bài đạt, "
                f"{summary.get('fail_cases', 0)} bài lỗi, "
                f"{summary.get('skip_cases_validation', 0)} bài được bỏ qua, "
                f"và {summary.get('error_cases', 0)} bài gặp lỗi.\n\n"
                "Nếu bạn muốn, tôi có thể giải thích chi tiết từng lỗi bằng ngôn ngữ không kỹ thuật."
            )

        return context["current_markdown"]

    def _contains_any(self, text: str, tokens: list[str]) -> bool:
        return any(token in text for token in tokens)