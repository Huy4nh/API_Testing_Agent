from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from api_testing_agent.tasks.language_support import SupportedLanguage
from api_testing_agent.tasks.workflow_language_policy import WorkflowLanguagePolicy


class WorkflowPhase(str, Enum):
    IDLE = "idle"
    PENDING_TARGET_SELECTION = "pending_target_selection"
    PENDING_SCOPE_CONFIRMATION = "pending_scope_confirmation"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    EXECUTING = "executing"
    VALIDATING = "validating"
    FINAL_REPORT_STAGED = "final_report_staged"
    REPORT_INTERACTION = "report_interaction"
    FINALIZED = "finalized"
    CANCELLED = "cancelled"
    RERUN_REQUESTED = "rerun_requested"
    ERROR = "error"


class RouterIntent(str, Enum):
    START_NEW_WORKFLOW = "start_new_workflow"
    RESUME_TARGET_SELECTION = "resume_target_selection"
    RESUME_SCOPE_CONFIRMATION = "resume_scope_confirmation"

    SHOW_SCOPE_CATALOG = "show_scope_catalog"
    SHOW_SCOPE_GROUP_DETAILS = "show_scope_group_details"
    SHOW_SCOPE_OPERATION_DETAILS = "show_scope_operation_details"

    ASK_SCOPE_RECOMMENDATION = "ask_scope_recommendation"
    APPLY_SCOPE_RECOMMENDATION = "apply_scope_recommendation"

    RESUME_REVIEW = "resume_review"
    SHOW_REVIEW_SCOPE = "show_review_scope"

    CONTINUE_REPORT_INTERACTION = "continue_report_interaction"

    HELP = "help"
    STATUS = "status"
    CLARIFY = "clarify"
    UNKNOWN = "unknown"


class ScopeSelectionMode(str, Enum):
    ALL = "all"
    GROUPS = "groups"
    OPERATIONS = "operations"
    CUSTOM = "custom"


class ScopeRecommendationMode(str, Enum):
    PRIORITIZE = "prioritize"
    DEPRIORITIZE = "deprioritize"


@dataclass(frozen=True)
class RouterDecision:
    intent: RouterIntent
    confidence: float
    reason: str
    normalized_message: str
    clarification_question: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowScopeCatalogGroup:
    group_id: str
    title: str
    description: str | None = None
    operation_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class WorkflowScopeCatalogOperation:
    operation_id: str
    method: str
    path: str
    group_id: str | None = None
    group_title: str | None = None
    summary: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    auth_required: bool | None = None


@dataclass
class WorkflowScopeRecommendation:
    mode: ScopeRecommendationMode | str | None = None
    group_ids: list[str] = field(default_factory=list)
    operation_ids: list[str] = field(default_factory=list)
    rationale: str | None = None
    follow_up_question: str | None = None
    source_user_message: str | None = None
    rendered_message: str | None = None

    def has_payload(self) -> bool:
        return bool(
            self.group_ids
            or self.operation_ids
            or self.rationale
            or self.follow_up_question
            or self.rendered_message
        )


@dataclass
class WorkflowArtifactRefs:
    draft_report_json_path: str | None = None
    draft_report_md_path: str | None = None
    execution_report_json_path: str | None = None
    execution_report_md_path: str | None = None
    validation_report_json_path: str | None = None
    validation_report_md_path: str | None = None
    staged_final_report_json_path: str | None = None
    staged_final_report_md_path: str | None = None
    final_report_json_path: str | None = None
    final_report_md_path: str | None = None
    artifact_paths: list[str] = field(default_factory=list)

    def merge_artifact_paths(self, new_paths: list[str]) -> None:
        seen = set(self.artifact_paths)
        for item in new_paths:
            cleaned = str(item).strip()
            if not cleaned:
                continue
            if cleaned in seen:
                continue
            seen.add(cleaned)
            self.artifact_paths.append(cleaned)


