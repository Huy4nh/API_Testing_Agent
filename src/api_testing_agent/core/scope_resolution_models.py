from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ScopeResolutionDecision(BaseModel):
    scope_mode: Literal["all", "specific", "invalid_function"] = Field(
        description=(
            "Cách hiểu phạm vi test sau khi target đã rõ. "
            "'all' nghĩa là user không chỉ rõ chức năng cụ thể. "
            "'specific' nghĩa là user đã chỉ rõ một chức năng/path/module cụ thể. "
            "'invalid_function' nghĩa là user có nói chức năng nhưng không map được vào OpenAPI hints."
        )
    )

    matched_operation_id: str | None = Field(
        default=None,
        description="operation_id đã match được nếu scope_mode='specific'",
    )
    matched_path: str | None = Field(
        default=None,
        description="path đã match được nếu scope_mode='specific'",
    )
    matched_method: str | None = Field(
        default=None,
        description="HTTP method đã match được nếu scope_mode='specific'",
    )
    matched_tag: str | None = Field(
        default=None,
        description="tag/module đã match được nếu scope_mode='specific'",
    )

    invalid_requested_function: str | None = Field(
        default=None,
        description="Phần chức năng user yêu cầu nhưng không tồn tại, dùng khi scope_mode='invalid_function'",
    )

    reason: str = Field(
        description="Giải thích ngắn gọn tại sao agent đưa ra quyết định này"
    )