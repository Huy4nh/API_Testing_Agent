from api_testing_agent.tasks.conversation_router import ConversationRouter
from api_testing_agent.tasks.workflow_models import (
    RouterIntent,
    WorkflowContextSnapshot,
    WorkflowPhase,
)


def build_snapshot(phase: WorkflowPhase) -> WorkflowContextSnapshot:
    return WorkflowContextSnapshot(
        workflow_id="wf-1",
        thread_id="thread-1",
        phase=phase,
        original_user_text="test img staging",
        selected_target="img_api_staging",
        current_markdown="Preview draft here",
        canonical_command="test target img_api_staging /img POST",
        understanding_explanation="Matched POST /img",
    )


def test_route_without_snapshot_starts_new_workflow():
    router = ConversationRouter()

    decision = router.route(
        message="hãy thử chức năng sinh ảnh của img",
        snapshot=None,
    )

    assert decision.intent == RouterIntent.START_NEW_WORKFLOW


def test_route_help_without_snapshot():
    router = ConversationRouter()

    decision = router.route(
        message="help",
        snapshot=None,
    )

    assert decision.intent == RouterIntent.HELP


def test_route_pending_target_selection_resumes_selection():
    router = ConversationRouter()
    snapshot = build_snapshot(WorkflowPhase.PENDING_TARGET_SELECTION)

    decision = router.route(
        message="2",
        snapshot=snapshot,
    )

    assert decision.intent == RouterIntent.RESUME_TARGET_SELECTION


def test_route_pending_review_resumes_review():
    router = ConversationRouter()
    snapshot = build_snapshot(WorkflowPhase.PENDING_REVIEW)

    decision = router.route(
        message="tốt rồi",
        snapshot=snapshot,
    )

    assert decision.intent == RouterIntent.RESUME_REVIEW


def test_route_pending_review_new_task_requires_clarify():
    router = ConversationRouter()
    snapshot = build_snapshot(WorkflowPhase.PENDING_REVIEW)

    decision = router.route(
        message="test target auth_staging module login",
        snapshot=snapshot,
    )

    assert decision.intent == RouterIntent.CLARIFY
    assert decision.clarification_question is not None


def test_route_pending_review_scope_question_returns_show_scope():
    router = ConversationRouter()
    snapshot = build_snapshot(WorkflowPhase.PENDING_REVIEW)

    decision = router.route(
        message="đang có những chức năng nào ?",
        snapshot=snapshot,
    )

    assert decision.intent == RouterIntent.SHOW_REVIEW_SCOPE


def test_route_pending_review_scope_question_without_full_accents_returns_show_scope():
    router = ConversationRouter()
    snapshot = build_snapshot(WorkflowPhase.PENDING_REVIEW)

    decision = router.route(
        message="hiện đang có những chức nang nào",
        snapshot=snapshot,
    )

    assert decision.intent == RouterIntent.SHOW_REVIEW_SCOPE


def test_route_pending_review_scope_question_in_english_returns_show_scope():
    router = ConversationRouter()
    snapshot = build_snapshot(WorkflowPhase.PENDING_REVIEW)

    decision = router.route(
        message="what functions are available?",
        snapshot=snapshot,
    )

    assert decision.intent == RouterIntent.SHOW_REVIEW_SCOPE


def test_route_report_interaction_continues():
    router = ConversationRouter()
    snapshot = build_snapshot(WorkflowPhase.REPORT_INTERACTION)

    decision = router.route(
        message="cho tôi bản tóm tắt dễ hiểu hơn",
        snapshot=snapshot,
    )

    assert decision.intent == RouterIntent.CONTINUE_REPORT_INTERACTION


def test_route_report_interaction_new_task_requires_clarify():
    router = ConversationRouter()
    snapshot = build_snapshot(WorkflowPhase.REPORT_INTERACTION)

    decision = router.route(
        message="hãy thử chức năng login ở staging",
        snapshot=snapshot,
    )

    assert decision.intent == RouterIntent.CLARIFY
    assert decision.clarification_question is not None


def test_route_terminal_phase_can_start_new_workflow():
    router = ConversationRouter()
    snapshot = build_snapshot(WorkflowPhase.FINALIZED)

    decision = router.route(
        message="test target img_api_staging /img POST",
        snapshot=snapshot,
    )

    assert decision.intent == RouterIntent.START_NEW_WORKFLOW