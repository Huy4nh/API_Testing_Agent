from __future__ import annotations

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

from api_testing_agent.core.feedback_scope_models import FeedbackScopeDecision


class FeedbackScopeAgent:
    """
    Agent chuyên dùng để hiểu feedback của user trong vòng review testcase.

    Khác với ScopeResolutionAgent:
    - ScopeResolutionAgent: hiểu phạm vi từ request ban đầu
    - FeedbackScopeAgent: hiểu feedback để sửa phạm vi hiện tại
    """

    def __init__(self, model_name: str = "openai:gpt-5.2") -> None:
        self._model_name = ""
        self._agent = None
        self._system_prompt = (
            "Bạn là trợ lý chỉnh sửa phạm vi test API dựa trên feedback của người dùng trong vòng review testcase.\n"
            "\n"
            "Nhiệm vụ của bạn là xác định feedback này muốn:\n"
            "- giữ nguyên scope hiện tại\n"
            "- quay về test toàn bộ\n"
            "- thay scope hiện tại bằng một scope cụ thể mới\n"
            "- thêm scope mới vào scope hiện tại\n"
            "- bỏ bớt một phần scope khỏi scope hiện tại\n"
            "\n"
            "Luật rất quan trọng:\n"
            "1. Nếu user nói kiểu 'chỉ test ...' => thường là replace_with_specific.\n"
            "2. Nếu user nói kiểu 'thêm ... nữa' => thường là add_specific.\n"
            "3. Nếu user nói kiểu 'bỏ ... đi', 'loại ... ra' => thường là remove_specific.\n"
            "4. Nếu user nói kiểu 'quay lại test toàn bộ', 'test hết lại' => reset_all.\n"
            "5. Không được bịa operation/path/tag ngoài danh sách operation hints được cung cấp.\n"
            "6. Nếu feedback không map được vào operation/path/tag nào thì trả invalid_feedback.\n"
        )
        self.set_model_name(model_name)

    def set_model_name(self, model_name: str) -> None:
        cleaned = model_name.strip()
        if not cleaned:
            raise ValueError("Model name must not be empty.")

        self._model_name = cleaned
        model = init_chat_model(cleaned)

        self._agent = create_agent(
            model=model,
            tools=[],
            response_format=FeedbackScopeDecision,
        )

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
        if self._agent is None:
            raise ValueError("FeedbackScopeAgent is not initialized.")

        result = self._agent.invoke(
            {
                "messages": [
                    {
                        "role": "system",
                        "content": self._system_prompt,
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Target hiện tại: {target_name}\n\n"
                            f"Feedback mới nhất của user:\n{feedback_text}\n\n"
                            f"Toàn bộ operation hints của target:\n{all_operation_hints}\n\n"
                            f"Scope hiện tại đang được test:\n{current_scope_hints}\n\n"
                            "Hãy trả ra action_mode đúng với feedback này."
                        ),
                    },
                ]
            }
        )

        structured = result.get("structured_response")
        if structured is None:
            raise ValueError("FeedbackScopeAgent did not return structured_response.")

        return structured