@dataclass
class WorkflowContextSnapshot:
    workflow_id: str
    thread_id: str
    phase: WorkflowPhase

    original_user_text: str | None = None
    selected_target: str | None = None
    candidate_targets: list[str] = field(default_factory=list)
    selection_question: str | None = None

    canonical_command: str | None = None
    understanding_explanation: str | None = None
    preferred_language: SupportedLanguage = "vi"
    language_policy: WorkflowLanguagePolicy = WorkflowLanguagePolicy.ADAPTIVE

    scope_confirmation_question: str | None = None
    scope_confirmation_summary: str | None = None
    scope_selection_mode: ScopeSelectionMode | None = None

    scope_catalog_groups: list[WorkflowScopeCatalogGroup] = field(default_factory=list)
    scope_catalog_operations: list[WorkflowScopeCatalogOperation] = field(
        default_factory=list
    )

    selected_scope_group_ids: list[str] = field(default_factory=list)
    selected_scope_operation_ids: list[str] = field(default_factory=list)
    excluded_scope_group_ids: list[str] = field(default_factory=list)
    excluded_scope_operation_ids: list[str] = field(default_factory=list)

    scope_confirmation_history: list[str] = field(default_factory=list)

    latest_scope_recommendation: WorkflowScopeRecommendation = field(
        default_factory=WorkflowScopeRecommendation
    )
    applied_scope_recommendation: WorkflowScopeRecommendation = field(
        default_factory=WorkflowScopeRecommendation
    )
    latest_scope_selection_source: str | None = None
    latest_scope_agent_action: str | None = None
    latest_scope_agent_reason: str | None = None
    last_scope_user_message: str | None = None

    review_feedback_history: list[str] = field(default_factory=list)

    artifacts: WorkflowArtifactRefs = field(default_factory=WorkflowArtifactRefs)

    approved_payload: dict[str, Any] | None = None
    final_report_payload: dict[str, Any] | None = None

    execution_batch_result: Any | None = None
    validation_batch_result: Any | None = None

    current_markdown: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    assistant_message_count: int = 0

    finalized: bool = False
    cancelled: bool = False
    rerun_requested: bool = False
    rerun_user_text: str | None = None

    pending_router_clarification: str | None = None
    last_router_reason: str | None = None


@dataclass(frozen=True)
class PostApprovalRuntimeResult:
    approved_payload: dict[str, Any]
    execution_batch_result: Any
    validation_batch_result: Any
    final_report_payload: dict[str, Any]

    execution_report_json_path: str
    execution_report_md_path: str
    validation_report_json_path: str
    validation_report_md_path: str
    staged_final_report_json_path: str
    staged_final_report_md_path: str

    current_markdown: str
    messages: list[dict[str, Any]]
    assistant_messages: list[str]
    assistant_message_count: int
    artifact_paths: list[str]


@dataclass(frozen=True)
class ReportInteractionUpdate:
    thread_id: str
    target_name: str
    assistant_messages: list[str]
    assistant_message_count: int
    current_markdown: str
    messages: list[dict[str, Any]]
    artifact_paths: list[str]

    finalized: bool = False
    cancelled: bool = False
    rerun_requested: bool = False
    rerun_user_text: str | None = None
    final_report_json_path: str | None = None
    final_report_md_path: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class FullWorkflowResult:
    workflow_id: str
    thread_id: str
    phase: WorkflowPhase

    assistant_message: str | None = None
    status_message: str | None = None

    selected_target: str | None = None
    candidate_targets: list[str] = field(default_factory=list)
    selection_question: str | None = None

    canonical_command: str | None = None
    understanding_explanation: str | None = None
    preferred_language: SupportedLanguage = "vi"
    language_policy: WorkflowLanguagePolicy = WorkflowLanguagePolicy.ADAPTIVE

    scope_confirmation_question: str | None = None
    scope_confirmation_summary: str | None = None
    scope_selection_mode: ScopeSelectionMode | None = None

    scope_catalog_groups: list[WorkflowScopeCatalogGroup] = field(default_factory=list)
    scope_catalog_operations: list[WorkflowScopeCatalogOperation] = field(
        default_factory=list
    )

    selected_scope_group_ids: list[str] = field(default_factory=list)
    selected_scope_operation_ids: list[str] = field(default_factory=list)
    excluded_scope_group_ids: list[str] = field(default_factory=list)
    excluded_scope_operation_ids: list[str] = field(default_factory=list)

    latest_scope_recommendation: WorkflowScopeRecommendation = field(
        default_factory=WorkflowScopeRecommendation
    )
    applied_scope_recommendation: WorkflowScopeRecommendation = field(
        default_factory=WorkflowScopeRecommendation
    )
    latest_scope_selection_source: str | None = None
    latest_scope_agent_action: str | None = None
    latest_scope_agent_reason: str | None = None
    last_scope_user_message: str | None = None

    draft_report_json_path: str | None = None
    draft_report_md_path: str | None = None
    execution_report_json_path: str | None = None
    execution_report_md_path: str | None = None
    validation_report_json_path: str | None = None
    validation_report_md_path: str | None = None
    staged_final_report_json_path: str | None = None
    staged_final_report_md_path: str | None = None
    final_report_json_path: str | None = None
    final_report_md_path: str | None = None

    rerun_user_text: str | None = None

    finalized: bool = False
    cancelled: bool = False

    needs_user_input: bool = True
    available_actions: list[str] = field(default_factory=list)