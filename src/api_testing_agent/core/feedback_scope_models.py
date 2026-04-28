from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FeedbackScopeDecision(BaseModel):
    action_mode: Literal[
        "keep",
        "reset_all",
        "replace_with_specific",
        "add_specific",
        "remove_specific",
        "invalid_feedback",
    ] = Field(
        description=(
            "Cách feedback của user nên tác động lên phạm vi operation hiện tại.\n"
            "- keep: giữ nguyên\n"
            "- reset_all: quay về full scope\n"
            "- replace_with_specific: thay toàn bộ scope hiện tại bằng một scope cụ thể mới\n"
            "- add_specific: thêm một scope cụ thể vào scope hiện tại\n"
            "- remove_specific: loại bỏ một scope cụ thể khỏi scope hiện tại\n"
            "- invalid_feedback: feedback không map được"
        )
    )

    matched_operation_ids: list[str] = Field(
        default_factory=list,
        description="Danh sách operation_id đã match được từ feedback"
    )
    matched_paths: list[str] = Field(
        default_factory=list,
        description="Danh sách path đã match được từ feedback"
    )
    matched_tags: list[str] = Field(
        default_factory=list,
        description="Danh sách tag/module đã match được từ feedback"
    )

    invalid_feedback_text: str | None = Field(
        default=None,
        description="Phần feedback không map được nếu action_mode='invalid_feedback'"
    )

    reason: str = Field(
        description="Giải thích ngắn gọn tại sao agent đưa ra quyết định này"
    )