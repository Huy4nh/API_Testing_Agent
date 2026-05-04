from __future__ import annotations

import json
import re
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from api_testing_agent.core.feedback_scope_models import FeedbackScopeDecision
from api_testing_agent.logging_config import bind_logger, get_logger


class FeedbackScopeAgent:
    """
    AI-first feedback resolver for pending_review scope mutation.

    Important:
    - Does NOT use create_agent(..., response_format=...)
      because some providers compile grammar for structured output and may fail with 503.
    - Uses normal chat completion + JSON parsing + Pydantic validation.
    - No target-specific hard-code. All decisions are catalog-driven.
    """

    def __init__(self, model_name: str = "openai:gpt-5.2") -> None:
        self._model_name = ""
        self._model = None
        self._logger = get_logger(__name__)
        self._system_prompt = self._build_system_prompt()
        self.set_model_name(model_name)

        self._logger.info(
            f"Initialized FeedbackScopeAgent with model={self._model_name}.",
            extra={"payload_source": "feedback_scope_agent_init"},
        )

    def set_model_name(self, model_name: str) -> None:
        cleaned = model_name.strip()
        if not cleaned:
            raise ValueError("Model name must not be empty.")

        logger = bind_logger(
            self._logger,
            payload_source="feedback_scope_set_model",
        )
        logger.info(f"Setting FeedbackScopeAgent model to {cleaned}")

        self._model_name = cleaned
        self._model = init_chat_model(cleaned)

        logger.info("FeedbackScopeAgent model initialized successfully.")

    def get_model_name(self) -> str:
        return self._model_name

    def decide(
        self,
        *,
        feedback_text: str,
        target_name: str,
        all_operation_hints: list[dict],
        current_scope_hints: list[dict],
    ) -> FeedbackScopeDecision:
        logger = bind_logger(
            self._logger,
            target_name=target_name,
            payload_source="feedback_scope_decide",
        )
        logger.info(
            "Starting feedback scope decision. "
            f"all_operation_hints={len(all_operation_hints)}, "
            f"current_scope_hints={len(current_scope_hints)}"
        )

        if self._model is None:
            raise ValueError("FeedbackScopeAgent model is not initialized.")

        payload = {
            "target_name": target_name,
            "latest_user_feedback": feedback_text,
            "current_active_scope_hints": current_scope_hints,
            "all_available_operation_hints": all_operation_hints,
        }

        raw_text = self._invoke_json_model(
            system_prompt=self._system_prompt,
            payload=payload,
        )

        try:
            parsed = self._parse_json_object(raw_text)
            decision = FeedbackScopeDecision.model_validate(parsed)
        except Exception as first_error:
            logger.warning(
                "FeedbackScopeAgent first JSON parse/validation failed; trying repair.",
                extra={
                    "payload_source": "feedback_scope_parse_repair",
                    "error": str(first_error),
                },
            )
            repaired_text = self._invoke_json_repair_model(
                original_text=raw_text,
                validation_error=str(first_error),
            )
            parsed = self._parse_json_object(repaired_text)
            decision = FeedbackScopeDecision.model_validate(parsed)

        logger.info(
            "Feedback scope decision completed. "
            f"action_mode={decision.action_mode}, confidence={decision.confidence}"
        )
        return decision

    def _invoke_json_model(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
    ) -> str:
        if self._model is None:
            raise ValueError("FeedbackScopeAgent model is not initialized.")

        response = self._model.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(
                    content=json.dumps(payload, ensure_ascii=False, indent=2)
                ),
            ]
        )
        return self._extract_text(response)

    def _invoke_json_repair_model(
        self,
        *,
        original_text: str,
        validation_error: str,
    ) -> str:
        if self._model is None:
            raise ValueError("FeedbackScopeAgent model is not initialized.")

        repair_prompt = """
Bạn là JSON repair assistant.

Nhiệm vụ:
- Chuyển output trước đó thành JSON object hợp lệ theo schema FeedbackScopeDecision.
- Không markdown.
- Không giải thích ngoài JSON.
- Không thêm operation/path/tag ngoài dữ liệu đã có trong output trước đó.
- Nếu không chắc, trả action_mode="keep".

Schema:
{
  "action_mode": "keep" | "reset_all" | "replace_with_specific" | "add_specific" | "remove_specific" | "update_scope" | "mixed_mutation" | "invalid_feedback",
  "matched_operation_ids": [],
  "matched_paths": [],
  "matched_tags": [],
  "add_operation_ids": [],
  "add_paths": [],
  "add_tags": [],
  "remove_operation_ids": [],
  "remove_paths": [],
  "remove_tags": [],
  "final_operation_ids": [],
  "final_paths": [],
  "final_tags": [],
  "invalid_feedback_text": null,
  "confidence": 0.0,
  "reason": ""
}
""".strip()

        payload = {
            "invalid_output": original_text,
            "validation_error": validation_error,
        }

        response = self._model.invoke(
            [
                SystemMessage(content=repair_prompt),
                HumanMessage(
                    content=json.dumps(payload, ensure_ascii=False, indent=2)
                ),
            ]
        )
        return self._extract_text(response)

    def _parse_json_object(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()

        if cleaned.startswith("```"):
            cleaned = re.sub(
                r"^```(?:json)?",
                "",
                cleaned,
                flags=re.IGNORECASE,
            ).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise ValueError("Model output does not contain a JSON object.")

        parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise ValueError("Parsed JSON root is not an object.")

        return parsed

    def _extract_text(self, response: Any) -> str:
        content = getattr(response, "content", response)

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue

                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                        continue

                parts.append(str(item))
            return "\n".join(parts)

        return str(content)

    def _build_system_prompt(self) -> str:
        return """
Bạn là AI planner chuyên xử lý chỉnh sửa phạm vi test API trong vòng review testcase.

Bạn nhận:
- latest_user_feedback
- current_active_scope_hints
- all_available_operation_hints

Nhiệm vụ:
Hiểu user muốn giữ, thay, thêm, bớt, reset, hoặc chỉnh scope như thế nào.
Bạn KHÔNG được bịa operation/path/tag ngoài catalog được cung cấp.

Các action_mode:
1. keep
   User không muốn đổi phạm vi operation. Có thể chỉ sửa wording/test data/testcase content.

2. reset_all
   User muốn quay lại test toàn bộ operation của target.

3. replace_with_specific
   User muốn thay toàn bộ scope hiện tại bằng một số operation cụ thể.
   Ví dụ: "chỉ test user và order".

4. add_specific
   User chỉ muốn thêm operation vào scope hiện tại.
   Ví dụ: "thêm phần payment vào".

5. remove_specific
   User chỉ muốn bỏ operation khỏi scope hiện tại.
   Ví dụ: "bỏ auth ra".

6. update_scope hoặc mixed_mutation
   User muốn vừa thêm vừa bỏ, hoặc chỉnh scope phức hợp.
   Ví dụ:
   - "bỏ fb thêm yt vào"
   - "bỏ 2 thằng trên thêm yt với fb vào"
   - "remove auth and add users"
   - "thay phần cũ bằng phần search"

7. invalid_feedback
   Chỉ dùng khi user thật sự yêu cầu operation không tồn tại trong catalog
   hoặc feedback không thể hiểu được sau khi đã xem catalog.

Nguyên tắc cực quan trọng:
- Nếu user nói "bỏ A thêm B", đây là update_scope/mixed_mutation.
- Nếu user nói "bỏ 2 thằng trên", "bỏ mấy cái hiện tại", "remove current ones", hãy hiểu là remove current_active_scope_hints.
- Nếu user nói "thêm B", hãy tìm B trong all_available_operation_hints bằng operation_id/path/tags/summary.
- Nếu A đang có trong current scope và B có trong all operations, hãy remove A và add B.
- Nếu user nói "thay A bằng B", hãy dùng update_scope/mixed_mutation.
- Nếu user nói "chỉ giữ ..." hoặc "chỉ test ...", hãy dùng replace_with_specific hoặc final_operation_ids.
- Nếu user nói "thêm ..." mà không nói bỏ cái gì, dùng add_specific.
- Nếu user nói "bỏ ..." mà không nói thêm cái gì, dùng remove_specific.
- Ưu tiên trả operation_id chính xác.
- Không trả text như "group yt" nếu có thể trả operation_id/path/tag thật.
- Không tự biến yêu cầu đổi operation scope thành sửa test data.

Trả về DUY NHẤT một JSON object hợp lệ, không markdown, không giải thích ngoài JSON.

Schema:
{
  "action_mode": "keep" | "reset_all" | "replace_with_specific" | "add_specific" | "remove_specific" | "update_scope" | "mixed_mutation" | "invalid_feedback",
  "matched_operation_ids": [],
  "matched_paths": [],
  "matched_tags": [],
  "add_operation_ids": [],
  "add_paths": [],
  "add_tags": [],
  "remove_operation_ids": [],
  "remove_paths": [],
  "remove_tags": [],
  "final_operation_ids": [],
  "final_paths": [],
  "final_tags": [],
  "invalid_feedback_text": null,
  "confidence": 0.0,
  "reason": ""
}
""".strip()