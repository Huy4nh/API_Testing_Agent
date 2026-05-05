from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from api_testing_agent.application.headless_workflow_service import HeadlessWorkflowService
from api_testing_agent.application.workflow_service_models import (
    CancelWorkflowRequest,
    ContinueWorkflowRequest,
    FinalizeWorkflowRequest,
    RerunWorkflowRequest,
    StartWorkflowRequest,
    WorkflowActorContext,
    WorkflowServiceResponse,
)
from api_testing_agent.config import Settings
from api_testing_agent.logging_config import get_logger, setup_logging
from api_testing_agent.tasks.language_support import SupportedLanguage
from api_testing_agent.tasks.workflow_language_policy import WorkflowLanguagePolicy


setup_logging()
logger = get_logger(__name__)

settings = Settings()
service = HeadlessWorkflowService(settings)


OPENAPI_TAGS = [
    {
        "name": "Health",
        "description": "Health check and service availability endpoints.",
    },
    {
        "name": "Workflows",
        "description": "Create and continue API testing workflows.",
    },
    {
        "name": "Workflow Read-Only",
        "description": (
            "Read-only workflow endpoints. These endpoints must not mutate "
            "workflow state, router history, or artifacts."
        ),
    },
    {
        "name": "Workflow Actions",
        "description": (
            "Semantic workflow actions such as finalize, cancel, and rerun."
        ),
    },
]


app = FastAPI(
    title="API Testing Agent Headless Workflow API",
    version="0.1.0",
    description=(
        "Thin REST adapter for HeadlessWorkflowService. "
        "This API exposes the API testing workflow through stable HTTP endpoints. "
        "The REST layer must stay thin and must not call workflow core or "
        "orchestrator internals directly."
    ),
    openapi_tags=OPENAPI_TAGS,
)


class ActorContextIn(BaseModel):
    """
    Caller metadata.

    These fields are optional for local demo, but they prepare the API contract
    for future authentication, multi-user sessions, and organization-level usage.
    """

    actor_id: str | None = Field(
        default=None,
        description="Generic actor identifier, such as API client, bot user, or CLI user.",
        examples=["local_rest", "telegram_user_123", "demo_script"],
    )
    session_id: str | None = Field(
        default=None,
        description="Adapter-level session identifier.",
        examples=["rest_manual_test", "telegram_chat_123"],
    )
    user_id: str | None = Field(
        default=None,
        description="Internal authenticated user id. Optional for local/demo mode.",
        examples=["local_user"],
    )
    org_id: str | None = Field(
        default=None,
        description="Organization or tenant id. Optional for local/demo mode.",
        examples=["local_org"],
    )


class StartWorkflowIn(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        description="Initial natural-language request from the user.",
        examples=["test img", "test target img_api_staging module image POST"],
    )
    thread_id: str | None = Field(
        default=None,
        description="Optional thread id supplied by external adapter. Usually omitted.",
        examples=["wf-custom-thread-id"],
    )
    language_policy: str | None = Field(
        default=None,
        description="Optional language policy, such as adaptive or session_lock.",
        examples=["adaptive"],
    )
    selected_language: str | None = Field(
        default=None,
        description="Optional selected language. Supported values: vi, en.",
        examples=["vi"],
    )
    actor_context: ActorContextIn = Field(
        default_factory=ActorContextIn,
        description="Caller/session metadata.",
    )


class ContinueWorkflowIn(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        description="Next user message for the active workflow.",
        examples=["product", "chi test operation POST /img, khong test endpoint khac", "approve"],
    )
    actor_context: ActorContextIn = Field(
        default_factory=ActorContextIn,
        description="Caller/session metadata.",
    )


class FinalizeWorkflowIn(BaseModel):
    auto_confirm: bool = Field(
        default=True,
        description="If true, the service may auto-confirm finalize confirmation prompts.",
    )
    finalize_message: str = Field(
        default="luu",
        description="Message sent to the workflow to request finalization.",
        examples=["luu", "done", "finalize"],
    )
    confirmation_message: str = Field(
        default="dong y",
        description="Confirmation message used when auto_confirm is enabled.",
        examples=["dong y", "yes"],
    )
    actor_context: ActorContextIn = Field(
        default_factory=ActorContextIn,
        description="Caller/session metadata.",
    )


class CancelWorkflowIn(BaseModel):
    auto_confirm: bool = Field(
        default=True,
        description="If true, the service may auto-confirm cancel confirmation prompts.",
    )
    cancel_message: str = Field(
        default="huy",
        description="Message sent to the workflow to request cancellation.",
        examples=["huy", "cancel", "stop"],
    )
    confirmation_message: str = Field(
        default="dong y",
        description="Confirmation message used when auto_confirm is enabled.",
        examples=["dong y", "yes"],
    )
    actor_context: ActorContextIn = Field(
        default_factory=ActorContextIn,
        description="Caller/session metadata.",
    )


