from types import SimpleNamespace
from typing import Any

from api_testing_agent.tasks.full_workflow_orchestrator import FullWorkflowOrchestrator
from api_testing_agent.tasks.orchestrator import ReviewWorkflowResult
from api_testing_agent.tasks.workflow_models import (
    PostApprovalRuntimeResult,
    ReportInteractionUpdate,
    WorkflowPhase,
)
from api_testing_agent.tasks.workflow_state_store import InMemoryWorkflowStateStore
from api_testing_agent.tasks.workflow_language_policy import WorkflowLanguagePolicy
from api_testing_agent.tasks.language_support import SupportedLanguage

class FakeReviewOrchestrator:
    def __init__(self) -> None:
        self.resume_review_calls: list[dict[str, Any]] = []

    def start_review_from_text(self, text: str, *, thread_id: str | None = None) -> ReviewWorkflowResult:
        return ReviewWorkflowResult(
            thread_id=thread_id or "thread-1",
            status="pending_review",
            original_user_text=text,
            selected_target="img_api_staging",
            canonical_command="test target img_api_staging /img POST",
            understanding_explanation="Matched POST /img",
            preview_text="Draft testcase preview here",
            draft_report_json_path="reports/draft.json",
            draft_report_md_path="reports/draft.md",
        )

    def resume_target_selection(self, thread_id: str, *, selection: str) -> ReviewWorkflowResult:
        return ReviewWorkflowResult(
            thread_id=thread_id,
            status="pending_review",
            original_user_text="test request",
            selected_target="img_api_staging",
            canonical_command="test target img_api_staging /img POST",
            understanding_explanation="Matched POST /img",
            preview_text="Draft testcase preview after target selection",
            draft_report_json_path="reports/draft.json",
            draft_report_md_path="reports/draft.md",
            selection_question="Bạn muốn test image generation trên môi trường nào?",
        )

    def resume_review(self, thread_id: str, *, action: str, feedback: str = "") -> ReviewWorkflowResult:
        self.resume_review_calls.append(
            {
                "thread_id": thread_id,
                "action": action,
                "feedback": feedback,
            }
        )
        return ReviewWorkflowResult(
            thread_id=thread_id,
            status="approved",
            original_user_text="test request",
            selected_target="img_api_staging",
            canonical_command="test target img_api_staging /img POST",
            understanding_explanation="Matched POST /img",
            preview_text="Approved preview",
            draft_report_json_path="reports/draft.json",
            draft_report_md_path="reports/draft.md",
            message="Review approved.",
        )

    def get_review_state_values(self, thread_id: str) -> dict[str, Any]:
        return {
            "all_operation_contexts": [
                {
                    "operation_id": "image_generate_img_post",
                    "method": "POST",
                    "path": "/img",
                    "summary": "Image Generate",
                    "tags": ["image"],
                },
                {
                    "operation_id": "fb_get_content_FB_post",
                    "method": "POST",
                    "path": "/FB",
                    "summary": "Fb Get Content",
                    "tags": ["facebook"],
                },
                {
                    "operation_id": "yt_get_content_YT_post",
                    "method": "POST",
                    "path": "/YT",
                    "summary": "Yt Get Content",
                    "tags": ["youtube"],
                },
                {
                    "operation_id": "x_post_post_x_post",
                    "method": "POST",
                    "path": "/post/x",
                    "summary": "X Post",
                    "tags": ["x"],
                },
            ]
        }

    def get_approved_execution_payload(self, thread_id: str) -> dict[str, Any]:
        return {
            "thread_id": thread_id,
            "target": object(),
            "target_name": "img_api_staging",
            "canonical_command": "test target img_api_staging /img POST",
            "understanding_explanation": "Matched POST /img",
            "operation_contexts": [],
            "draft_groups": [],
            "draft_report_json_path": "reports/draft.json",
            "draft_report_md_path": "reports/draft.md",
        }


