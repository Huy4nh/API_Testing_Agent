from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FeedbackScopeDecision(BaseModel):
    """
    Structured AI decision for review-scope mutation.

    Backward compatible with the old single-action model, but upgraded to support
    compound scope patches such as:
    - "bỏ fb thêm yt vào"
    - "remove auth and add users"
    - "replace current scope with POST /orders and GET /orders/{id}"
    """

    action_mode: Literal[
        "keep",
        "reset_all",
        "replace_with_specific",
        "add_specific",
        "remove_specific",
        "update_scope",
        "mixed_mutation",
        "invalid_feedback",
    ] = Field(
        default="keep",
        description=(
            "The scope action. Use update_scope or mixed_mutation for compound "
            "changes that both add and remove operations."
        ),
    )

    # Legacy / generic matched references.
    matched_operation_ids: list[str] = Field(default_factory=list)
    matched_paths: list[str] = Field(default_factory=list)
    matched_tags: list[str] = Field(default_factory=list)

    # New patch-style references.
    add_operation_ids: list[str] = Field(default_factory=list)
    add_paths: list[str] = Field(default_factory=list)
    add_tags: list[str] = Field(default_factory=list)

    remove_operation_ids: list[str] = Field(default_factory=list)
    remove_paths: list[str] = Field(default_factory=list)
    remove_tags: list[str] = Field(default_factory=list)

    final_operation_ids: list[str] = Field(default_factory=list)
    final_paths: list[str] = Field(default_factory=list)
    final_tags: list[str] = Field(default_factory=list)

    invalid_feedback_text: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""