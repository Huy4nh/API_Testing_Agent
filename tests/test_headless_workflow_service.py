from api_testing_agent.application.headless_workflow_service import HeadlessWorkflowService
from api_testing_agent.application.workflow_service_models import (
    ContinueWorkflowRequest,
    GetWorkflowRequest,
    StartWorkflowRequest,
    WorkflowServiceStatus,
)
from api_testing_agent.tasks.workflow_language_policy import WorkflowLanguagePolicy
from api_testing_agent.tasks.workflow_state_store import InMemoryWorkflowStateStore

from tests.test_full_workflow_orchestrator import (
    FakeReviewOrchestratorVietnamesePendingReview,
    FakeRuntimeBridge,
    build_settings,
)


def test_headless_service_can_start_workflow():
    settings = build_settings()
    review = FakeReviewOrchestratorVietnamesePendingReview()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    service = HeadlessWorkflowService(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    response = service.start_workflow(
        StartWorkflowRequest(
            user_input="please test image generation for img",
            session_id="svc-thread-1",
        )
    )

    assert response.status == WorkflowServiceStatus.OK
    assert response.state is not None
    assert response.state.thread_id == "svc-thread-1"
    assert response.state.preferred_language == "en"
    assert response.state.language_policy == WorkflowLanguagePolicy.ADAPTIVE
    assert response.state.phase.value == "pending_review"


def test_headless_service_can_start_with_selected_language():
    settings = build_settings()
    review = FakeReviewOrchestratorVietnamesePendingReview()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    service = HeadlessWorkflowService(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    response = service.start_workflow(
        StartWorkflowRequest(
            user_input="hãy test API sinh ảnh",
            session_id="svc-thread-2",
            selected_language="en",
        )
    )

    assert response.status == WorkflowServiceStatus.OK
    assert response.state is not None
    assert response.state.preferred_language == "en"
    assert response.state.language_policy == WorkflowLanguagePolicy.SESSION_LOCK


def test_headless_service_can_continue_workflow():
    settings = build_settings()
    review = FakeReviewOrchestratorVietnamesePendingReview()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    service = HeadlessWorkflowService(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    start_response = service.start_workflow(
        StartWorkflowRequest(
            user_input="please test image generation for img",
            session_id="svc-thread-3",
            language_policy=WorkflowLanguagePolicy.ADAPTIVE,
        )
    )
    assert start_response.status == WorkflowServiceStatus.OK

    continue_response = service.continue_workflow(
        ContinueWorkflowRequest(
            thread_id="svc-thread-3",
            user_input="đang ở bước nào",
        )
    )

    assert continue_response.status == WorkflowServiceStatus.OK
    assert continue_response.state is not None
    assert continue_response.state.thread_id == "svc-thread-3"
    assert continue_response.state.preferred_language == "vi"


def test_headless_service_returns_not_found_for_unknown_thread():
    settings = build_settings()
    review = FakeReviewOrchestratorVietnamesePendingReview()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    service = HeadlessWorkflowService(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    response = service.get_workflow_status(
        GetWorkflowRequest(thread_id="missing-thread")
    )

    assert response.status == WorkflowServiceStatus.NOT_FOUND
    assert response.state is None
    assert response.error_message is not None