class FakeReviewOrchestratorSelectionFlow(FakeReviewOrchestrator):
    def start_review_from_text(self, text: str, *, thread_id: str | None = None) -> ReviewWorkflowResult:
        return ReviewWorkflowResult(
            thread_id=thread_id or "thread-1",
            status="pending_target_selection",
            original_user_text=text,
            selected_target=None,
            candidate_targets=["img_local", "img_api_staging", "img_api_prod"],
            selection_question="Bạn muốn test image generation trên môi trường nào?",
        )


class FakeReviewOrchestratorInvalidFunction(FakeReviewOrchestrator):
    def start_review_from_text(self, text: str, *, thread_id: str | None = None) -> ReviewWorkflowResult:
        return ReviewWorkflowResult(
            thread_id=thread_id or "thread-9",
            status="pending_target_selection",
            original_user_text=text,
            selected_target=None,
            candidate_targets=["img_local", "img_api_staging", "img_api_prod"],
            selection_question="Bạn muốn sử dụng chức năng 'abcd' của img trên môi trường nào? (production, staging, hay local)",
        )

    def resume_target_selection(self, thread_id: str, *, selection: str) -> ReviewWorkflowResult:
        return ReviewWorkflowResult(
            thread_id=thread_id,
            status="invalid_function",
            original_user_text="dùng chức năng abcd của img",
            selected_target="img_local",
            available_functions=[
                "POST /img - Generate image from input content.",
                "POST /YT - Extract content from YouTube URL.",
            ],
            message="Không tìm thấy chức năng 'abcd' trong target 'img_local'.",
        )


class FakeRuntimeBridge:
    def __init__(self) -> None:
        self.persist_called = False

    def normalize_review_input(
        self,
        *,
        raw_action: str,
        thread_id: str,
        target_name: str | None,
        preview_text: str,
        feedback_history: list[str],
    ) -> tuple[str, str]:
        return "approve", ""

    def run_post_approval(
        self,
        *,
        approved_payload: dict[str, Any],
        original_request: str,
        candidate_targets_history: list[str],
        target_selection_question: str | None,
        review_feedback_history: list[str],
    ) -> PostApprovalRuntimeResult:
        return PostApprovalRuntimeResult(
            approved_payload=approved_payload,
            execution_batch_result={"kind": "execution_batch"},
            validation_batch_result={"kind": "validation_batch"},
            final_report_payload={
                "summary": {
                    "thread_id": approved_payload["thread_id"],
                    "target_name": approved_payload["target_name"],
                },
                "links": {
                    "final_report_json_path": "reports/_staging/final.json",
                    "final_report_md_path": "reports/_staging/final.md",
                },
            },
            execution_report_json_path="reports/execution.json",
            execution_report_md_path="reports/execution.md",
            validation_report_json_path="reports/validation.json",
            validation_report_md_path="reports/validation.md",
            staged_final_report_json_path="reports/_staging/final.json",
            staged_final_report_md_path="reports/_staging/final.md",
            current_markdown="# Final Workflow Report",
            messages=[{"role": "assistant", "content": "Tôi đã tạo staged final report."}],
            assistant_messages=["Tôi đã tạo staged final report."],
            assistant_message_count=1,
            artifact_paths=["reports/_staging/final.json", "reports/_staging/final.md"],
        )

    def continue_report_interaction(
        self,
        *,
        thread_id: str,
        user_message: str,
        previous_assistant_count: int,
    ) -> ReportInteractionUpdate:
        if user_message.strip().lower() == "lưu":
            return ReportInteractionUpdate(
                thread_id=thread_id,
                target_name="img_api_staging",
                assistant_messages=["Tôi đã chốt final report."],
                assistant_message_count=2,
                current_markdown="# Final Workflow Report\n\nFinalized",
                messages=[
                    {"role": "assistant", "content": "Tôi đã tạo staged final report."},
                    {"role": "assistant", "content": "Tôi đã chốt final report."},
                ],
                artifact_paths=["reports/final/final.json", "reports/final/final.md"],
                finalized=True,
                final_report_json_path="reports/final/final.json",
                final_report_md_path="reports/final/final.md",
            )

        return ReportInteractionUpdate(
            thread_id=thread_id,
            target_name="img_api_staging",
            assistant_messages=["Đây là bản giải thích report."],
            assistant_message_count=2,
            current_markdown="# Final Workflow Report\n\nRewritten",
            messages=[
                {"role": "assistant", "content": "Tôi đã tạo staged final report."},
                {"role": "assistant", "content": "Đây là bản giải thích report."},
            ],
            artifact_paths=["reports/_staging/final.json", "reports/_staging/final.md"],
            finalized=False,
            cancelled=False,
            rerun_requested=False,
        )

    def persist_finalized_run(
        self,
        *,
        final_report_payload: dict[str, Any],
        finalized_final_report_json_path: str | None,
        finalized_final_report_md_path: str,
        execution_batch_result: Any,
        validation_batch_result: Any,
        messages: list[dict[str, Any]],
    ) -> None:
        self.persist_called = True


