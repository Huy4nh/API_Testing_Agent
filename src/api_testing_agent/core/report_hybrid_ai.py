from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from langchain_core.messages import HumanMessage, SystemMessage

from api_testing_agent.logging_config import bind_logger, get_logger

try:
    from langchain.chat_models import init_chat_model
except Exception:  # pragma: no cover
    init_chat_model = None  # type: ignore


@runtime_checkable
class ReviewActionHybridAIProtocol(Protocol):
    def decide_review_action(
        self,
        *,
        thread_id: str,
        target_name: str | None,
        user_text: str,
        preview_text: str,
        feedback_history: list[str],
    ) -> dict[str, Any]:
        ...


@runtime_checkable
class ReportIntentHybridAIProtocol(Protocol):
    def decide_report_intent(
        self,
        *,
        thread_id: str,
        target_name: str | None,
        user_text: str,
        final_report_data: dict[str, Any],
        current_markdown: str,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        ...


@runtime_checkable
class ReportAnswerHybridAIProtocol(Protocol):
    def answer_report_question(
        self,
        *,
        thread_id: str,
        target_name: str | None,
        user_text: str,
        final_report_data: dict[str, Any],
        current_markdown: str,
        messages: list[dict[str, str]],
    ) -> str:
        ...


@runtime_checkable
class ReportRewriteHybridAIProtocol(Protocol):
    def rewrite_report(
        self,
        *,
        thread_id: str,
        target_name: str | None,
        instruction: str,
        final_report_data: dict[str, Any],
        current_markdown: str,
        messages: list[dict[str, str]],
    ) -> str:
        ...


@runtime_checkable
class ReportInteractionHybridAIProtocol(
    ReportIntentHybridAIProtocol,
    ReportAnswerHybridAIProtocol,
    ReportRewriteHybridAIProtocol,
    Protocol,
):
    pass


class ReportHybridAI:
    """
    Lớp AI helper cho:
    - classify review action ở pending_review
    - classify post-report intent
    - answer câu hỏi về final report
    - rewrite final report theo instruction user
    """

    def __init__(
        self,
        *,
        model_name: str,
        model_provider: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        self._model_name = model_name.strip()
        self._model_provider = (model_provider or "").strip() or None
        self._temperature = temperature
        self._logger = get_logger(__name__)
        self._model = self._build_model()

    def _build_model(self):
        if init_chat_model is None:
            raise RuntimeError(
                "Không import được langchain.chat_models.init_chat_model. "
                "Hãy kiểm tra package langchain trong môi trường."
            )

        kwargs: dict[str, Any] = {
            "model": self._model_name,
            "temperature": self._temperature,
        }

        if self._model_provider:
            kwargs["model_provider"] = self._model_provider

        return init_chat_model(**kwargs)

    def decide_review_action(
        self,
        *,
        thread_id: str,
        target_name: str | None,
        user_text: str,
        preview_text: str,
        feedback_history: list[str],
    ) -> dict[str, Any]:
        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=str(target_name or "-"),
            payload_source="ai_decide_review_action",
        )
        logger.info("Deciding review action with AI fallback.")

        system_prompt = """
Bạn là bộ phân loại hành động review testcase draft.

Nhiệm vụ:
- Nhận message mới của user ở trạng thái pending_review.
- Chỉ trả về JSON hợp lệ, không thêm markdown.
- Quyết định một trong 3 action:
  1. approve
  2. revise
  3. cancel

Quy tắc:
- Nếu user thể hiện đồng ý/chốt/ổn/rồi/lưu ý rằng draft đã tốt, thường là approve.
- Nếu user yêu cầu sửa, thêm bớt, thay đổi nội dung testcase, là revise.
- Nếu user muốn dừng/hủy, là cancel.
- "tốt rồi", "ổn rồi", "ok rồi", "được rồi", "aprove", "aprrove" thường nên hiểu là approve.
- Nếu không chắc, ưu tiên revise thay vì approve.
- Nếu action là revise mà user không đưa feedback rõ, feedback có thể để rỗng.

Trả về JSON schema:
{
  "action": "approve" | "revise" | "cancel",
  "feedback": "<string, có thể rỗng>",
  "confidence": <float 0..1>,
  "reason": "<string>"
}
""".strip()

        human_payload = {
            "user_text": user_text,
            "preview_text": preview_text,
            "feedback_history": feedback_history,
        }

        raw = self._invoke_json(
            system_prompt=system_prompt,
            human_payload=human_payload,
        )
        logger.info(f"AI review action raw result={raw}")

        action = str(raw.get("action", "revise")).strip().lower()
        if action not in {"approve", "revise", "cancel"}:
            action = "revise"

        feedback = str(raw.get("feedback", "") or "")
        confidence = self._to_float(raw.get("confidence"), default=0.5)
        reason = str(raw.get("reason", "AI fallback review action."))

        return {
            "action": action,
            "feedback": feedback,
            "confidence": confidence,
            "reason": reason,
        }

    def decide_report_intent(
        self,
        *,
        thread_id: str,
        target_name: str | None,
        user_text: str,
        final_report_data: dict[str, Any],
        current_markdown: str,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=str(target_name or "-"),
            payload_source="ai_decide_report_intent",
        )
        logger.info("Deciding report intent with AI fallback.")

        system_prompt = """
Bạn là bộ phân loại intent sau final report.

Nhiệm vụ:
- Nhận message mới của user sau khi final report đã được tạo.
- Chỉ trả về JSON hợp lệ.
- Chọn một intent trong danh sách:
  1. ask_report_question
  2. revise_report_text
  3. revise_and_rerun
  4. share_report
  5. finalize_report
  6. cancel_report

Quy tắc:
- Nếu user hỏi giải thích, hỏi vì sao, hỏi "đã sửa chỗ nào", hỏi ý nghĩa report -> ask_report_question
- Nếu user muốn viết lại report, dễ hiểu hơn, ngắn gọn hơn, chi tiết hơn, tự nhiên hơn -> revise_report_text
- Nếu user muốn đổi scope test và chạy lại -> revise_and_rerun
- Nếu user muốn bản tóm tắt gửi team/sếp -> share_report
- Nếu user nói lưu/chốt/done/ok để kết thúc -> finalize_report
- Nếu user nói hủy/bỏ hết -> cancel_report
- Những câu như "cho tôi bản dễ hiểu hơn", "nói tự nhiên hơn", "giải thích kiểu không kỹ thuật" thường nên hiểu là revise_report_text
- Những câu như "tốt rồi" sau final report KHÔNG tự động là finalize_report; chỉ coi là finalize_report nếu user thể hiện rõ ý lưu/chốt.

Trả về JSON schema:
{
  "intent": "ask_report_question" | "revise_report_text" | "revise_and_rerun" | "share_report" | "finalize_report" | "cancel_report",
  "confidence": <float 0..1>,
  "reason": "<string>",
  "revision_instruction": "<string|null>",
  "rerun_instruction": "<string|null>"
}
""".strip()

        human_payload = {
            "user_text": user_text,
            "current_markdown": current_markdown,
            "messages": messages[-8:],
            "summary": final_report_data.get("summary", {}),
            "notable_findings": final_report_data.get("notable_findings", []),
        }

        raw = self._invoke_json(
            system_prompt=system_prompt,
            human_payload=human_payload,
        )
        logger.info(f"AI report intent raw result={raw}")
        return raw

    def answer_report_question(
        self,
        *,
        thread_id: str,
        target_name: str | None,
        user_text: str,
        final_report_data: dict[str, Any],
        current_markdown: str,
        messages: list[dict[str, str]],
    ) -> str:
        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=str(target_name or "-"),
            payload_source="ai_answer_report_question",
        )
        logger.info("Answering report question with grounded AI.")

        system_prompt = """
Bạn là trợ lý giải thích final report kiểm thử API.

Yêu cầu:
- Chỉ dùng thông tin có trong context được cung cấp.
- Không bịa thêm dữ kiện ngoài context.
- Trả lời bằng tiếng Việt tự nhiên, dễ hiểu.
- Nếu user hỏi "bạn đã sửa chỗ nào", hãy trả lời dựa trên current_markdown và lịch sử gần đây.
- Nếu user hỏi kiểu "nói dễ hiểu hơn", hãy giải thích theo ngôn ngữ ít kỹ thuật hơn.
- Nếu context không đủ, hãy nói rõ là thông tin hiện tại chưa đủ.
""".strip()

        human_payload = {
            "user_text": user_text,
            "current_markdown": current_markdown,
            "messages": messages[-10:],
            "final_report_data": final_report_data,
        }

        return self._invoke_text(
            system_prompt=system_prompt,
            human_payload=human_payload,
        )

    def rewrite_report(
        self,
        *,
        thread_id: str,
        target_name: str | None,
        instruction: str,
        final_report_data: dict[str, Any],
        current_markdown: str,
        messages: list[dict[str, str]],
    ) -> str:
        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=str(target_name or "-"),
            payload_source="ai_rewrite_report",
        )
        logger.info("Rewriting final report with grounded AI.")

        system_prompt = """
Bạn là trợ lý viết lại final report kiểm thử API.

Yêu cầu:
- Chỉ dùng dữ liệu trong final_report_data.
- Không tự ý thêm kết quả test mới.
- Giữ nguyên facts, chỉ đổi cách trình bày.
- Nếu user yêu cầu "ngắn gọn", hãy ngắn gọn thật.
- Nếu user yêu cầu "dễ hiểu", hãy viết như giải thích cho người không kỹ thuật.
- Nếu user yêu cầu "chi tiết hơn", hãy mở rộng phần findings và case overview.
- Trả về markdown hoàn chỉnh, không thêm giải thích ngoài markdown.
""".strip()

        human_payload = {
            "instruction": instruction,
            "current_markdown": current_markdown,
            "messages": messages[-10:],
            "final_report_data": final_report_data,
        }

        return self._invoke_text(
            system_prompt=system_prompt,
            human_payload=human_payload,
        )

    def _invoke_json(
        self,
        *,
        system_prompt: str,
        human_payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = self._model.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(
                    content=json.dumps(
                        human_payload,
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
            ]
        )

        content = getattr(response, "content", "")
        if not isinstance(content, str):
            raise ValueError("AI response content is not a string.")

        cleaned = content.strip()

        if cleaned.startswith("```json"):
            cleaned = cleaned.removeprefix("```json").strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()

        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("AI JSON response must be an object.")

        return parsed

    def _invoke_text(
        self,
        *,
        system_prompt: str,
        human_payload: dict[str, Any],
    ) -> str:
        response = self._model.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(
                    content=json.dumps(
                        human_payload,
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
            ]
        )

        content = getattr(response, "content", "")
        if isinstance(content, str):
            return content.strip()

        return str(content)

    def _to_float(
        self,
        value: Any,
        *,
        default: float,
    ) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default