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
            "keep: giữ nguyên\n"
            "reset_all: quay về test toàn bộ\n"
            "replace_with_specific: thay scope hiện tại bằng scope mới\n"
            "add_specific: thêm scope mới vào scope hiện tại\n"
            "remove_specific: bỏ một phần scope khỏi scope hiện tại\n"
            "invalid_feedback: feedback không map được"
        )
    )

    matched_operation_ids: list[str] = Field(default_factory=list)
    matched_paths: list[str] = Field(default_factory=list)
    matched_tags: list[str] = Field(default_factory=list)

    invalid_feedback_text: str | None = Field(
        default=None,
        description="Phần feedback không hiểu được nếu invalid_feedback"
    )

    reason: str = Field(
        description="Giải thích ngắn vì sao hệ thống hiểu feedback như vậy"
    )