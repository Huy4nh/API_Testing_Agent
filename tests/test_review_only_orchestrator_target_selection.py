import json
from pathlib import Path

from api_testing_agent.config import Settings
from api_testing_agent.core.request_understanding_service import UnderstandingResult
from api_testing_agent.core.intent_parser import RuleBasedIntentParser
from api_testing_agent.tasks.orchestrator import TestOrchestrator


class FakeUnderstandingService:
    def __init__(self) -> None:
        self._parser = RuleBasedIntentParser()

    def understand(
        self,
        raw_text: str,
        *,
        forced_target_name: str,
        operation_hints: list[dict],
    ):
        canonical = f"test target {forced_target_name} /img POST"
        plan = self._parser.parse(canonical)
        return UnderstandingResult(
            original_text=raw_text,
            canonical_command=canonical,
            plan=plan,
        )


class FakeAITestCaseAgent:
    def __init__(self) -> None:
        self._model_name = "fake:model"

    def set_model_name(self, model_name: str) -> None:
        self._model_name = model_name

    def get_model_name(self) -> str:
        return self._model_name

    def generate_for_operation(self, context):
        from api_testing_agent.core.ai_testcase_models import AITestCaseDraft, AITestCaseDraftList

        return AITestCaseDraftList(
            cases=[
                AITestCaseDraft(
                    test_type="positive",
                    description="Positive case",
                    reasoning_summary="Valid request body",
                    expected_status_codes=[200],
                    json_body={"content": "hello"},
                )
            ]
        )


class FakeTargetDisambiguationAgent:
    def __init__(self) -> None:
        self._model_name = "fake:model"

    def set_model_name(self, model_name: str) -> None:
        self._model_name = model_name

    def get_model_name(self) -> str:
        return self._model_name

    def decide(self, *, raw_text: str, candidate_payload: list[dict]):
        from api_testing_agent.core.target_disambiguation_models import (
            TargetCandidate,
            TargetDisambiguationDecision,
        )

        return TargetDisambiguationDecision(
            mode="ask_user",
            selected_target=None,
            candidates=[
                TargetCandidate(name=item["name"], reason=item["reason"])
                for item in candidate_payload
            ],
            question="Bạn muốn chọn target nào?",
        )


class FakeCanonicalCommandAgent:
    def __init__(self) -> None:
        self._model_name = "fake:model"

    def set_model_name(self, model_name: str) -> None:
        self._model_name = model_name

    def get_model_name(self) -> str:
        return self._model_name


def test_orchestrator_target_selection_then_review(tmp_path: Path):
    spec_path = tmp_path / "openapi.yaml"
    spec_path.write_text(
        """
openapi: 3.0.0
info:
  title: Demo API
  version: 1.0.0

paths:
  /img:
    post:
      summary: Generate image
      responses:
        "200":
          description: OK
        """,
        encoding="utf-8",
    )

    targets_path = tmp_path / "targets.json"
    targets_path.write_text(
        json.dumps(
            [
                {
                    "name": "hello_work",
                    "base_url": "http://127.0.0.1:8000",
                    "openapi_spec_path": str(spec_path),
                    "enabled": True,
                },
                {
                    "name": "hello_work_to",
                    "base_url": "http://127.0.0.1:8001",
                    "openapi_spec_path": str(spec_path),
                    "enabled": True,
                },
                {
                    "name": "hello_world",
                    "base_url": "http://127.0.0.1:8002",
                    "openapi_spec_path": str(spec_path),
                    "enabled": True,
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    settings = Settings(
        target_registry_path=str(targets_path),
        report_output_dir=str(tmp_path / "reports"),
        testcase_generator_mode="ai",
        langchain_model_name="openai:gpt-5.2",
        langgraph_checkpointer="memory",
        langgraph_sqlite_path=str(tmp_path / "checkpoints.db"),
        http_timeout_seconds=10,
        sqlite_path=str(tmp_path / "runs.sqlite3"),
    )

    orchestrator = TestOrchestrator(
        settings,
        ai_agent=FakeAITestCaseAgent(),
        target_disambiguation_agent=FakeTargetDisambiguationAgent(),
        canonical_command_agent=FakeCanonicalCommandAgent(),
        understanding_service=FakeUnderstandingService(),
    )

    start_result = orchestrator.start_review_from_text(
        "hãy test hello cho tôi",
        thread_id="thread-target-selection",
    )

    assert start_result.status == "pending_target_selection"
    assert start_result.candidate_targets == ["hello_work", "hello_work_to", "hello_world"]

    select_result = orchestrator.resume_target_selection(
        "thread-target-selection",
        selection="3",
    )

    assert select_result.status == "pending_review"
    assert select_result.selected_target == "hello_world"
    assert select_result.canonical_command == "test target hello_world /img POST"
    assert select_result.draft_report_json_path is not None
    assert select_result.draft_report_md_path is not None
    assert Path(select_result.draft_report_json_path).exists()
    assert Path(select_result.draft_report_md_path).exists()