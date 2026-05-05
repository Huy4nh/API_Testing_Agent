from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api_testing_agent.interfaces.rest import headless_workflow_api as api


class FakeHeadlessWorkflowService:
    """
    Fake service for REST adapter tests.

    Purpose:
    - Do not run real LLM.
    - Do not run real workflow execution.
    - Do not call real target APIs.
    - Only verify that FastAPI endpoints call HeadlessWorkflowService contract correctly.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def start_workflow(self, request: Any) -> dict[str, Any]:
        self.calls.append(("start_workflow", request))

        return {
            "ok": True,
            "operation": "start_workflow",
            "actor_context": {
                "actor_id": request.actor_context.actor_id,
                "session_id": request.actor_context.session_id,
                "user_id": request.actor_context.user_id,
                "org_id": request.actor_context.org_id,
            },
            "workflow": {
                "workflow_id": "wf-demo-id",
                "thread_id": "wf-demo-thread",
                "phase": "pending_target_selection",
                "current_target": None,
                "assistant_message": "Which environment do you want to test?",
                "status_message": "Workflow is currently in phase `pending_target_selection`.",
                "selected_target": None,
                "candidate_targets": ["img_local", "img_api_staging", "img_api_prod"],
                "selection_question": "Which environment do you want to test?",
                "scope_confirmation_question": None,
                "scope_confirmation_summary": None,
                "canonical_command": None,
                "understanding_explanation": None,
                "preferred_language": "en",
                "language_policy": "adaptive",
                "available_actions": ["select_target", "cancel", "status", "help"],
                "needs_user_input": True,
                "finalized": False,
                "cancelled": False,
                "rerun_requested": False,
                "rerun_user_text": None,
                "artifacts": [],
            },
            "snapshot": None,
            "artifacts": [],
            "error": None,
        }

    def continue_workflow(self, request: Any) -> dict[str, Any]:
        self.calls.append(("continue_workflow", request))

        return {
            "ok": True,
            "operation": "continue_workflow",
            "actor_context": {
                "actor_id": request.actor_context.actor_id,
                "session_id": request.actor_context.session_id,
                "user_id": request.actor_context.user_id,
                "org_id": request.actor_context.org_id,
            },
            "workflow": {
                "workflow_id": "wf-demo-id",
                "thread_id": request.thread_id,
                "phase": "pending_scope_confirmation",
                "current_target": "img_api_prod",
                "assistant_message": "Please confirm testing scope.",
                "status_message": "Workflow is currently in phase `pending_scope_confirmation`.",
                "selected_target": "img_api_prod",
                "candidate_targets": ["img_local", "img_api_staging", "img_api_prod"],
                "selection_question": None,
                "scope_confirmation_question": "Do you want to test POST /img only?",
                "scope_confirmation_summary": "Target has multiple operations.",
                "canonical_command": None,
                "understanding_explanation": "Target selected, scope needs confirmation.",
                "preferred_language": "en",
                "language_policy": "adaptive",
                "available_actions": [
                    "resume_scope_confirmation",
                    "cancel",
                    "status",
                    "help",
                ],
                "needs_user_input": True,
                "finalized": False,
                "cancelled": False,
                "rerun_requested": False,
                "rerun_user_text": None,
                "artifacts": [],
            },
            "snapshot": None,
            "artifacts": [],
            "error": None,
        }

    def get_workflow_status(
        self,
        *,
        thread_id: str,
        actor_context: Any = None,
    ) -> dict[str, Any]:
        self.calls.append(("get_workflow_status", thread_id))

        return {
            "ok": True,
            "operation": "get_workflow_status",
            "actor_context": {},
            "workflow": {
                "workflow_id": "wf-demo-id",
                "thread_id": thread_id,
                "phase": "pending_review",
                "current_target": "img_api_prod",
                "assistant_message": None,
                "status_message": "Workflow is currently in phase `pending_review`.",
                "selected_target": "img_api_prod",
                "candidate_targets": ["img_local", "img_api_staging", "img_api_prod"],
                "selection_question": None,
                "scope_confirmation_question": None,
                "scope_confirmation_summary": None,
                "canonical_command": "test target img_api_prod /img POST positive missing invalid",
                "understanding_explanation": "Scope confirmed.",
                "preferred_language": "en",
                "language_policy": "adaptive",
                "available_actions": [
                    "continue_workflow",
                    "cancel_workflow",
                    "get_workflow_status",
                ],
                "needs_user_input": True,
                "finalized": False,
                "cancelled": False,
                "rerun_requested": False,
                "rerun_user_text": None,
                "artifacts": [
                    {
                        "artifact_type": "draft_report_json",
                        "path": "reports/testcase_drafts/demo/round_01.json",
                        "stage": "review",
                        "storage_backend": "filesystem",
                    }
                ],
            },
            "snapshot": {
                "workflow_id": "wf-demo-id",
                "thread_id": thread_id,
                "current_phase": "pending_review",
                "current_subphase": None,
                "current_target": "img_api_prod",
                "original_user_text": "test img",
                "selected_target": "img_api_prod",
                "candidate_targets": ["img_local", "img_api_staging", "img_api_prod"],
                "canonical_command": "test target img_api_prod /img POST positive missing invalid",
                "understanding_explanation": "Scope confirmed.",
                "preferred_language": "en",
                "language_policy": "adaptive",
                "finalized": False,
                "cancelled": False,
                "rerun_requested": False,
                "rerun_user_text": None,
                "pending_question": None,
                "last_router_decision": None,
                "last_scope_user_message": None,
                "artifact_refs": [
                    {
                        "artifact_type": "draft_report_json",
                        "path": "reports/testcase_drafts/demo/round_01.json",
                        "stage": "review",
                        "storage_backend": "filesystem",
                    }
                ],
                "active_review_id": thread_id,
                "active_report_session_id": None,
            },
            "artifacts": [
                {
                    "artifact_type": "draft_report_json",
                    "path": "reports/testcase_drafts/demo/round_01.json",
                    "stage": "review",
                    "storage_backend": "filesystem",
                }
            ],
            "error": None,
        }

    def get_workflow_snapshot(
        self,
        *,
        thread_id: str,
        actor_context: Any = None,
    ) -> dict[str, Any]:
        self.calls.append(("get_workflow_snapshot", thread_id))

        return {
            "ok": True,
            "operation": "get_workflow_snapshot",
            "actor_context": {},
            "workflow": None,
            "snapshot": {
                "workflow_id": "wf-demo-id",
                "thread_id": thread_id,
                "current_phase": "pending_review",
                "current_subphase": None,
                "current_target": "img_api_prod",
                "original_user_text": "test img",
                "selected_target": "img_api_prod",
                "candidate_targets": ["img_local", "img_api_staging", "img_api_prod"],
                "canonical_command": "test target img_api_prod /img POST positive missing invalid",
                "understanding_explanation": "Scope confirmed.",
                "preferred_language": "en",
                "language_policy": "adaptive",
                "finalized": False,
                "cancelled": False,
                "rerun_requested": False,
                "rerun_user_text": None,
                "pending_question": None,
                "last_router_decision": None,
                "last_scope_user_message": None,
                "artifact_refs": [],
                "active_review_id": thread_id,
                "active_report_session_id": None,
            },
            "artifacts": [],
            "error": None,
        }

    def list_workflow_artifacts(
        self,
        *,
        thread_id: str,
        actor_context: Any = None,
    ) -> dict[str, Any]:
        self.calls.append(("list_workflow_artifacts", thread_id))

        return {
            "ok": True,
            "operation": "list_workflow_artifacts",
            "actor_context": {},
            "workflow": None,
            "snapshot": None,
            "artifacts": [
                {
                    "artifact_type": "draft_report_json",
                    "path": "reports/testcase_drafts/demo/round_01.json",
                    "stage": "review",
                    "storage_backend": "filesystem",
                },
                {
                    "artifact_type": "draft_report_md",
                    "path": "reports/testcase_drafts/demo/round_01.md",
                    "stage": "review",
                    "storage_backend": "filesystem",
                },
            ],
            "error": None,
        }

    def finalize_workflow(self, request: Any) -> dict[str, Any]:
        self.calls.append(("finalize_workflow", request))

        return {
            "ok": True,
            "operation": "finalize_workflow",
            "actor_context": {},
            "workflow": {
                "workflow_id": "wf-demo-id",
                "thread_id": request.thread_id,
                "phase": "finalized",
                "current_target": "img_api_prod",
                "assistant_message": "Workflow finalized.",
                "status_message": "Workflow is finalized.",
                "selected_target": "img_api_prod",
                "candidate_targets": [],
                "selection_question": None,
                "scope_confirmation_question": None,
                "scope_confirmation_summary": None,
                "canonical_command": "test target img_api_prod /img POST positive missing invalid",
                "understanding_explanation": "Finalized.",
                "preferred_language": "en",
                "language_policy": "adaptive",
                "available_actions": ["start_new_workflow", "status", "help"],
                "needs_user_input": False,
                "finalized": True,
                "cancelled": False,
                "rerun_requested": False,
                "rerun_user_text": None,
                "artifacts": [],
            },
            "snapshot": None,
            "artifacts": [],
            "error": None,
        }

    def cancel_workflow(self, request: Any) -> dict[str, Any]:
        self.calls.append(("cancel_workflow", request))

        return {
            "ok": True,
            "operation": "cancel_workflow",
            "actor_context": {},
            "workflow": {
                "workflow_id": "wf-demo-id",
                "thread_id": request.thread_id,
                "phase": "cancelled",
                "current_target": "img_api_prod",
                "assistant_message": "Workflow cancelled.",
                "status_message": "Workflow is cancelled.",
                "selected_target": "img_api_prod",
                "candidate_targets": [],
                "selection_question": None,
                "scope_confirmation_question": None,
                "scope_confirmation_summary": None,
                "canonical_command": "test target img_api_prod /img POST positive missing invalid",
                "understanding_explanation": "Cancelled.",
                "preferred_language": "en",
                "language_policy": "adaptive",
                "available_actions": ["start_new_workflow", "status", "help"],
                "needs_user_input": False,
                "finalized": False,
                "cancelled": True,
                "rerun_requested": False,
                "rerun_user_text": None,
                "artifacts": [],
            },
            "snapshot": None,
            "artifacts": [],
            "error": None,
        }

    def rerun_workflow(self, request: Any) -> dict[str, Any]:
        self.calls.append(("rerun_workflow", request))

        return {
            "ok": True,
            "operation": "rerun_workflow",
            "actor_context": {},
            "workflow": {
                "workflow_id": "wf-demo-id",
                "thread_id": request.thread_id,
                "phase": "rerun_requested",
                "current_target": "img_api_prod",
                "assistant_message": "Rerun requested.",
                "status_message": "Rerun requested.",
                "selected_target": "img_api_prod",
                "candidate_targets": [],
                "selection_question": None,
                "scope_confirmation_question": None,
                "scope_confirmation_summary": None,
                "canonical_command": "test target img_api_prod /img POST positive missing invalid",
                "understanding_explanation": "Rerun requested.",
                "preferred_language": "en",
                "language_policy": "adaptive",
                "available_actions": ["start_new_workflow", "status", "help"],
                "needs_user_input": False,
                "finalized": False,
                "cancelled": False,
                "rerun_requested": True,
                "rerun_user_text": request.instruction,
                "artifacts": [],
            },
            "snapshot": None,
            "artifacts": [],
            "error": None,
        }


@pytest.fixture()
def rest_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, FakeHeadlessWorkflowService]]:
    fake_service = FakeHeadlessWorkflowService()
    monkeypatch.setattr(api, "service", fake_service)

    with TestClient(api.app) as client:
        yield client, fake_service


def test_health_returns_ok(
    rest_client: tuple[TestClient, FakeHeadlessWorkflowService],
) -> None:
    client, _ = rest_client

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service": "api-testing-agent-headless-workflow-api",
    }


def test_start_workflow_calls_service_and_returns_response(
    rest_client: tuple[TestClient, FakeHeadlessWorkflowService],
) -> None:
    client, fake_service = rest_client

    response = client.post(
        "/workflows/start",
        json={
            "text": "test img",
            "actor_context": {
                "actor_id": "local_rest",
                "session_id": "rest_manual_test",
                "user_id": "local_user",
                "org_id": "local_org",
            },
        },
    )

    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["operation"] == "start_workflow"
    assert data["workflow"]["phase"] == "pending_target_selection"
    assert data["workflow"]["thread_id"] == "wf-demo-thread"

    assert fake_service.calls[0][0] == "start_workflow"
    request = fake_service.calls[0][1]
    assert request.text == "test img"
    assert request.actor_context.actor_id == "local_rest"


def test_start_workflow_rejects_invalid_selected_language(
    rest_client: tuple[TestClient, FakeHeadlessWorkflowService],
) -> None:
    client, fake_service = rest_client

    response = client.post(
        "/workflows/start",
        json={
            "text": "test img",
            "selected_language": "jp",
        },
    )

    data = response.json()

    assert response.status_code == 422
    assert data["detail"]["error_code"] == "INVALID_LANGUAGE"
    assert data["detail"]["allowed_values"] == ["en", "vi"]

    assert fake_service.calls == []


def test_continue_workflow_calls_service(
    rest_client: tuple[TestClient, FakeHeadlessWorkflowService],
) -> None:
    client, fake_service = rest_client

    response = client.post(
        "/workflows/wf-demo-thread/continue",
        json={
            "message": "product",
            "actor_context": {
                "actor_id": "local_rest",
                "session_id": "rest_manual_test",
            },
        },
    )

    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["operation"] == "continue_workflow"
    assert data["workflow"]["thread_id"] == "wf-demo-thread"
    assert data["workflow"]["phase"] == "pending_scope_confirmation"

    assert fake_service.calls[0][0] == "continue_workflow"
    request = fake_service.calls[0][1]
    assert request.thread_id == "wf-demo-thread"
    assert request.message == "product"
    assert request.actor_context.actor_id == "local_rest"


def test_get_workflow_status_calls_read_only_service_method(
    rest_client: tuple[TestClient, FakeHeadlessWorkflowService],
) -> None:
    client, fake_service = rest_client

    response = client.get("/workflows/wf-demo-thread/status")

    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["operation"] == "get_workflow_status"
    assert data["workflow"]["phase"] == "pending_review"
    assert data["snapshot"]["current_phase"] == "pending_review"

    assert fake_service.calls == [("get_workflow_status", "wf-demo-thread")]


def test_get_workflow_snapshot_calls_read_only_service_method(
    rest_client: tuple[TestClient, FakeHeadlessWorkflowService],
) -> None:
    client, fake_service = rest_client

    response = client.get("/workflows/wf-demo-thread/snapshot")

    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["operation"] == "get_workflow_snapshot"
    assert data["snapshot"]["thread_id"] == "wf-demo-thread"
    assert data["snapshot"]["current_phase"] == "pending_review"

    assert fake_service.calls == [("get_workflow_snapshot", "wf-demo-thread")]


def test_list_workflow_artifacts_calls_read_only_service_method(
    rest_client: tuple[TestClient, FakeHeadlessWorkflowService],
) -> None:
    client, fake_service = rest_client

    response = client.get("/workflows/wf-demo-thread/artifacts")

    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["operation"] == "list_workflow_artifacts"
    assert len(data["artifacts"]) == 2
    assert data["artifacts"][0]["artifact_type"] == "draft_report_json"

    assert fake_service.calls == [("list_workflow_artifacts", "wf-demo-thread")]


def test_finalize_workflow_calls_service(
    rest_client: tuple[TestClient, FakeHeadlessWorkflowService],
) -> None:
    client, fake_service = rest_client

    response = client.post(
        "/workflows/wf-demo-thread/finalize",
        json={
            "auto_confirm": True,
            "finalize_message": "luu",
            "confirmation_message": "dong y",
        },
    )

    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["operation"] == "finalize_workflow"
    assert data["workflow"]["phase"] == "finalized"
    assert data["workflow"]["finalized"] is True

    assert fake_service.calls[0][0] == "finalize_workflow"
    request = fake_service.calls[0][1]
    assert request.thread_id == "wf-demo-thread"
    assert request.auto_confirm is True


def test_cancel_workflow_calls_service(
    rest_client: tuple[TestClient, FakeHeadlessWorkflowService],
) -> None:
    client, fake_service = rest_client

    response = client.post(
        "/workflows/wf-demo-thread/cancel",
        json={
            "auto_confirm": True,
            "cancel_message": "huy",
            "confirmation_message": "dong y",
        },
    )

    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["operation"] == "cancel_workflow"
    assert data["workflow"]["phase"] == "cancelled"
    assert data["workflow"]["cancelled"] is True

    assert fake_service.calls[0][0] == "cancel_workflow"
    request = fake_service.calls[0][1]
    assert request.thread_id == "wf-demo-thread"
    assert request.cancel_message == "huy"


def test_rerun_workflow_calls_service(
    rest_client: tuple[TestClient, FakeHeadlessWorkflowService],
) -> None:
    client, fake_service = rest_client

    response = client.post(
        "/workflows/wf-demo-thread/rerun",
        json={
            "instruction": "run again with positive cases only",
        },
    )

    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["operation"] == "rerun_workflow"
    assert data["workflow"]["phase"] == "rerun_requested"
    assert data["workflow"]["rerun_requested"] is True

    assert fake_service.calls[0][0] == "rerun_workflow"
    request = fake_service.calls[0][1]
    assert request.thread_id == "wf-demo-thread"
    assert request.instruction == "run again with positive cases only"