class RerunWorkflowIn(BaseModel):
    instruction: str = Field(
        ...,
        min_length=1,
        description="Rerun instruction from report interaction phase.",
        examples=["run again with only positive cases", "bo YT va chi test positive"],
    )
    actor_context: ActorContextIn = Field(
        default_factory=ActorContextIn,
        description="Caller/session metadata.",
    )


def is_dataclass_instance(value: Any) -> bool:
    """
    Pylance-friendly dataclass instance check.

    dataclasses.is_dataclass(value) returns True for both dataclass classes and
    dataclass instances. asdict() only accepts dataclass instances.
    """
    return is_dataclass(value) and not isinstance(value, type)


def json_safe(value: Any) -> Any:
    """
    Convert dataclass/Enum/Path/set/tuple/list/dict into JSON-safe objects.
    """
    if is_dataclass_instance(value):
        return json_safe(asdict(value))

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, list):
        return [json_safe(item) for item in value]

    if isinstance(value, tuple):
        return [json_safe(item) for item in value]

    if isinstance(value, set):
        return sorted(json_safe(item) for item in value)

    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}

    return value


def to_actor_context(payload: ActorContextIn | None) -> WorkflowActorContext:
    if payload is None:
        return WorkflowActorContext()

    return WorkflowActorContext(
        actor_id=payload.actor_id,
        session_id=payload.session_id,
        user_id=payload.user_id,
        org_id=payload.org_id,
    )


def to_language_policy(value: str | None) -> WorkflowLanguagePolicy | str | None:
    """
    Convert raw string from REST payload to WorkflowLanguagePolicy when possible.

    If it does not match the enum, return the original string for compatibility
    with the workflow layer.
    """
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    for item in WorkflowLanguagePolicy:
        if item.value == cleaned:
            return item

    return cleaned


def to_supported_language(value: str | None) -> SupportedLanguage | None:
    """
    Convert raw string to SupportedLanguage.

    In the current project, SupportedLanguage behaves like a Literal-like type,
    so this function validates by string set and casts for typing.
    """
    if value is None:
        return None

    cleaned = value.strip().lower()
    if not cleaned:
        return None

    allowed_values = {"vi", "en"}

    if cleaned in allowed_values:
        return cast(SupportedLanguage, cleaned)

    raise HTTPException(
        status_code=422,
        detail={
            "error_code": "INVALID_LANGUAGE",
            "error_message": f"Unsupported selected_language: {value}",
            "allowed_values": sorted(allowed_values),
        },
    )


def response_to_json(response: WorkflowServiceResponse) -> dict[str, Any]:
    """
    Convert WorkflowServiceResponse to JSON-safe dict.

    Domain/workflow errors are returned as ok=false payloads instead of HTTP
    exceptions so clients can inspect response.error and suggested actions.
    """
    return cast(dict[str, Any], json_safe(response))


@app.get(
    "/health",
    tags=["Health"],
    summary="Check API health",
    description=(
        "Returns a simple health response. Use this endpoint to verify that "
        "the FastAPI REST adapter is running."
    ),
    operation_id="health_check",
)
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "api-testing-agent-headless-workflow-api",
    }


@app.post(
    "/workflows/start",
    tags=["Workflows"],
    summary="Start a new API testing workflow",
    description=(
        "Creates a new headless API testing workflow from a natural-language "
        "user request. The workflow may enter target selection, scope "
        "confirmation, or review depending on how specific the request is."
    ),
    operation_id="start_workflow",
)
def start_workflow(payload: StartWorkflowIn) -> dict[str, Any]:
    logger.info(
        "REST start_workflow called.",
        extra={"payload_source": "rest_headless_start_workflow"},
    )

    response = service.start_workflow(
        StartWorkflowRequest(
            text=payload.text,
            actor_context=to_actor_context(payload.actor_context),
            thread_id=payload.thread_id,
            language_policy=to_language_policy(payload.language_policy),
            selected_language=to_supported_language(payload.selected_language),
        )
    )
    return response_to_json(response)


@app.post(
    "/workflows/{thread_id}/continue",
    tags=["Workflows"],
    summary="Continue an existing workflow",
    description=(
        "Continues an active workflow with a user message. This endpoint is "
        "used for target selection, scope confirmation, review approval/revision, "
        "and report interaction."
    ),
    operation_id="continue_workflow",
)
def continue_workflow(
    thread_id: str,
    payload: ContinueWorkflowIn,
) -> dict[str, Any]:
    logger.info(
        "REST continue_workflow called.",
        extra={
            "thread_id": thread_id,
            "payload_source": "rest_headless_continue_workflow",
        },
    )

    response = service.continue_workflow(
        ContinueWorkflowRequest(
            thread_id=thread_id,
            message=payload.message,
            actor_context=to_actor_context(payload.actor_context),
        )
    )
    return response_to_json(response)


