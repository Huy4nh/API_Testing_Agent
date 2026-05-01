from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

from api_testing_agent.core.ai_testcase_models import AITestCaseDraftList
from api_testing_agent.logging_config import bind_logger, get_logger

SYSTEM_PROMP = (
    "Bạn là AI chuyên sinh test case cho REST API dựa trên OpenAPI. "
    "Bạn chỉ được sinh test case cho đúng 1 operation được cung cấp. "
    "Bạn phải trả output đúng schema có cấu trúc. "
    "Không được bịa endpoint mới. "
    "Không được bịa field ngoài schema trừ khi cố tình tạo invalid case. "
    "Không được đưa token thật vào Authorization header. "
    "Runtime system sẽ tự inject bearer token nếu cần. "
    "Nếu một test type không phù hợp với operation thì đặt skip=true và giải thích ngắn. "
    "Sinh tối đa 1 case cho mỗi test_type được yêu cầu."
)


class AITestCaseAgent:
    def __init__(self, model_name: str = "openai:gpt-5.2") -> None:
        self._model_name = ""
        self._agent = None
        self._logger = get_logger(__name__)
        self._system_prompt = SYSTEM_PROMP
        self.set_model_name(model_name)

        self._logger.info(
            f"Initialized AITestCaseAgent with model={self._model_name}.",
            extra={"payload_source": "ai_testcase_agent_init"},
        )

    def set_model_name(self, model_name: str) -> None:
        cleaned = model_name.strip()
        if not cleaned:
            raise ValueError("Model name must not be empty.")

        logger = bind_logger(
            self._logger,
            payload_source="ai_testcase_agent_set_model",
        )
        logger.info(f"Setting AI testcase model to {cleaned}")

        self._model_name = cleaned
        model = init_chat_model(cleaned)

        self._agent = create_agent(
            model=model,
            tools=[],
            response_format=AITestCaseDraftList,
        )

        logger.info("AI testcase agent model initialized successfully.")

    def get_model_name(self) -> str:
        return self._model_name

    def generate_for_operation(self, context: dict[str, Any]) -> AITestCaseDraftList:
        operation = context.get("operation", {})
        operation_id = str(operation.get("operation_id", "-")) if isinstance(operation, dict) else "-"
        target_name = str(context.get("target_name", "-"))

        logger = bind_logger(
            self._logger,
            target_name=target_name,
            operation_id=operation_id,
            payload_source="ai_testcase_generate",
        )
        logger.info("Starting testcase generation for operation.")

        if self._agent is None:
            logger.error("AI testcase agent is not initialized.")
            raise ValueError("Agent is not initialized.")

        result = self._agent.invoke(
            {
                "messages": [
                    {"role": "system", "content": self._system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "Sinh testcase draft cho operation sau. "
                            "Hãy trả về dữ liệu đúng schema.\n\n"
                            f"{json.dumps(context, ensure_ascii=False, indent=2)}"
                        ),
                    },
                ]
            }
        )

        structured = result.get("structured_response")
        if structured is None:
            logger.error("AI testcase agent did not return structured_response.")
            raise ValueError("Agent did not return structured_response.")

        logger.info(f"Generated testcase draft list successfully. case_count={len(structured.cases)}")
        return structured