from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from api_testing_agent.logging_config import bind_logger, get_logger
from api_testing_agent.tasks.language_support import (
    SupportedLanguage,
    choose_workflow_language,
    coerce_supported_language,
    detect_user_language,
)



class WorkflowLanguagePolicy(str, Enum):
    ADAPTIVE = "adaptive"
    SESSION_LOCK = "session_lock"


@dataclass(frozen=True)
class WorkflowLanguageDecision:
    language: SupportedLanguage
    policy: WorkflowLanguagePolicy
    changed: bool
    reason: str


class WorkflowLanguagePolicyService:
    def __init__(
        self,
        *,
        default_policy: WorkflowLanguagePolicy = WorkflowLanguagePolicy.ADAPTIVE,
        default_language: SupportedLanguage = "vi",
    ) -> None:
        self._logger = get_logger(__name__)
        self._default_policy: WorkflowLanguagePolicy = default_policy
        self._default_language: SupportedLanguage = default_language

    @property
    def default_policy(self) -> WorkflowLanguagePolicy:
        return self._default_policy

    @property
    def default_language(self) -> SupportedLanguage:
        return self._default_language

    def coerce_policy(
        self,
        value: WorkflowLanguagePolicy | str | None,
    ) -> WorkflowLanguagePolicy:
        if value == WorkflowLanguagePolicy.SESSION_LOCK or value == "session_lock":
            return WorkflowLanguagePolicy.SESSION_LOCK
        if value == WorkflowLanguagePolicy.ADAPTIVE or value == "adaptive":
            return WorkflowLanguagePolicy.ADAPTIVE
        return self._default_policy

    def resolve_initial_language(
        self,
        *,
        user_text: str,
        policy: WorkflowLanguagePolicy | str | None = None,
        thread_id: str | None = None,
    ) -> WorkflowLanguageDecision:
        actual_policy: WorkflowLanguagePolicy = self.coerce_policy(policy)
        detected = detect_user_language(
            user_text,
            fallback=self._default_language,
        )
        resolved: SupportedLanguage = (
            detected if detected is not None else self._default_language
        )

        logger = bind_logger(
            self._logger,
            thread_id=thread_id or "-",
            payload_source="workflow_language_policy_initial",
        )
        logger.info(
            f"Resolved initial language={resolved} with policy={actual_policy.value}."
        )

        return WorkflowLanguageDecision(
            language=resolved,
            policy=actual_policy,
            changed=True,
            reason="Initial workflow language resolved from first user request.",
        )

    def resolve_next_language(
        self,
        *,
        current_language: str,
        incoming_text: str,
        policy: WorkflowLanguagePolicy | str | None = None,
        thread_id: str | None = None,
    ) -> WorkflowLanguageDecision:
        current: SupportedLanguage = coerce_supported_language(
            current_language,
            fallback=self._default_language,
        )
        actual_policy: WorkflowLanguagePolicy = self.coerce_policy(policy)

        logger = bind_logger(
            self._logger,
            thread_id=thread_id or "-",
            payload_source="workflow_language_policy_next",
        )

        if actual_policy == WorkflowLanguagePolicy.SESSION_LOCK:
            logger.info(
                f"Keeping language locked at {current} under policy=session_lock."
            )
            return WorkflowLanguageDecision(
                language=current,
                policy=actual_policy,
                changed=False,
                reason="Language remains locked for this workflow session.",
            )

        next_language: SupportedLanguage = choose_workflow_language(
            incoming_text,
            current,
        )
        changed = next_language != current

        logger.info(
            f"Resolved next language={next_language} from current={current} under policy=adaptive."
        )
        return WorkflowLanguageDecision(
            language=next_language,
            policy=actual_policy,
            changed=changed,
            reason=(
                "Language updated from the latest user message."
                if changed
                else "Language remains unchanged after evaluating the latest user message."
            ),
        )