from __future__ import annotations

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

from api_testing_agent.core.scope_resolution_models import ScopeResolutionDecision


class ScopeResolutionAgent:
    """
    Agent dùng để quyết định:
    - user có chỉ rõ chức năng cụ thể hay không
    - nếu có thì match vào operation/path/tag nào
    - nếu không có thì trả scope_mode='all'
    - nếu user chỉ chức năng sai thì trả scope_mode='invalid_function'
    """

    def __init__(self, model_name: str = "openai:gpt-5.2") -> None:
        self._model_name = ""
        self._agent = None
        self._system_prompt = (
            "Bạn là trợ lý phân tích phạm vi test API sau khi target đã được chọn sẵn.\n"
            "Nhiệm vụ của bạn là xác định user có chỉ rõ chức năng cụ thể trong target hay không.\n"
            "\n"
            "Luật rất quan trọng:\n"
            "1. Nếu user KHÔNG chỉ rõ chức năng/path/module cụ thể, phải trả scope_mode='all'.\n"
            "2. Nếu user chỉ rõ chức năng và nó match được với operation hints, trả scope_mode='specific'.\n"
            "3. Nếu user có nói một chức năng cụ thể nhưng không match được với operation hints, trả scope_mode='invalid_function'.\n"
            "4. Không được tự chọn một operation cụ thể khi yêu cầu của user còn mơ hồ.\n"
            "5. Không được bịa operation/path/tag ngoài danh sách hints được cung cấp.\n"
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
            response_format=ScopeResolutionDecision,
        )

    def get_model_name(self) -> str:
        return self._model_name

    def decide(
        self,
        *,
        raw_text: str,
        forced_target_name: str,
        operation_hints: list[dict],
    ) -> ScopeResolutionDecision:
        if self._agent is None:
            raise ValueError("Scope resolution agent is not initialized.")

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
                            f"User request:\n{raw_text}\n\n"
                            f"Selected target:\n{forced_target_name}\n\n"
                            f"Available OpenAPI operation hints for this target:\n{operation_hints}\n\n"
                            "Hãy quyết định scope_mode là 'all', 'specific', hay 'invalid_function'."
                        ),
                    },
                ]
            }
        )

        structured = result.get("structured_response")
        if structured is None:
            raise ValueError("Scope resolution agent did not return structured_response.")

        return structured