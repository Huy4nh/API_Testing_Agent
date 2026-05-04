from api_testing_agent.tasks.workflow_language_policy import (
    WorkflowLanguagePolicy,
    WorkflowLanguagePolicyService,
)


def test_resolve_initial_language_english():
    service = WorkflowLanguagePolicyService(
        default_policy=WorkflowLanguagePolicy.ADAPTIVE,
        default_language="vi",
    )

    result = service.resolve_initial_language(
        user_text="please test image generation for img",
        thread_id="thread-1",
    )

    assert result.language == "en"
    assert result.policy == WorkflowLanguagePolicy.ADAPTIVE


def test_resolve_initial_language_accepts_explicit_session_lock():
    service = WorkflowLanguagePolicyService(
        default_policy=WorkflowLanguagePolicy.ADAPTIVE,
        default_language="vi",
    )

    result = service.resolve_initial_language(
        user_text="please test image generation for img",
        policy="session_lock",
        thread_id="thread-1b",
    )

    assert result.language == "en"
    assert result.policy == WorkflowLanguagePolicy.SESSION_LOCK


def test_adaptive_policy_switches_language():
    service = WorkflowLanguagePolicyService(
        default_policy=WorkflowLanguagePolicy.ADAPTIVE,
        default_language="vi",
    )

    result = service.resolve_next_language(
        current_language="en",
        incoming_text="giải thích ngắn gọn bằng tiếng Việt",
        policy=WorkflowLanguagePolicy.ADAPTIVE,
        thread_id="thread-2",
    )

    assert result.language == "vi"
    assert result.changed is True


def test_session_lock_policy_keeps_original_language():
    service = WorkflowLanguagePolicyService(
        default_policy=WorkflowLanguagePolicy.ADAPTIVE,
        default_language="vi",
    )

    result = service.resolve_next_language(
        current_language="en",
        incoming_text="giải thích ngắn gọn bằng tiếng Việt",
        policy=WorkflowLanguagePolicy.SESSION_LOCK,
        thread_id="thread-3",
    )

    assert result.language == "en"
    assert result.changed is False