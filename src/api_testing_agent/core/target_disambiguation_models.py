from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TargetCandidate(BaseModel):
    name: str = Field(description="Tên target candidate")
    reason: str = Field(description="Lý do target này phù hợp với yêu cầu người dùng")


class TargetDisambiguationDecision(BaseModel):
    mode: Literal["auto_select", "ask_user", "no_match"] = Field(
        description="Cách hệ thống nên xử lý bước chọn target"
    )
    selected_target: str | None = Field(
        default=None,
        description="Tên target được auto chọn nếu đủ rõ",
    )
    candidates: list[TargetCandidate] = Field(
        default_factory=list,
        description="Danh sách target candidate theo thứ tự gợi ý",
    )
    question: str | None = Field(
        default=None,
        description="Câu hỏi ngắn gọn để hỏi người dùng khi cần chọn target",
    )