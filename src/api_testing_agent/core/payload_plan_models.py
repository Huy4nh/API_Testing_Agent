from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, Field, field_validator


BasePayloadStrategy: TypeAlias = Literal[
    "use_explicit",
    "synthesize_from_schema",
]

MutationKind: TypeAlias = Literal[
    "none",
    "remove_required_field",
    "invalid_type_or_format",
    "semantic_positive",
]

# Giữ lại để tương thích ngược với code/test cũ nếu cần
InvalidValueStrategy: TypeAlias = Literal[
    "infer_from_schema",
    "number_for_string",
    "string_for_integer",
    "string_for_number",
    "string_for_boolean",
    "string_for_array",
    "string_for_object",
]


class PayloadPlan(BaseModel):
    """
    Kế hoạch dựng payload runtime.

    Điểm khác biệt lớn của bản này:
    - AI có thể trả về field_overrides cụ thể theo ngữ nghĩa
      thay vì chỉ trả strategy kiểu "string_for_integer".
    - Runtime deterministic chỉ việc apply plan.
    """

    trust_explicit_payload: bool = Field(
        default=False,
        description="Có nên trust explicit json_body từ testcase draft không.",
    )

    base_payload_strategy: BasePayloadStrategy = Field(
        default="synthesize_from_schema",
        description="Chọn base payload từ explicit payload hay từ schema.",
    )

    mutation_kind: MutationKind = Field(
        default="none",
        description="Loại mutation hoặc semantic adjustment.",
    )

    target_field: str | None = Field(
        default=None,
        description="Field mục tiêu chính mà testcase đang nhắm tới.",
    )

    # Giữ lại để backward-compatible, nhưng bản mới ưu tiên field_overrides cụ thể
    invalid_value_strategy: InvalidValueStrategy | None = Field(
        default=None,
        description="Fallback strategy nếu chưa có concrete field_overrides.",
    )

    # Bản mới: field nào cần remove
    fields_to_remove: list[str] = Field(
        default_factory=list,
        description="Danh sách field cần loại khỏi payload cuối cùng.",
    )

    # Bản mới: giá trị cụ thể cần set/override
    field_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description="Các field/value cụ thể cần set vào payload cuối cùng.",
    )

    reason: str = Field(
        default="",
        description="Giải thích ngắn gọn vì sao planner chọn plan này.",
    )

    confidence: float | None = Field(
        default=None,
        description="Mức độ tự tin từ 0.0 đến 1.0.",
    )

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value < 0:
            return 0.0
        if value > 1:
            return 1.0
        return value