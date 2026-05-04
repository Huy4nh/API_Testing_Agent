from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from typing_extensions import TypedDict

from api_testing_agent.tasks.language_support import SupportedLanguage


class ReportUserIntent(str, Enum):
    ASK_REPORT_QUESTION = "ask_report_question"
    REVISE_REPORT_TEXT = "revise_report_text"
    REVISE_AND_RERUN = "revise_and_rerun"
    SHARE_REPORT = "share_report"
    FINALIZE_REPORT = "finalize_report"
    CANCEL_REPORT = "cancel_report"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ReportIntentDecision:
    intent: ReportUserIntent
    confidence: float
    reason: str
    revision_instruction: str | None = None
    rerun_instruction: str | None = None


class ReportMessage(TypedDict):
    role: str
    content: str


class ReportInteractionState(TypedDict, total=False):
    # Core identity
    thread_id: str
    target_name: str
    preferred_language: SupportedLanguage

    # Request / review context
    original_request: str | None
    canonical_command: str | None
    understanding_explanation: str | None

    candidate_targets: list[str]
    target_selection_question: str | None
    review_feedback_history: list[str]

    # Draft / execution / validation / final report artifact links
    draft_report_json_path: str | None
    draft_report_md_path: str | None
    execution_report_json_path: str | None
    execution_report_md_path: str | None
    validation_report_json_path: str | None
    validation_report_md_path: str | None

    staged_final_report_json_path: str | None
    staged_final_report_md_path: str | None
    final_report_json_path: str | None
    final_report_md_path: str | None

    # Report payloads / rendered content
    final_report_markdown: str
    final_report_data: dict[str, Any]

    execution_batch_result: Any
    validation_batch_result: Any

    # Conversation state
    messages: list[ReportMessage]
    latest_user_message: str
    assistant_response: str
    shareable_summary: str | None

    # Intent tracking
    last_intent: str
    last_intent_reason: str
    last_intent_confidence: float
    pending_revision_instruction: str | None
    pending_rerun_instruction: str | None

    # Artifact tracking
    artifact_paths: list[str]

    # Session lifecycle
    finalized: bool
    cancelled: bool
    rerun_requested: bool
    rerun_user_text: str | None


@dataclass(frozen=True)
class ReportSessionResult:
    thread_id: str
    target_name: str

    finalized: bool = False
    cancelled: bool = False
    rerun_requested: bool = False

    rerun_user_text: str | None = None
    final_report_json_path: str | None = None
    final_report_md_path: str | None = None
    message: str | None = None
    messages: list[ReportMessage] | None = None