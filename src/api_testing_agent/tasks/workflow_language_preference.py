from __future__ import annotations

from dataclasses import dataclass

from api_testing_agent.logging_config import bind_logger, get_logger
from api_testing_agent.tasks.language_support import SupportedLanguage
from api_testing_agent.tasks.workflow_language_policy import (
    WorkflowLanguageDecision,
    WorkflowLanguagePolicy,
    WorkflowLanguagePolicyService,
)


@dataclass(frozen=True)
class WorkflowLanguagePreferenceResolution:
    preferred_language: SupportedLanguage
    language_policy: WorkflowLanguagePolicy
    reason: str
    explicit_user_selection: bool


class WorkflowLanguagePreferenceResolver:
    def __init__(
        self,
        *,
        policy_service: WorkflowLanguagePolicyService,
    ) -> None:
        self._logger = get_logger(__name__)
        self._policy_service = policy_service

    def resolve_for_workflow_start(
        self,
        *,
        user_text: str,
        selected_language: SupportedLanguage | None = None,
        requested_language_policy: WorkflowLanguagePolicy | str | None = None,
        thread_id: str | None = None,
    ) -> WorkflowLanguagePreferenceResolution:
        logger = bind_logger(
            self._logger,
            thread_id=thread_id or "-",
            payload_source="workflow_language_preference_resolver",
        )

        if selected_language is not None:
            logger.info(
                f"Using explicit selected language={selected_language}; forcing session_lock."
            )
            return WorkflowLanguagePreferenceResolution(
                preferred_language=selected_language,
                language_policy=WorkflowLanguagePolicy.SESSION_LOCK,
                reason="Explicit language selection provided by caller; using session lock.",
                explicit_user_selection=True,
            )

        initial_decision: WorkflowLanguageDecision = (
            self._policy_service.resolve_initial_language(
                user_text=user_text,
                policy=requested_language_policy,
                thread_id=thread_id,
            )
        )
        logger.info(
            f"No explicit language selected; resolved preferred_language={initial_decision.language} "
            f"with policy={initial_decision.policy.value}."
        )
        return WorkflowLanguagePreferenceResolution(
            preferred_language=initial_decision.language,
            language_policy=initial_decision.policy,
            reason="No explicit language selection; resolved from workflow language policy service.",
            explicit_user_selection=False,
        )