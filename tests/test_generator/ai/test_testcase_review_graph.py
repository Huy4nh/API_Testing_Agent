from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from api_testing_agent.core.ai_testcase_models import AITestCaseDraft, AITestCaseDraftList
from api_testing_agent.core.reporter.testcase import TestcaseDraftReporter
from api_testing_agent.core.testcase_review_graph import build_testcase_review_graph


class FakeAITestCaseAgent:
    def generate_for_operation(self, context):
        feedback_text = " ".join(context.get("feedback_history", [])).lower()

        cases = [
            AITestCaseDraft(
                test_type="positive",
                description="Positive case from fake agent",
                reasoning_summary="Valid request body",
                expected_status_codes=[201],
                json_body={"title": "string", "content": "string"},
            )
        ]

        if "unauthorized" in feedback_text:
            cases.append(
                AITestCaseDraft(
                    test_type="unauthorized_or_forbidden",
                    description="Unauthorized case from fake agent",
                    reasoning_summary="No token should be sent",
                    expected_status_codes=[401, 403],
                    headers={"Authorization": "Bearer fake"},
                )
            )

        return AITestCaseDraftList(cases=cases)


def _has_interrupt(snapshot) -> bool:
    for task in snapshot.tasks:
        if getattr(task, "interrupts", ()):
            return True
    return False


def test_review_graph_interrupt_revise_and_approve(tmp_path: Path):
    draft_reporter = TestcaseDraftReporter(output_dir=str(tmp_path))

    graph = build_testcase_review_graph(
        agent=FakeAITestCaseAgent(),
        draft_reporter=draft_reporter,
        checkpointer=InMemorySaver(),
    )

    config = {"configurable": {"thread_id": "thread-1"}}
    initial_state = {
        "thread_id": "thread-1",
        "user_request_text": "Run negative login tests on ngrok.",
        "canonical_command": "test target ngrok_live module auth negative",
        "target_name": "cms_local",
        "plan": {
            "test_types": ["positive", "unauthorized_or_forbidden"],
            "ignore_fields": [],
        },
        "operation_contexts": [
            {
                "operation_id": "post_posts",
                "method": "POST",
                "path": "/posts",
                "tags": ["posts"],
                "summary": "Create post",
                "auth_required": True,
                "parameters": [],
                "request_body": {
                    "required": True,
                    "content_type": "application/json",
                    "schema": {
                        "type": "object",
                        "required": ["title", "content"],
                        "properties": {
                            "title": {"type": "string"},
                            "content": {"type": "string"},
                        },
                    },
                },
                "responses": {"201": {"description": "Created"}},
            }
        ],
        "feedback_history": [],
        "review_round": 0,
        "approved": False,
        "cancelled": False,
    }

    graph.invoke(initial_state, config=config)
    snapshot = graph.get_state(config)

    assert _has_interrupt(snapshot) is True
    assert snapshot.values["review_round"] == 1
    assert "Run negative login tests on ngrok." in snapshot.values["draft_preview"]
    assert "test target ngrok_live module auth negative" in snapshot.values["draft_preview"]
    assert Path(snapshot.values["draft_report_json_path"]).exists()
    assert Path(snapshot.values["draft_report_md_path"]).exists()

    graph.invoke(
        Command(
            resume={
                "action": "revise",
                "feedback": "Please add unauthorized case",
            }
        ),
        config=config,
    )
    snapshot = graph.get_state(config)

    assert _has_interrupt(snapshot) is True
    assert snapshot.values["review_round"] == 2
    assert "Unauthorized case from fake agent" in snapshot.values["draft_preview"]

    graph.invoke(
        Command(
            resume={
                "action": "approve",
                "feedback": "",
            }
        ),
        config=config,
    )
    snapshot = graph.get_state(config)

    assert _has_interrupt(snapshot) is False
    assert snapshot.values["approved"] is True
    assert snapshot.next == ()