@app.get(
    "/workflows/{thread_id}/status",
    tags=["Workflow Read-Only"],
    summary="Get workflow status",
    description=(
        "Returns the current workflow status. This endpoint is read-only and "
        "must not mutate workflow state or conversation history."
    ),
    operation_id="get_workflow_status",
)
def get_workflow_status(thread_id: str) -> dict[str, Any]:
    logger.info(
        "REST get_workflow_status called.",
        extra={
            "thread_id": thread_id,
            "payload_source": "rest_headless_get_workflow_status",
        },
    )

    response = service.get_workflow_status(thread_id=thread_id)
    return response_to_json(response)


@app.get(
    "/workflows/{thread_id}/snapshot",
    tags=["Workflow Read-Only"],
    summary="Get workflow snapshot",
    description=(
        "Returns a debug/admin-oriented snapshot of the workflow state. "
        "This endpoint is read-only."
    ),
    operation_id="get_workflow_snapshot",
)
def get_workflow_snapshot(thread_id: str) -> dict[str, Any]:
    logger.info(
        "REST get_workflow_snapshot called.",
        extra={
            "thread_id": thread_id,
            "payload_source": "rest_headless_get_workflow_snapshot",
        },
    )

    response = service.get_workflow_snapshot(thread_id=thread_id)
    return response_to_json(response)


@app.get(
    "/workflows/{thread_id}/artifacts",
    tags=["Workflow Read-Only"],
    summary="List workflow artifacts",
    description=(
        "Lists artifact references associated with the workflow, such as draft "
        "reports, execution reports, validation reports, staged final reports, "
        "and finalized reports. This endpoint is read-only."
    ),
    operation_id="list_workflow_artifacts",
)
def list_workflow_artifacts(thread_id: str) -> dict[str, Any]:
    logger.info(
        "REST list_workflow_artifacts called.",
        extra={
            "thread_id": thread_id,
            "payload_source": "rest_headless_list_workflow_artifacts",
        },
    )

    response = service.list_workflow_artifacts(thread_id=thread_id)
    return response_to_json(response)


@app.post(
    "/workflows/{thread_id}/finalize",
    tags=["Workflow Actions"],
    summary="Finalize a workflow",
    description=(
        "Requests finalization of a workflow. This is mainly valid during "
        "report interaction after a staged final report has been created."
    ),
    operation_id="finalize_workflow",
)
def finalize_workflow(
    thread_id: str,
    payload: FinalizeWorkflowIn,
) -> dict[str, Any]:
    logger.info(
        "REST finalize_workflow called.",
        extra={
            "thread_id": thread_id,
            "payload_source": "rest_headless_finalize_workflow",
        },
    )

    response = service.finalize_workflow(
        FinalizeWorkflowRequest(
            thread_id=thread_id,
            actor_context=to_actor_context(payload.actor_context),
            auto_confirm=payload.auto_confirm,
            finalize_message=payload.finalize_message,
            confirmation_message=payload.confirmation_message,
        )
    )
    return response_to_json(response)


@app.post(
    "/workflows/{thread_id}/cancel",
    tags=["Workflow Actions"],
    summary="Cancel a workflow",
    description=(
        "Cancels an active workflow or report interaction session. The exact "
        "behavior depends on the current workflow phase."
    ),
    operation_id="cancel_workflow",
)
def cancel_workflow(
    thread_id: str,
    payload: CancelWorkflowIn,
) -> dict[str, Any]:
    logger.info(
        "REST cancel_workflow called.",
        extra={
            "thread_id": thread_id,
            "payload_source": "rest_headless_cancel_workflow",
        },
    )

    response = service.cancel_workflow(
        CancelWorkflowRequest(
            thread_id=thread_id,
            actor_context=to_actor_context(payload.actor_context),
            auto_confirm=payload.auto_confirm,
            cancel_message=payload.cancel_message,
            confirmation_message=payload.confirmation_message,
        )
    )
    return response_to_json(response)


@app.post(
    "/workflows/{thread_id}/rerun",
    tags=["Workflow Actions"],
    summary="Request workflow rerun",
    description=(
        "Requests a rerun from report interaction phase using a new natural-language "
        "instruction. This is mainly valid after the workflow has reached report interaction."
    ),
    operation_id="rerun_workflow",
)
def rerun_workflow(
    thread_id: str,
    payload: RerunWorkflowIn,
) -> dict[str, Any]:
    logger.info(
        "REST rerun_workflow called.",
        extra={
            "thread_id": thread_id,
            "payload_source": "rest_headless_rerun_workflow",
        },
    )

    response = service.rerun_workflow(
        RerunWorkflowRequest(
            thread_id=thread_id,
            instruction=payload.instruction,
            actor_context=to_actor_context(payload.actor_context),
        )
    )
    return response_to_json(response)