from __future__ import annotations

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

from api_testing_agent.core.target_resolution_models import TargetResolutionDecision


class TargetResolutionAgent:
    """
    AI-first target resolver:
    - hiểu user đang nói target nào
    - nếu mơ hồ thì trả ask_user
    - không bịa target ngoài danh sách available_targets
    """

    def __init__(self, model_name: str = "openai:gpt-5.2") -> None:
        self._model_name = ""
        self._agent = None
        self._system_prompt = (
            "Bạn là trợ lý chọn target API.\n"
            "Bạn chỉ được dùng các target trong danh sách available_targets.\n"
            "Không được bịa target ngoài danh sách.\n"
            "Nếu chỉ có một target rõ ràng thì trả mode='auto_select'.\n"
            "Nếu có nhiều target gần giống nhau thì trả mode='ask_user'.\n"
            "Nếu không match được target nào thì trả mode='no_match'.\n"
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
            response_format=TargetResolutionDecision,
        )

    def get_model_name(self) -> str:
        return self._model_name

    def decide(
        self,
        *,
        raw_text: str,
        available_targets: list[str],
    ) -> TargetResolutionDecision:
        if self._agent is None:
            raise ValueError("TargetResolutionAgent is not initialized.")

        result = self._agent.invoke(
            {
                "messages": [
                    {"role": "system", "content": self._system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"User request:\n{raw_text}\n\n"
                            f"Available targets:\n{available_targets}\n\n"
                            "Hãy chọn đúng mode và candidates."
                        ),
                    },
                ]
            }
        )

        structured = result.get("structured_response")
        if structured is None:
            raise ValueError("Target resolution agent did not return structured_response.")
        return structured