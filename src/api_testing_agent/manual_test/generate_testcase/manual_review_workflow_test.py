from __future__ import annotations

import uuid

from api_testing_agent.config import Settings
from api_testing_agent.tasks.orchestrator import TestOrchestrator


def main() -> None:
    settings = Settings()
    orchestrator = TestOrchestrator(settings)

    request_text = input("Nhập lệnh test: ").strip()
    if not request_text:
        print("Request rỗng.")
        return

    thread_id = f"cli-review-{uuid.uuid4().hex}"
    result = orchestrator.start_review_from_text(request_text, thread_id=thread_id)

    while True:
        print("\n" + "=" * 100)
        print(f"STATUS: {result.status}")
        print(f"THREAD: {result.thread_id}")

        if result.original_user_text:
            print(f"ORIGINAL REQUEST: {result.original_user_text}")

        if result.selected_target:
            print(f"SELECTED TARGET: {result.selected_target}")

        if result.canonical_command:
            print(f"CANONICAL COMMAND: {result.canonical_command}")

        if result.understanding_explanation:
            print(f"UNDERSTANDING: {result.understanding_explanation}")

        if result.candidate_targets:
            print("CANDIDATE TARGETS:")
            for index, item in enumerate(result.candidate_targets, start=1):
                print(f"  {index}. {item}")

        if result.selection_question:
            print(f"TARGET QUESTION: {result.selection_question}")

        if result.message:
            print(f"MESSAGE: {result.message}")

        if result.available_functions:
            print("AVAILABLE FUNCTIONS:")
            for item in result.available_functions:
                print(f"  - {item}")

        if result.draft_report_json_path:
            print(f"DRAFT JSON REPORT: {result.draft_report_json_path}")
        if result.draft_report_md_path:
            print(f"DRAFT MD REPORT: {result.draft_report_md_path}")

        if result.preview_text:
            print(result.preview_text)

        if result.status == "pending_target_selection":
            selection = input("\nNhập lựa chọn target [số thứ tự / tên target / cancel]: ").strip()
            result = orchestrator.resume_target_selection(
                thread_id,
                selection=selection,
            )
            continue

        if result.status == "target_not_found":
            print("\nKhông resolve được target.")
            break

        if result.status == "invalid_function":
            print("\nChức năng bạn yêu cầu không tồn tại hoặc không map được.")
            break

        if result.status == "pending_review":
            action = input("\nNhập action [approve / feedback / cancel]: ").strip().lower()

            if action == "approve":
                result = orchestrator.resume_review(thread_id, action="approve")
                continue

            if action == "cancel":
                result = orchestrator.resume_review(thread_id, action="cancel")
                continue

            feedback = input("Nhập feedback để sinh lại testcase: ").strip()
            result = orchestrator.resume_review(
                thread_id,
                action="revise",
                feedback=feedback,
            )
            continue

        if result.status == "approved":
            print("\nReview approved.")
            break

        if result.status == "cancelled":
            print("\nWorkflow cancelled.")
            break

        print("\nWorkflow ended with unexpected state.")
        break


if __name__ == "__main__":
    main()