class FakeRuntimeBridgeCancel(FakeRuntimeBridge):
    def continue_report_interaction(
        self,
        *,
        thread_id: str,
        user_message: str,
        previous_assistant_count: int,
    ) -> ReportInteractionUpdate:
        return ReportInteractionUpdate(
            thread_id=thread_id,
            target_name="img_api_staging",
            assistant_messages=["Workflow đã bị hủy."],
            assistant_message_count=2,
            current_markdown="",
            messages=[
                {"role": "assistant", "content": "Tôi đã tạo staged final report."},
                {"role": "assistant", "content": "Workflow đã bị hủy."},
            ],
            artifact_paths=[],
            finalized=False,
            cancelled=True,
            rerun_requested=False,
            final_report_json_path=None,
            final_report_md_path=None,
        )


class FakeRuntimeBridgeRaiseOnPostApproval(FakeRuntimeBridge):
    def run_post_approval(
        self,
        *,
        approved_payload: dict[str, Any],
        original_request: str,
        candidate_targets_history: list[str],
        target_selection_question: str | None,
        review_feedback_history: list[str],
    ) -> PostApprovalRuntimeResult:
        raise RuntimeError("post approval exploded")


def build_settings() -> Any:
    return SimpleNamespace(
        report_output_dir="./reports",
        target_registry_path="./targets.json",
        http_timeout_seconds=5,
        sqlite_path="./data/runs.sqlite3",
        langchain_model_name="dummy-model",
        langchain_model_provider=None,
        langgraph_checkpointer="memory",
        langgraph_sqlite_path="./data/langgraph.sqlite3",
    )


