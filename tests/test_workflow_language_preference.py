from api_testing_agent.tasks.workflow_language_policy import (
    WorkflowLanguagePolicy,
    WorkflowLanguagePolicyService,
)
from api_testing_agent.tasks.workflow_language_preference import (
    WorkflowLanguagePreferenceResolver,
)


def build_resolver() -> WorkflowLanguagePreferenceResolver:
    service = WorkflowLanguagePolicyService(
        default_policy=WorkflowLanguagePolicy.ADAPTIVE,
        default_language="vi",
    )
    return WorkflowLanguagePreferenceResolver(policy_service=service)


def test_explicit_selected_language_forces_session_lock():
    resolver = build_resolver()

    result = resolver.resolve_for_workflow_start(
        user_text="hãy test API sinh ảnh",
        selected_language="en",
        thread_id="thread-pref-1",
    )

    assert result.preferred_language == "en"
    assert result.language_policy == WorkflowLanguagePolicy.SESSION_LOCK
    assert result.explicit_user_selection is True


def test_no_selected_language_uses_detected_language_and_default_policy():
    resolver = build_resolver()

    result = resolver.resolve_for_workflow_start(
        user_text="please test image generation for img",
        thread_id="thread-pref-2",
    )

    assert result.preferred_language == "en"
    assert result.language_policy == WorkflowLanguagePolicy.ADAPTIVE
    assert result.explicit_user_selection is False