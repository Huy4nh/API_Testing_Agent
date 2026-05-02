from pathlib import Path

from api_testing_agent.core.report_context_builder import ReportContextBuilder
from api_testing_agent.core.reporter.interactive.interactive_report_service import (
    InteractiveReportService,
)


class FakeHybridAI:
    def answer_report_question(
        self,
        *,
        thread_id: str,
        target_name: str | None,
        user_text: str,
        final_report_data: dict,
        current_markdown: str,
        messages: list[dict[str, str]],
    ) -> str:
        return "Đây là câu trả lời tự nhiên bằng AI."

    def rewrite_report(
        self,
        *,
        thread_id: str,
        target_name: str | None,
        instruction: str,
        final_report_data: dict,
        current_markdown: str,
        messages: list[dict[str, str]],
    ) -> str:
        return "# Bản report đã được viết lại bằng AI\n\n- Dễ hiểu hơn\n- Tự nhiên hơn"


def build_state(tmp_path: Path) -> dict:
    staged_dir = tmp_path / "_staging" / "final_runs" / "img_api_staging" / "thread-001"
    staged_dir.mkdir(parents=True, exist_ok=True)

    staged_json = staged_dir / "final_summary.json"
    staged_md = staged_dir / "final_summary.md"
    staged_json.write_text('{"summary": {"target_name": "img_api_staging"}}', encoding="utf-8")
    staged_md.write_text("# Final Report", encoding="utf-8")

    return {
        "thread_id": "thread-001",
        "target_name": "img_api_staging",
        "original_request": "hãy test sinh ảnh của img",
        "canonical_command": "test target img_api_staging /img POST /YT POST positive missing invalid",
        "understanding_explanation": "resolved img + yt scope",
        "candidate_targets": ["img_local", "img_api_staging", "img_api_prod"],
        "target_selection_question": "Bạn muốn test trên local, staging hay production?",
        "review_feedback_history": ["thêm yt vào"],
        "staged_final_report_json_path": str(staged_json),
        "staged_final_report_md_path": str(staged_md),
        "final_report_json_path": None,
        "final_report_md_path": None,
        "final_report_markdown": "# Final Report",
        "final_report_data": {
            "summary": {
                "target_name": "img_api_staging",
                "selected_target": "img_api_staging",
                "candidate_targets": ["img_local", "img_api_staging", "img_api_prod"],
                "feedback_history": ["thêm yt vào"],
                "total_cases": 10,
                "executed_cases": 6,
                "pass_cases": 5,
                "fail_cases": 1,
                "skip_cases_validation": 4,
                "error_cases": 0,
            },
            "case_summaries": [],
            "notable_findings": [],
            "links": {},
        },
        "messages": [],
        "artifact_paths": [],
        "finalized": False,
        "cancelled": False,
        "rerun_requested": False,
    }


def test_answer_question_uses_hybrid_ai(tmp_path: Path):
    service = InteractiveReportService(
        output_dir=str(tmp_path),
        context_builder=ReportContextBuilder(),
        hybrid_ai=FakeHybridAI(),
    )
    state = build_state(tmp_path)
    result = service.answer_question(state, "giải thích dễ hiểu hơn")
    assert result["assistant_response"] == "Đây là câu trả lời tự nhiên bằng AI."


def test_rewrite_report_uses_hybrid_ai(tmp_path: Path):
    service = InteractiveReportService(
        output_dir=str(tmp_path),
        context_builder=ReportContextBuilder(),
        hybrid_ai=FakeHybridAI(),
    )
    state = build_state(tmp_path)
    result = service.revise_report_text(state, "viết lại report dễ hiểu hơn")
    assert result["final_report_markdown"].startswith("# Bản report đã được viết lại bằng AI")


def test_finalize_session_copies_staged_to_final(tmp_path: Path):
    service = InteractiveReportService(
        output_dir=str(tmp_path),
        context_builder=ReportContextBuilder(),
        hybrid_ai=FakeHybridAI(),
    )
    state = build_state(tmp_path)
    result = service.finalize_session(state)

    assert result["finalized"] is True
    assert Path(result["final_report_json_path"]).exists()
    assert Path(result["final_report_md_path"]).exists()


def test_cancel_session_removes_staging(tmp_path: Path):
    service = InteractiveReportService(
        output_dir=str(tmp_path),
        context_builder=ReportContextBuilder(),
        hybrid_ai=FakeHybridAI(),
    )
    state = build_state(tmp_path)

    staged_json = Path(state["staged_final_report_json_path"])
    staged_md = Path(state["staged_final_report_md_path"])

    result = service.cancel_session(state)

    assert result["cancelled"] is True
    assert not staged_json.exists()
    assert not staged_md.exists()