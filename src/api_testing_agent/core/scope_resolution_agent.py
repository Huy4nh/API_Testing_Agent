from __future__ import annotations

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

from api_testing_agent.core.scope_resolution_models import ScopeResolutionDecision
from api_testing_agent.logging_config import bind_logger, get_logger


class ScopeResolutionAgent:
    """
    AI-first scope resolver cho request ban đầu sau khi target đã được chọn sẵn.
    """

    def __init__(self, model_name: str = "openai:gpt-5.2") -> None:
        self._model_name = ""
        self._agent = None
        self._logger = get_logger(__name__)
        self._system_prompt = (
            "Bạn là trợ lý phân tích phạm vi test API sau khi target đã được chọn sẵn.\n"
            "Luật:\n"
            "1. Nếu user KHÔNG chỉ rõ chức năng cụ thể, phải trả scope_mode='all'.\n"
            "2. Nếu user chỉ rõ chức năng hợp lệ, trả scope_mode='specific'.\n"
            "3. Nếu user chỉ rõ chức năng nhưng không có trong operation hints, trả scope_mode='invalid_function'.\n"
            "4. Không được tự chọn một operation cụ thể khi yêu cầu còn mơ hồ.\n"
            "5. Không được bịa operation/path/tag ngoài operation hints được cung cấp.\n"
        )
        self.set_model_name(model_name)

        self._logger.info(
            f"Initialized ScopeResolutionAgent with model={self._model_name}.",
            extra={"payload_source": "scope_resolution_init"},
        )

    def set_model_name(self, model_name: str) -> None:
        cleaned = model_name.strip()
        if not cleaned:
            raise ValueError("Model name must not be empty.")

        logger = bind_logger(
            self._logger,
            payload_source="scope_resolution_set_model",
        )
        logger.info(f"Setting ScopeResolutionAgent model to {cleaned}")

        self._model_name = cleaned
        model = init_chat_model(cleaned)
        self._agent = create_agent(
            model=model,
            tools=[],
            response_format=ScopeResolutionDecision,
        )

        logger.info("ScopeResolutionAgent model initialized successfully.")

    def get_model_name(self) -> str:
        return self._model_name

    def decide(
        self,
        *,
        raw_text: str,
        target_name: str,
        operation_hints: list[dict],
    ) -> ScopeResolutionDecision:
        logger = bind_logger(
            self._logger,
            target_name=target_name,
            payload_source="scope_resolution_decide",
        )
        logger.info(f"Starting scope resolution. operation_hints_count={len(operation_hints)}")

        if self._agent is None:
            logger.error("ScopeResolutionAgent is not initialized.")
            raise ValueError("ScopeResolutionAgent is not initialized.")

        result = self._agent.invoke(
            {
                "messages": [
                    {"role": "system", "content": self._system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"User request:\n{raw_text}\n\n"
                            f"Selected target:\n{target_name}\n\n"
                            f"Available operation hints:\n{operation_hints}\n\n"
                            "Hãy quyết định scope_mode đúng."
                        ),
                    },
                ]
            }
        )

        structured = result.get("structured_response")
        if structured is None:
            logger.error("Scope resolution agent did not return structured_response.")
            raise ValueError("Scope resolution agent did not return structured_response.")

        logger.info(f"Scope resolution completed. scope_mode={structured.scope_mode}")
        return structured