from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from typing_extensions import NotRequired, TypedDict

from api_testing_agent.tasks.workflow_models import RouterDecision, WorkflowContextSnapshot

AIIntentName = Literal[
    "show_scope_catalog",
    "show_scope_group_details",
    "show_scope_operation_details",
    "ask_scope_recommendation",
    "apply_scope_recommendation",
    "resume_scope_confirmation",
    "show_review_scope",
    "resume_review",
    "continue_report_interaction",
    "start_new_workflow",
    "help",
    "status",
    "clarify",
]

AIFollowupReference = Literal[
    "latest_scope_recommendation",
    "latest_scope_selection",
    "latest_review_context",
    "none",
]

AIScopeFollowupKind = Literal[
    "accept_recommendation",
    "reject_recommendation",
    "refine_recommendation",
    "apply_previous_selection",
    "none",
]


class AIIntentClassification(BaseModel):
    intent: AIIntentName = Field(description="Best intent for the user message.")
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence from 0.0 to 1.0.",
    )
    rationale: str = Field(
        default="",
        description="Short reasoning for the classification.",
    )
    clarification_question: str | None = Field(
        default=None,
        description="Clarification question if intent=clarify or if extra clarification is helpful.",
    )

    followup_reference: AIFollowupReference = Field(
        default="none",
        description=(
            "Whether the user message refers to a prior conversational object, "
            "such as the latest scope recommendation."
        ),
    )
    scope_followup_kind: AIScopeFollowupKind = Field(
        default="none",
        description=(
            "Fine-grained interpretation for scope-related follow-up messages. "
            "For example, whether the user is accepting or refining a previous recommendation."
        ),
    )


class HybridRouterState(TypedDict):
    message: str
    snapshot: WorkflowContextSnapshot | None
    deterministic_decision: NotRequired[RouterDecision | None]
    llm_classification: NotRequired[AIIntentClassification | None]
    final_decision: NotRequired[RouterDecision | None]