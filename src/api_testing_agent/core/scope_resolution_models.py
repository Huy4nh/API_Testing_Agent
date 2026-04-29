from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ScopeResolutionDecision(BaseModel):
    scope_mode: Literal["all", "specific", "invalid_function"] = Field(
        description=(
            "all: user không chỉ rõ chức năng cụ thể\n"
            "specific: user chỉ rõ chức năng hợp lệ\n"
            "invalid_function: user có chỉ chức năng nhưng không map được"
        )
    )

    matched_operation_ids: list[str] = Field(
        default_factory=list,
        description="Danh sách operation_id match được nếu specific",
    )
    matched_paths: list[str] = Field(
        default_factory=list,
        description="Danh sách path match được nếu specific",
    )
    matched_tags: list[str] = Field(
        default_factory=list,
        description="Danh sách tags/modules match được nếu specific",
    )

    invalid_requested_function: str | None = Field(
        default=None,
        description="Tên chức năng user nói nhưng không map được",
    )

    reason: str = Field(
        description="Giải thích ngắn vì sao hệ thống hiểu scope như vậy"
    )