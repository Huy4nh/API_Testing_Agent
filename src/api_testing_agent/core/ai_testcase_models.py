from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AITestCaseDraft(BaseModel):
    test_type: Literal[
        "positive",
        "missing_required",
        "invalid_type_or_format",
        "unauthorized_or_forbidden",
        "resource_not_found",
    ] = Field(description="Loại test case")

    description: str = Field(description="Mô tả ngắn gọn test case")
    reasoning_summary: str = Field(description="Giải thích ngắn vì sao sinh case này")
    expected_status_reason: str | None = Field(
        default=None,
        description="Giải thích ngắn vì sao kỳ vọng status code như vậy",
    )

    path_params: dict[str, Any] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: dict[str, Any] | None = None

    expected_status_codes: list[int] = Field(default_factory=list)

    skip: bool = Field(default=False)
    skip_reason: str | None = None


class AITestCaseDraftList(BaseModel):
    cases: list[AITestCaseDraft] = Field(default_factory=list)