def test_start_from_text_creates_pending_review_workflow():
    settings = build_settings()
    review = FakeReviewOrchestrator()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    orchestrator = FullWorkflowOrchestrator(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    result = orchestrator.start_from_text("hãy thử chức năng sinh ảnh của img", thread_id="thread-1")

    assert result.thread_id == "thread-1"
    assert result.phase == WorkflowPhase.PENDING_REVIEW
    assert result.selected_target == "img_api_staging"
    assert result.draft_report_md_path == "reports/draft.md"
    assert result.assistant_message is not None


def test_continue_review_approve_moves_to_report_interaction():
    settings = build_settings()
    review = FakeReviewOrchestrator()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    orchestrator = FullWorkflowOrchestrator(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    orchestrator.start_from_text("hãy thử chức năng sinh ảnh của img", thread_id="thread-2")
    result = orchestrator.continue_with_message(thread_id="thread-2", message="tốt")

    assert review.resume_review_calls[0]["action"] == "approve"
    assert result.phase == WorkflowPhase.REPORT_INTERACTION
    assert result.execution_report_md_path == "reports/execution.md"
    assert result.validation_report_md_path == "reports/validation.md"
    assert result.staged_final_report_md_path == "reports/_staging/final.md"
    assert result.assistant_message is not None


def test_report_interaction_finalize_persists():
    settings = build_settings()
    review = FakeReviewOrchestrator()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    orchestrator = FullWorkflowOrchestrator(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    orchestrator.start_from_text("hãy thử chức năng sinh ảnh của img", thread_id="thread-3")
    orchestrator.continue_with_message(thread_id="thread-3", message="tốt")
    result = orchestrator.continue_with_message(thread_id="thread-3", message="lưu")

    assert result.phase == WorkflowPhase.FINALIZED
    assert result.finalized is True
    assert result.final_report_json_path == "reports/final/final.json"
    assert result.final_report_md_path == "reports/final/final.md"
    assert bridge.persist_called is True


def test_help_and_status_do_not_break_workflow():
    settings = build_settings()
    review = FakeReviewOrchestrator()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    orchestrator = FullWorkflowOrchestrator(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    orchestrator.start_from_text("hãy thử chức năng sinh ảnh của img", thread_id="thread-4")

    help_result = orchestrator.continue_with_message(thread_id="thread-4", message="help")
    status_result = orchestrator.continue_with_message(thread_id="thread-4", message="đang ở bước nào")

    assert help_result.phase == WorkflowPhase.PENDING_REVIEW
    assert help_result.assistant_message is not None

    assert status_result.phase == WorkflowPhase.PENDING_REVIEW
    assert status_result.assistant_message is not None


def test_report_interaction_cancel_clears_artifact_refs():
    settings = build_settings()
    review = FakeReviewOrchestrator()
    bridge = FakeRuntimeBridgeCancel()
    store = InMemoryWorkflowStateStore()

    orchestrator = FullWorkflowOrchestrator(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    orchestrator.start_from_text("hãy thử chức năng sinh ảnh của img", thread_id="thread-5")
    orchestrator.continue_with_message(thread_id="thread-5", message="tốt")

    before_cancel_snapshot = orchestrator.get_snapshot("thread-5")
    assert before_cancel_snapshot is not None
    assert before_cancel_snapshot.phase == WorkflowPhase.REPORT_INTERACTION
    assert before_cancel_snapshot.artifacts.staged_final_report_json_path == "reports/_staging/final.json"
    assert before_cancel_snapshot.artifacts.staged_final_report_md_path == "reports/_staging/final.md"
    assert len(before_cancel_snapshot.artifacts.artifact_paths) > 0

    result = orchestrator.continue_with_message(thread_id="thread-5", message="hủy")

    assert result.phase == WorkflowPhase.CANCELLED
    assert result.cancelled is True
    assert result.finalized is False
    assert result.staged_final_report_json_path is None
    assert result.staged_final_report_md_path is None
    assert result.final_report_json_path is None
    assert result.final_report_md_path is None

    after_cancel_snapshot = orchestrator.get_snapshot("thread-5")
    assert after_cancel_snapshot is not None
    assert after_cancel_snapshot.phase == WorkflowPhase.CANCELLED
    assert after_cancel_snapshot.artifacts.staged_final_report_json_path is None
    assert after_cancel_snapshot.artifacts.staged_final_report_md_path is None
    assert after_cancel_snapshot.artifacts.final_report_json_path is None
    assert after_cancel_snapshot.artifacts.final_report_md_path is None
    assert after_cancel_snapshot.artifacts.artifact_paths == []


def test_post_approval_exception_marks_workflow_error():
    settings = build_settings()
    review = FakeReviewOrchestrator()
    bridge = FakeRuntimeBridgeRaiseOnPostApproval()
    store = InMemoryWorkflowStateStore()

    orchestrator = FullWorkflowOrchestrator(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    orchestrator.start_from_text("hãy thử chức năng sinh ảnh của img", thread_id="thread-6")
    result = orchestrator.continue_with_message(thread_id="thread-6", message="tốt")

    assert result.phase == WorkflowPhase.ERROR
    assert result.assistant_message is not None


def test_pending_review_scope_question_lists_functions_in_english():
    settings = build_settings()
    review = FakeReviewOrchestrator()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    orchestrator = FullWorkflowOrchestrator(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    orchestrator.start_from_text("please test image generation for img", thread_id="thread-7")
    result = orchestrator.continue_with_message(thread_id="thread-7", message="what functions are available?")

    assert result.phase == WorkflowPhase.PENDING_REVIEW
    assert result.assistant_message is not None
    assert "here is the current review scope" in result.assistant_message.lower()
    assert "available functions in target" in result.assistant_message.lower()
    assert "post /img" in result.assistant_message.lower()
    assert "description: generate an image from the provided content." in result.assistant_message.lower()
    assert "description: retrieve content from facebook." in result.assistant_message.lower()
    assert "description: retrieve content from youtube." in result.assistant_message.lower()
    assert "description: publish a post to x." in result.assistant_message.lower()
    assert review.resume_review_calls == []


def test_selection_question_is_cleared_after_target_selection():
    settings = build_settings()
    review = FakeReviewOrchestratorSelectionFlow()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    orchestrator = FullWorkflowOrchestrator(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    result_1 = orchestrator.start_from_text("hãy thử chức năng sinh ảnh của img", thread_id="thread-8")
    assert result_1.phase == WorkflowPhase.PENDING_TARGET_SELECTION
    assert result_1.selection_question is not None

    result_2 = orchestrator.continue_with_message(thread_id="thread-8", message="2")
    assert result_2.phase == WorkflowPhase.PENDING_REVIEW
    assert result_2.selected_target == "img_api_staging"
    assert result_2.selection_question is None


def test_invalid_function_lists_available_functions():
    settings = build_settings()
    review = FakeReviewOrchestratorInvalidFunction()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    orchestrator = FullWorkflowOrchestrator(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    result_1 = orchestrator.start_from_text("please use function abcd of img", thread_id="thread-9")
    assert result_1.phase == WorkflowPhase.PENDING_TARGET_SELECTION

    result_2 = orchestrator.continue_with_message(thread_id="thread-9", message="local")

    assert result_2.phase == WorkflowPhase.ERROR
    assert result_2.assistant_message is not None
    assert "available functions in target `img_local`" in result_2.assistant_message.lower()
    assert "post /img" in result_2.assistant_message.lower()
    assert "post /yt" in result_2.assistant_message.lower()

class FakeReviewOrchestratorVietnamesePendingReview(FakeReviewOrchestrator):
    def start_review_from_text(self, text: str, *, thread_id: str | None = None) -> ReviewWorkflowResult:
        return ReviewWorkflowResult(
            thread_id=thread_id or "thread-en-1",
            status="pending_review",
            original_user_text=text,
            selected_target="img_local",
            canonical_command="test target img_local /img POST positive missing invalid",
            understanding_explanation="Đã xác định target là 'img_local' và đã match đúng chức năng cụ thể: POST /img.",
            preview_text=(
                "Review round: 1\n"
                "Original request: test img generate of img\n"
                "Canonical command: test target img_local /img POST positive missing invalid\n"
                "Understanding: Đã xác định target là 'img_local' và đã match đúng chức năng cụ thể: POST /img.\n"
                "Active operations: POST /img\n\n"
                "1. POST /img (operation_id=image_generate_img_post)\n"
                "   1. [positive] POST /img với content hợp lệ (URL), prompt và quality tùy chọn\n"
                "      why: Gửi request hợp lệ với trường required 'content' là URL, kèm prompt và quality để kiểm tra response thành công.\n"
                "      expect: [200]\n"
            ),
            draft_report_json_path="reports/draft.json",
            draft_report_md_path="reports/draft.md",
        )

def test_english_request_localizes_vietnamese_review_fields():
    settings = build_settings()
    review = FakeReviewOrchestratorVietnamesePendingReview()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    orchestrator = FullWorkflowOrchestrator(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    result = orchestrator.start_from_text(
        "please test image generation for img",
        thread_id="thread-en-1",
    )

    assert result.phase == WorkflowPhase.PENDING_REVIEW
    assert result.preferred_language == "en"
    assert result.language_policy.value == "adaptive"
    assert result.assistant_message is not None
    assert "identified the target as 'img_local'" in result.assistant_message.lower()
    assert "post /img with valid content (url), prompt, and optional quality" in result.assistant_message.lower()
    
def test_explicit_session_lock_keeps_english_on_vietnamese_follow_up():
    settings = build_settings()
    review = FakeReviewOrchestratorVietnamesePendingReview()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    orchestrator = FullWorkflowOrchestrator(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    result_1 = orchestrator.start_from_text(
        "please test image generation for img",
        thread_id="thread-policy-lock-1",
        language_policy=WorkflowLanguagePolicy.SESSION_LOCK,
    )

    assert result_1.preferred_language == "en"
    assert result_1.language_policy == WorkflowLanguagePolicy.SESSION_LOCK

    result_2 = orchestrator.continue_with_message(
        thread_id="thread-policy-lock-1",
        message="đang ở bước nào",
    )

    assert result_2.preferred_language == "en"
    assert result_2.language_policy == WorkflowLanguagePolicy.SESSION_LOCK
    assert result_2.assistant_message is not None
    assert "is currently in phase" in result_2.assistant_message.lower()


def test_explicit_adaptive_allows_switch_to_vietnamese_on_follow_up():
    settings = build_settings()
    review = FakeReviewOrchestratorVietnamesePendingReview()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    orchestrator = FullWorkflowOrchestrator(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    result_1 = orchestrator.start_from_text(
        "please test image generation for img",
        thread_id="thread-policy-adaptive-1",
        language_policy=WorkflowLanguagePolicy.ADAPTIVE,
    )

    assert result_1.preferred_language == "en"
    assert result_1.language_policy == WorkflowLanguagePolicy.ADAPTIVE

    result_2 = orchestrator.continue_with_message(
        thread_id="thread-policy-adaptive-1",
        message="đang ở bước nào",
    )

    assert result_2.preferred_language == "vi"
    assert result_2.language_policy == WorkflowLanguagePolicy.ADAPTIVE
    assert result_2.assistant_message is not None
    assert "đang ở phase" in result_2.assistant_message.lower()
    
def test_selected_language_en_forces_session_lock_on_workflow_start():
    settings = build_settings()
    review = FakeReviewOrchestratorVietnamesePendingReview()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    orchestrator = FullWorkflowOrchestrator(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    result = orchestrator.start_from_text(
        "hãy test API sinh ảnh",
        thread_id="thread-selected-lang-1",
        selected_language="en",
    )

    assert result.preferred_language == "en"
    assert result.language_policy == WorkflowLanguagePolicy.SESSION_LOCK
    assert result.assistant_message is not None
    assert "img_local" in result.assistant_message.lower()
    assert "matched the intended function: post /img" in result.assistant_message.lower()


def test_selected_language_vi_forces_session_lock_on_english_input():
    settings = build_settings()
    review = FakeReviewOrchestratorVietnamesePendingReview()
    bridge = FakeRuntimeBridge()
    store = InMemoryWorkflowStateStore()

    orchestrator = FullWorkflowOrchestrator(
        settings=settings,
        review_orchestrator=review,
        runtime_bridge=bridge,
        state_store=store,
    )

    result = orchestrator.start_from_text(
        "please test image generation for img",
        thread_id="thread-selected-lang-2",
        selected_language="vi",
    )

    assert result.preferred_language == "vi"
    assert result.language_policy == WorkflowLanguagePolicy.SESSION_LOCK