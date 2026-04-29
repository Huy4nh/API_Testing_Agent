from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TargetCandidate(BaseModel):
    name: str = Field(description="Tên target candidate")
    reason: str = Field(description="Lý do target này phù hợp với yêu cầu user")


class TargetResolutionDecision(BaseModel):
    mode: Literal["auto_select", "ask_user", "no_match"] = Field(
        description="Cách xử lý bước chọn target"
    )
    selected_target: str | None = Field(
        default=None,
        description="Target được chọn nếu auto_select",
    )
    candidates: list[TargetCandidate] = Field(
        default_factory=list,
        description="Danh sách target candidate theo thứ tự gợi ý",
    )
    question: str | None = Field(
        default=None,
        description="Câu hỏi hỏi user khi có nhiều target mơ hồ",
    )
    reason: str = Field(
        description="Giải thích ngắn vì sao hệ thống đưa ra quyết định này"
    )