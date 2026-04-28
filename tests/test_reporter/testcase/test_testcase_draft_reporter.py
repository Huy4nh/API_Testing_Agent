from pathlib import Path

from api_testing_agent.core.reporter.testcase import TestcaseDraftReporter


def test_testcase_draft_reporter_writes_json_and_markdown(tmp_path: Path):
    reporter = TestcaseDraftReporter(output_dir=str(tmp_path))

    draft_groups = [
        {
            "operation_id": "post_posts",
            "method": "POST",
            "path": "/posts",
            "cases": [
                {
                    "test_type": "positive",
                    "description": "Create post with valid body",
                    "reasoning_summary": "Schema requires title and content",
                    "expected_status_codes": [201],
                    "skip": False,
                },
                {
                    "test_type": "unauthorized_or_forbidden",
                    "description": "Create post without token",
                    "reasoning_summary": "Endpoint requires auth",
                    "expected_status_codes": [401, 403],
                    "skip": False,
                },
            ],
        }
    ]

    report = reporter.write(
        thread_id="thread-abc",
        target_name="cms_local",
        round_number=1,
        original_user_text="Run negative login tests on ngrok.",
        canonical_command="test target ngrok_live module auth negative",
        draft_groups=draft_groups,
        feedback_history=["Add unauthorized case"],
        plan={
            "test_types": ["positive", "unauthorized_or_forbidden"],
            "ignore_fields": [],
        },
        operation_contexts=[
            {
                "operation_id": "post_posts",
                "method": "POST",
                "path": "/posts",
            }
        ],
    )

    assert report.thread_id == "thread-abc"
    assert report.target_name == "cms_local"
    assert report.round_number == 1

    json_path = Path(report.json_path)
    md_path = Path(report.markdown_path)

    assert json_path.exists()
    assert md_path.exists()

    json_text = json_path.read_text(encoding="utf-8")
    md_text = md_path.read_text(encoding="utf-8")

    assert "Run negative login tests on ngrok." in json_text
    assert "test target ngrok_live module auth negative" in json_text
    assert "Original request" in md_text
    assert "Canonical command" in md_text
    assert "Create post without token" in md_text