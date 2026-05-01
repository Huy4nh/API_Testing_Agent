from __future__ import annotations

import os
import re
from typing import Any, Protocol

from langchain.chat_models import init_chat_model

from api_testing_agent.core.payload_plan_models import (
    InvalidValueStrategy,
    PayloadPlan,
)
from api_testing_agent.logging_config import bind_logger, get_logger


class PayloadPlannerServiceProtocol(Protocol):
    def plan(
        self,
        *,
        operation_context: dict[str, Any],
        case: dict[str, Any],
        explicit_json_body: Any,
    ) -> PayloadPlan:
        ...


class DeterministicFallbackPayloadPlanner:
    """
    Fallback planner:
    - không đủ semantic như AI planner
    - nhưng vẫn chạy được nếu model unavailable
    """

    def __init__(self) -> None:
        self._logger = get_logger(__name__)

    def plan(
        self,
        *,
        operation_context: dict[str, Any],
        case: dict[str, Any],
        explicit_json_body: Any,
    ) -> PayloadPlan:
        operation_id = str(operation_context.get("operation_id", "-"))
        test_type = str(case.get("test_type", "")).strip().lower()
        logger = bind_logger(
            self._logger,
            operation_id=operation_id,
            payload_source="payload_planner_fallback",
        )
        logger.info(f"Using deterministic fallback planner. test_type={test_type}")

        schema = self._extract_schema(operation_context)

        if explicit_json_body is not None and not self._is_empty_object(explicit_json_body):
            logger.info("Fallback planner trusted explicit non-empty payload.")
            return PayloadPlan(
                trust_explicit_payload=True,
                base_payload_strategy="use_explicit",
                mutation_kind="none",
                reason="Fallback planner trust explicit payload vì payload không rỗng.",
                confidence=0.70,
            )

        if test_type == "missing_required":
            target_field = self._infer_target_field(
                case=case,
                schema=schema,
                only_required=True,
            )
            fields_to_remove = [target_field] if target_field else []

            logger.info(
                f"Fallback planner built missing_required plan. target_field={target_field}, remove_count={len(fields_to_remove)}"
            )
            return PayloadPlan(
                trust_explicit_payload=False,
                base_payload_strategy="synthesize_from_schema",
                mutation_kind="remove_required_field",
                target_field=target_field,
                fields_to_remove=fields_to_remove,
                reason="Fallback planner sẽ synthesize payload rồi remove required field mục tiêu.",
                confidence=0.75,
            )

        if test_type == "invalid_type_or_format":
            target_field = self._infer_target_field(
                case=case,
                schema=schema,
                only_required=False,
            )
            target_schema = self._extract_field_schema(schema, target_field)
            strategy = self._infer_invalid_strategy_from_field_schema(target_schema)

            logger.info(
                f"Fallback planner built invalid_type_or_format plan. target_field={target_field}, strategy={strategy}"
            )
            return PayloadPlan(
                trust_explicit_payload=False,
                base_payload_strategy="synthesize_from_schema",
                mutation_kind="invalid_type_or_format",
                target_field=target_field,
                invalid_value_strategy=strategy,
                field_overrides={},
                reason="Fallback planner chọn invalid strategy từ field schema.",
                confidence=0.72,
            )

        logger.info("Fallback planner built default synthesize_from_schema plan.")
        return PayloadPlan(
            trust_explicit_payload=False,
            base_payload_strategy="synthesize_from_schema",
            mutation_kind="none",
            reason="Fallback planner dùng payload hợp lệ tổng quát từ schema.",
            confidence=0.60,
        )

    def _extract_schema(self, operation_context: dict[str, Any]) -> dict[str, Any]:
        request_body = operation_context.get("request_body")
        if not isinstance(request_body, dict):
            return {}

        schema = request_body.get("schema")
        return schema if isinstance(schema, dict) else {}

    def _extract_field_schema(self, schema: dict[str, Any], field_name: str | None) -> dict[str, Any]:
        if not field_name:
            return {}

        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return {}

        field_schema = properties.get(field_name)
        return field_schema if isinstance(field_schema, dict) else {}

    def _infer_target_field(
        self,
        *,
        case: dict[str, Any],
        schema: dict[str, Any],
        only_required: bool,
    ) -> str | None:
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict):
            properties = {}

        candidate_fields = list(properties.keys())

        if only_required:
            required = schema.get("required") or []
            if isinstance(required, list) and required:
                candidate_fields = [str(item) for item in required]

        if not candidate_fields:
            return None

        direct_keys = ("field_name", "target_field", "parameter_name")
        lowered_map = {field.lower(): field for field in candidate_fields}

        for key in direct_keys:
            value = case.get(key)
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in lowered_map:
                    return lowered_map[lowered]

        text_parts: list[str] = []
        for key in ("description", "reasoning_summary", "why", "title", "name"):
            value = case.get(key)
            if isinstance(value, str) and value.strip():
                text_parts.append(value.strip())

        combined_text = " ".join(text_parts).lower()
        quoted_matches = re.findall(r"['\"]([a-zA-Z0-9_]+)['\"]", combined_text)

        for token in quoted_matches:
            lowered = token.lower()
            if lowered in lowered_map:
                return lowered_map[lowered]

        for lowered_field, original_field in lowered_map.items():
            if re.search(rf"\b{re.escape(lowered_field)}\b", combined_text):
                return original_field

        return candidate_fields[0]

    def _infer_invalid_strategy_from_field_schema(
        self,
        field_schema: dict[str, Any],
    ) -> InvalidValueStrategy:
        field_type = self._extract_type_from_schema(field_schema)

        if field_type == "string":
            return "number_for_string"
        if field_type == "integer":
            return "string_for_integer"
        if field_type == "number":
            return "string_for_number"
        if field_type == "boolean":
            return "string_for_boolean"
        if field_type == "array":
            return "string_for_array"
        if field_type == "object":
            return "string_for_object"

        return "infer_from_schema"

    def _extract_type_from_schema(self, schema: dict[str, Any]) -> str | None:
        direct_type = schema.get("type")

        if isinstance(direct_type, list):
            non_null = [item for item in direct_type if item != "null"]
            return non_null[0] if non_null else direct_type[0]

        if isinstance(direct_type, str):
            return direct_type

        for composite_key in ("anyOf", "oneOf", "allOf"):
            composite_value = schema.get(composite_key)
            if not isinstance(composite_value, list):
                continue

            for item in composite_value:
                if not isinstance(item, dict):
                    continue

                nested_type = item.get("type")
                if isinstance(nested_type, list):
                    non_null = [x for x in nested_type if x != "null"]
                    return non_null[0] if non_null else nested_type[0]

                if isinstance(nested_type, str):
                    return nested_type

        return None

    def _is_empty_object(self, value: Any) -> bool:
        return isinstance(value, dict) and len(value) == 0


