from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from api_testing_agent.tasks.language_support import SupportedLanguage
from api_testing_agent.tasks.workflow_language_policy import WorkflowLanguagePolicy
from api_testing_agent.tasks.workflow_models import WorkflowPhase


class WorkflowServiceStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class StartWorkflowRequest:
    user_input: str
    session_id: str | None = None
    selected_language: SupportedLanguage | None = None
    language_policy: WorkflowLanguagePolicy | str | None = None


@dataclass(frozen=True)
class ContinueWorkflowRequest:
    thread_id: str
    user_input: str


@dataclass(frozen=True)
class GetWorkflowRequest:
    thread_id: str


@dataclass(frozen=True)
class WorkflowArtifactDTO:
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


@dataclass(frozen=True)
class WorkflowStateDTO:
    workflow_id: str
    thread_id: str
    phase: WorkflowPhase
    selected_target: str | None
    canonical_command: str | None
    understanding_explanation: str | None
    preferred_language: SupportedLanguage
    language_policy: WorkflowLanguagePolicy
    finalized: bool
    cancelled: bool
    needs_user_input: bool
    available_actions: list[str] = field(default_factory=list)
    assistant_message: str | None = None
    status_message: str | None = None
    selection_question: str | None = None
    rerun_user_text: str | None = None
    artifacts: WorkflowArtifactDTO = field(default_factory=WorkflowArtifactDTO)


@dataclass(frozen=True)
class WorkflowServiceResponse:
    status: WorkflowServiceStatus
    state: WorkflowStateDTO | None
    error_message: str | None = None