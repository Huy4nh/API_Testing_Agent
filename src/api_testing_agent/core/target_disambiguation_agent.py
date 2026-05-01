from __future__ import annotations

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

from api_testing_agent.core.target_disambiguation_models import TargetDisambiguationDecision
from api_testing_agent.logging_config import bind_logger, get_logger


class TargetDisambiguationAgent:
    """
    Agent dùng để xếp hạng candidate target và tạo câu hỏi hỏi lại user.
    Không được tự bịa target ngoài candidate list.
    """

    def __init__(self, model_name: str = "openai:gpt-5.2") -> None:
        self._model_name = ""
        self._agent = None
        self._logger = get_logger(__name__)
        self._system_prompt = (
            "Bạn là trợ lý chọn target API. "
            "Bạn chỉ được dùng các candidate target đã được cung cấp. "
            "Không được bịa target ngoài danh sách. "
            "Nếu chỉ có một candidate rất rõ thì trả auto_select. "
            "Nếu còn mơ hồ thì trả ask_user và tạo câu hỏi ngắn, rõ, dễ chọn."
        )
        self.set_model_name(model_name)

        self._logger.info(
            f"Initialized TargetDisambiguationAgent with model={self._model_name}.",
            extra={"payload_source": "target_disambiguation_init"},
        )

    def set_model_name(self, model_name: str) -> None:
        cleaned = model_name.strip()
        if not cleaned:
            raise ValueError("Model name must not be empty.")

        logger = bind_logger(
            self._logger,
            payload_source="target_disambiguation_set_model",
        )
        logger.info(f"Setting target disambiguation model to {cleaned}")

        self._model_name = cleaned
        model = init_chat_model(cleaned)

        self._agent = create_agent(
            model=model,
            tools=[],
            response_format=TargetDisambiguationDecision,
        )

        logger.info("Target disambiguation agent model initialized successfully.")

    def get_model_name(self) -> str:
        return self._model_name

    def decide(
        self,
        *,
        raw_text: str,
        candidate_payload: list[dict],
    ) -> TargetDisambiguationDecision:
        logger = bind_logger(
            self._logger,
            payload_source="target_disambiguation_decide",
        )
        logger.info(
            f"Starting target disambiguation. candidate_payload_count={len(candidate_payload)}"
        )

        if self._agent is None:
            logger.error("Target disambiguation agent is not initialized.")
            raise ValueError("Target disambiguation agent is not initialized.")

        result = self._agent.invoke(
            {
                "messages": [
                    {"role": "system", "content": self._system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "Người dùng nhập:\n"
                            f"{raw_text}\n\n"
                            "Danh sách candidate target tìm được là:\n"
                            f"{candidate_payload}\n\n"
                            "Hãy quyết định auto_select hay ask_user."
                        ),
                    },
                ]
            }
        )

        structured = result.get("structured_response")
        if structured is None:
            logger.error("Target disambiguation agent did not return structured_response.")
            raise ValueError("Target disambiguation agent did not return structured_response.")

        logger.info(
            f"Target disambiguation completed. mode={structured.mode}, selected_target={structured.selected_target}"
        )

        return structured