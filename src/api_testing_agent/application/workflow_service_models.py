from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from api_testing_agent.tasks.language_support import SupportedLanguage
from api_testing_agent.tasks.workflow_language_policy import WorkflowLanguagePolicy


class WorkflowErrorCode(str, Enum):
    """
    Error code ổn định cho mọi adapter.

    Lý do dùng Enum:
    - REST API có thể map sang HTTP status code.
    - Telegram/Web có thể map sang message thân thiện.
    - Test dễ assert hơn so với string rời rạc.
    """

    INVALID_INPUT = "INVALID_INPUT"
    WORKFLOW_NOT_FOUND = "WORKFLOW_NOT_FOUND"
    INVALID_PHASE_ACTION = "INVALID_PHASE_ACTION"

    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    SCOPE_SELECTION_INVALID = "SCOPE_SELECTION_INVALID"

    FINALIZE_NOT_ALLOWED = "FINALIZE_NOT_ALLOWED"
    CANCEL_NOT_ALLOWED = "CANCEL_NOT_ALLOWED"
    RERUN_NOT_ALLOWED = "RERUN_NOT_ALLOWED"

    INTERNAL_WORKFLOW_ERROR = "INTERNAL_WORKFLOW_ERROR"


@dataclass(frozen=True)
class WorkflowActorContext:
    """
    Metadata người gọi workflow.

    Hiện tại có thể optional, nhưng contract nên có sẵn từ Bước 9 để sau này
    adapter thật như Telegram/Web/REST/API Gateway có chỗ truyền identity vào.

    - actor_id: định danh actor tổng quát, có thể là telegram_user_id, api_key_owner...
    - session_id: session phía adapter.
    - user_id: user nội bộ khi có auth system.
    - org_id: organization/tenant.
    """

    actor_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    org_id: str | None = None


@dataclass(frozen=True)
class StartWorkflowRequest:
    """
    Request mở workflow mới.

    thread_id optional để adapter có thể chủ động gắn thread/session id.
    Nếu None, FullWorkflowOrchestrator sẽ tự sinh thread_id.
    """

    text: str
    actor_context: WorkflowActorContext = field(default_factory=WorkflowActorContext)
    thread_id: str | None = None
    language_policy: WorkflowLanguagePolicy | str | None = None
    selected_language: SupportedLanguage | None = None


@dataclass(frozen=True)
class ContinueWorkflowRequest:
    """
    Request tiếp tục workflow hiện tại bằng message hội thoại.
    """

    thread_id: str
    message: str
    actor_context: WorkflowActorContext = field(default_factory=WorkflowActorContext)


@dataclass(frozen=True)
class FinalizeWorkflowRequest:
    """
    Finalize workflow theo semantic API.

    Trong bản Bước 9 hiện tại, service vẫn bridge qua text message vì
    FullWorkflowOrchestrator chưa có method finalize(thread_id) riêng.

    auto_confirm=True giúp adapter headless có thể finalize qua một call.
    """

    thread_id: str
    actor_context: WorkflowActorContext = field(default_factory=WorkflowActorContext)
    auto_confirm: bool = True
    finalize_message: str = "lưu"
    confirmation_message: str = "đồng ý"


@dataclass(frozen=True)
class CancelWorkflowRequest:
    """
    Cancel workflow theo semantic API.

    Giống finalize, hiện tại vẫn bridge qua message "hủy" để tương thích
    với FullWorkflowOrchestrator hiện có.
    """

    thread_id: str
    actor_context: WorkflowActorContext = field(default_factory=WorkflowActorContext)
    auto_confirm: bool = True
    cancel_message: str = "hủy"
    confirmation_message: str = "đồng ý"


@dataclass(frozen=True)
class RerunWorkflowRequest:
    """
    Request tạo rerun từ phase report_interaction.

    instruction là yêu cầu thay đổi scope/testcase cho lần chạy lại.
    """

    thread_id: str
    instruction: str
    actor_context: WorkflowActorContext = field(default_factory=WorkflowActorContext)


@dataclass(frozen=True)
class WorkflowArtifactView:
    """
    Artifact view chuẩn cho adapter.

    Hiện tại path là filesystem path. Sau này có thể đổi storage_backend thành:
    - s3
    - gcs
    - minio
    - database
    mà không cần đổi contract adapter.
    """

    artifact_type: str
    path: str
    stage: str
    storage_backend: str = "filesystem"


@dataclass(frozen=True)
class WorkflowView:
    """
    View ngắn gọn cho adapter hiển thị sau mỗi action.

    Đây là response chính cho start/continue/finalize/cancel/rerun.
    """

    workflow_id: str
    thread_id: str
    phase: str
    current_target: str | None = None

    assistant_message: str | None = None
    status_message: str | None = None

    selected_target: str | None = None
    candidate_targets: list[str] = field(default_factory=list)
    selection_question: str | None = None

    scope_confirmation_question: str | None = None
    scope_confirmation_summary: str | None = None

    canonical_command: str | None = None
    understanding_explanation: str | None = None

    preferred_language: str = "vi"
    language_policy: str = WorkflowLanguagePolicy.ADAPTIVE.value

    available_actions: list[str] = field(default_factory=list)
    needs_user_input: bool = True

    finalized: bool = False
    cancelled: bool = False
    rerun_requested: bool = False
    rerun_user_text: str | None = None

    artifacts: list[WorkflowArtifactView] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowSnapshotView:
    """
    View đầy đủ hơn cho debug/admin/dashboard.

    Không expose raw WorkflowContextSnapshot để tránh adapter phụ thuộc vào
    internal structure của orchestrator.
    """

    workflow_id: str
    thread_id: str
    current_phase: str
    current_subphase: str | None = None
    current_target: str | None = None

    original_user_text: str | None = None
    selected_target: str | None = None
    candidate_targets: list[str] = field(default_factory=list)

    canonical_command: str | None = None
    understanding_explanation: str | None = None

    preferred_language: str = "vi"
    language_policy: str = WorkflowLanguagePolicy.ADAPTIVE.value

    finalized: bool = False
    cancelled: bool = False
    rerun_requested: bool = False
    rerun_user_text: str | None = None

    pending_question: str | None = None
    last_router_decision: str | None = None
    last_scope_user_message: str | None = None

    artifact_refs: list[WorkflowArtifactView] = field(default_factory=list)

    active_review_id: str | None = None
    active_report_session_id: str | None = None


@dataclass(frozen=True)
class WorkflowErrorResponse:
    """
    Error contract chuẩn.

    Không để exception thò ra adapter. Adapter chỉ cần đọc:
    - error_code
    - error_message
    - recoverable
    - suggested_next_actions
    """

    error_code: WorkflowErrorCode
    error_message: str
    recoverable: bool
    suggested_next_actions: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowServiceResponse:
    """
    Response contract duy nhất cho HeadlessWorkflowService.

    ok=True:
      - workflow hoặc snapshot/artifacts có data.

    ok=False:
      - error có WorkflowErrorResponse.
    """

    ok: bool
    operation: str
    actor_context: WorkflowActorContext = field(default_factory=WorkflowActorContext)

    workflow: WorkflowView | None = None
    snapshot: WorkflowSnapshotView | None = None
    artifacts: list[WorkflowArtifactView] = field(default_factory=list)

    error: WorkflowErrorResponse | None = None