class AIPayloadPlannerService:
    """
    AI-first planner:
    - AI phải trả concrete field_overrides / fields_to_remove khi có thể
    - fallback chỉ dùng khi AI unavailable hoặc lỗi
    """

    def __init__(
        self,
        *,
        model_name: str | None = None,
        model_provider: str | None = None,
    ) -> None:
        self._logger = get_logger(__name__)
        self._model_name = (model_name or os.getenv("LANGCHAIN_MODEL_NAME") or "").strip() or None
        self._model_provider = (model_provider or os.getenv("LANGCHAIN_MODEL_PROVIDER") or "").strip() or None

        self._fallback = DeterministicFallbackPayloadPlanner()
        self._structured_llm = None

        init_logger = bind_logger(
            self._logger,
            payload_source="payload_planner_init",
        )
        init_logger.info(
            f"Initializing AIPayloadPlannerService. model_name={self._model_name}, model_provider={self._model_provider}"
        )

        if self._model_name:
            try:
                llm = init_chat_model(
                    self._model_name,
                    model_provider=self._model_provider,
                    temperature=0,
                )
                self._structured_llm = llm.with_structured_output(PayloadPlan)
                init_logger.info("Structured LLM for payload planner initialized successfully.")
            except Exception:
                init_logger.exception("Failed to initialize structured LLM for payload planner. Falling back.")
                self._structured_llm = None
        else:
            init_logger.warning("No model_name configured for payload planner. Fallback planner only.")

    def plan(
        self,
        *,
        operation_context: dict[str, Any],
        case: dict[str, Any],
        explicit_json_body: Any,
    ) -> PayloadPlan:
        operation_id = str(operation_context.get("operation_id", "-"))
        test_type = str(case.get("test_type", "")).strip().lower()
        logger = bind_logger(
            self._logger,
            operation_id=operation_id,
            payload_source="payload_planner_plan",
        )
        logger.info(f"Starting payload planning. test_type={test_type}")

        if self._structured_llm is None:
            logger.warning("Structured LLM unavailable. Using fallback payload planner.")
            return self._fallback.plan(
                operation_context=operation_context,
                case=case,
                explicit_json_body=explicit_json_body,
            )

        prompt = self._build_prompt(
            operation_context=operation_context,
            case=case,
            explicit_json_body=explicit_json_body,
        )

        try:
            result = self._structured_llm.invoke(prompt)
            if isinstance(result, PayloadPlan):
                logger.info(
                    f"AI payload planner returned PayloadPlan directly. mutation_kind={result.mutation_kind}, target_field={result.target_field}"
                )
                return result

            validated = PayloadPlan.model_validate(result)
            logger.info(
                f"AI payload planner returned model-validated plan. mutation_kind={validated.mutation_kind}, target_field={validated.target_field}"
            )
            return validated
        except Exception:
            logger.exception("AI payload planner failed during invoke/validate. Falling back.")
            return self._fallback.plan(
                operation_context=operation_context,
                case=case,
                explicit_json_body=explicit_json_body,
            )

    def _build_prompt(
        self,
        *,
        operation_context: dict[str, Any],
        case: dict[str, Any],
        explicit_json_body: Any,
    ) -> str:
        schema = self._extract_schema(operation_context)
        field_summary = self._build_field_summary(schema)
        summary = str(operation_context.get("summary", "")).strip()
        operation_id = str(operation_context.get("operation_id", "")).strip()
        path = str(operation_context.get("path", "")).strip()

        return f"""
Bạn là AI Payload Planner cho hệ thống test REST API.

Mục tiêu:
- Trả về DUY NHẤT một PayloadPlan hợp lệ.
- Không viết giải thích ngoài schema của PayloadPlan.
- Ưu tiên trả về concrete field_overrides và fields_to_remove để runtime không phải bịa giá trị generic.
- Không dùng placeholder kiểu "string", "invalid_integer", "https://example.com" nếu testcase yêu cầu semantic value cụ thể hơn.
- Nếu testcase nói "URL YouTube hợp lệ", hãy đặt field_overrides thành một URL YouTube thực sự hợp lệ.
- Nếu testcase nói "số nguyên thay vì chuỗi", field_overrides phải là giá trị integer thật, không phải chuỗi.
- Nếu testcase nói thiếu trường bắt buộc, hãy điền fields_to_remove rõ ràng.
- Chỉ trust explicit_json_body nếu nó thực sự usable và bám testcase.

Operation metadata:
- operation_id: {operation_id}
- summary: {summary}
- method: {operation_context.get("method")}
- path: {path}

Case metadata:
- test_type: {case.get("test_type")}
- description: {case.get("description")}
- why: {case.get("why") or case.get("reasoning_summary")}
- explicit_json_body: {explicit_json_body}

Schema summary:
{field_summary}

Yêu cầu lập plan:
1. base_payload_strategy:
   - dùng "use_explicit" nếu explicit_json_body tốt
   - ngược lại dùng "synthesize_from_schema"
2. fields_to_remove:
   - điền nếu testcase là missing_required
3. field_overrides:
   - điền value cụ thể theo ngữ nghĩa testcase
   - ví dụ URL YouTube hợp lệ, integer thật, boolean thật, array thật...
4. invalid_value_strategy:
   - chỉ dùng làm fallback nếu thật sự chưa thể tạo concrete field_overrides
5. reason:
   - giải thích ngắn gọn, rõ
6. confidence:
   - số từ 0 đến 1
        """.strip()

    def _extract_schema(self, operation_context: dict[str, Any]) -> dict[str, Any]:
        request_body = operation_context.get("request_body")
        if not isinstance(request_body, dict):
            return {}

        schema = request_body.get("schema")
        return schema if isinstance(schema, dict) else {}

    def _build_field_summary(self, schema: dict[str, Any]) -> str:
        properties = schema.get("properties") or {}
        required = schema.get("required") or []

        if not isinstance(properties, dict):
            properties = {}
        if not isinstance(required, list):
            required = []

        lines: list[str] = []
        lines.append(f"required_fields={required}")

        for field_name, field_schema in properties.items():
            if not isinstance(field_schema, dict):
                continue

            field_type = self._extract_type_from_schema(field_schema)
            field_format = self._extract_format_from_schema(field_schema)
            lines.append(f"- {field_name}: type={field_type}, format={field_format}")

        return "\n".join(lines)

    def _extract_type_from_schema(self, schema: dict[str, Any]) -> str | None:
        direct_type = schema.get("type")

        if isinstance(direct_type, list):
            non_null = [item for item in direct_type if item != "null"]
            return non_null[0] if non_null else direct_type[0]

        if isinstance(direct_type, str):
            return direct_type

        for composite_key in ("anyOf", "oneOf", "allOf"):
            composite_value = schema.get(composite_key)
            if not isinstance(composite_value, list):
                continue

            for item in composite_value:
                if not isinstance(item, dict):
                    continue

                nested_type = item.get("type")

                if isinstance(nested_type, list):
                    non_null = [x for x in nested_type if x != "null"]
                    return non_null[0] if non_null else nested_type[0]

                if isinstance(nested_type, str):
                    return nested_type

        return None

    def _extract_format_from_schema(self, schema: dict[str, Any]) -> str | None:
        direct_format = schema.get("format")
        if isinstance(direct_format, str):
            return direct_format

        for composite_key in ("anyOf", "oneOf", "allOf"):
            composite_value = schema.get(composite_key)
            if not isinstance(composite_value, list):
                continue
            for item in composite_value:
                if not isinstance(item, dict):
                    continue
                nested_format = item.get("format")
                if isinstance(nested_format, str):
                    return nested_format

        return None