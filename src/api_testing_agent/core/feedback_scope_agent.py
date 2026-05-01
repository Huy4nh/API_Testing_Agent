from __future__ import annotations

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

from api_testing_agent.core.feedback_scope_models import FeedbackScopeDecision
from api_testing_agent.logging_config import bind_logger, get_logger


class FeedbackScopeAgent:
    """
    AI-first feedback resolver.
    Dùng để hiểu feedback trong vòng review testcase.
    """

    def __init__(self, model_name: str = "openai:gpt-5.2") -> None:
        self._model_name = ""
        self._agent = None
        self._logger = get_logger(__name__)
        self._system_prompt = (
            "Bạn là trợ lý chỉnh sửa phạm vi test API dựa trên feedback của user trong vòng review testcase.\n"
            "Bạn phải quyết định feedback này muốn:\n"
            "- keep\n"
            "- reset_all\n"
            "- replace_with_specific\n"
            "- add_specific\n"
            "- remove_specific\n"
            "- invalid_feedback\n"
            "\n"
            "Luật:\n"
            "1. 'chỉ test ...' thường là replace_with_specific.\n"
            "2. 'thêm ... nữa' thường là add_specific.\n"
            "3. 'bỏ ... đi', 'loại ... ra' thường là remove_specific.\n"
            "4. 'test lại toàn bộ', 'quay lại test hết' là reset_all.\n"
            "5. Không được bịa operation/path/tag ngoài operation hints được cung cấp.\n"
        )
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
        model = init_chat_model(cleaned)
        self._agent = create_agent(
            model=model,
            tools=[],
            response_format=FeedbackScopeDecision,
        )

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
            f"Starting feedback scope decision. all_operation_hints={len(all_operation_hints)}, current_scope_hints={len(current_scope_hints)}"
        )

        if self._agent is None:
            logger.error("FeedbackScopeAgent is not initialized.")
            raise ValueError("FeedbackScopeAgent is not initialized.")

        result = self._agent.invoke(
            {
                "messages": [
                    {"role": "system", "content": self._system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Target: {target_name}\n\n"
                            f"Feedback mới nhất:\n{feedback_text}\n\n"
                            f"All operation hints:\n{all_operation_hints}\n\n"
                            f"Current scope hints:\n{current_scope_hints}\n\n"
                            "Hãy quyết định action_mode phù hợp."
                        ),
                    },
                ]
            }
        )

        structured = result.get("structured_response")
        if structured is None:
            logger.error("FeedbackScopeAgent did not return structured_response.")
            raise ValueError("FeedbackScopeAgent did not return structured_response.")

        logger.info(f"Feedback scope decision completed. action_mode={structured.action_mode}")
        return structured