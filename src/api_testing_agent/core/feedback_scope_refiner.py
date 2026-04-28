from __future__ import annotations

from dataclasses import dataclass

from api_testing_agent.core.feedback_scope_agent import FeedbackScopeAgent


@dataclass(frozen=True)
class FeedbackScopeResult:
    operation_contexts: list[dict]
    scope_note: str | None = None


class FeedbackScopeRefiner:
    """
    Dùng feedback của user trong vòng review để sửa lại phạm vi operation.

    Hỗ trợ:
    - replace_with_specific
    - add_specific
    - remove_specific
    - reset_all
    - keep
    """

    def __init__(self, feedback_scope_agent: FeedbackScopeAgent) -> None:
        self._feedback_scope_agent = feedback_scope_agent

    def refine(
        self,
        *,
        target_name: str,
        current_operation_contexts: list[dict],
        all_operation_contexts: list[dict],
        feedback_history: list[str],
    ) -> FeedbackScopeResult:
        if not feedback_history:
            return FeedbackScopeResult(
                operation_contexts=current_operation_contexts,
                scope_note=None,
            )

        latest_feedback = feedback_history[-1].strip()
        if not latest_feedback:
            return FeedbackScopeResult(
                operation_contexts=current_operation_contexts,
                scope_note=None,
            )

        decision = self._feedback_scope_agent.decide(
            feedback_text=latest_feedback,
            target_name=target_name,
            all_operation_hints=self._build_operation_hints(all_operation_contexts),
            current_scope_hints=self._build_operation_hints(current_operation_contexts),
        )

        if decision.action_mode == "keep":
            return FeedbackScopeResult(
                operation_contexts=current_operation_contexts,
                scope_note="Feedback không thay đổi phạm vi test. Giữ nguyên scope hiện tại.",
            )

        if decision.action_mode == "reset_all":
            return FeedbackScopeResult(
                operation_contexts=all_operation_contexts,
                scope_note="Feedback đã chuyển phạm vi về: toàn bộ chức năng của target.",
            )

        matched_operations = self._resolve_operations(
            all_operation_contexts=all_operation_contexts,
            matched_operation_ids=decision.matched_operation_ids,
            matched_paths=decision.matched_paths,
            matched_tags=decision.matched_tags,
        )

        if decision.action_mode == "invalid_feedback":
            invalid_text = decision.invalid_feedback_text or latest_feedback
            return FeedbackScopeResult(
                operation_contexts=current_operation_contexts,
                scope_note=(
                    f"Không áp dụng được feedback '{invalid_text}' vì không map được vào "
                    "operation hiện có. Giữ nguyên phạm vi hiện tại."
                ),
            )

        if not matched_operations:
            return FeedbackScopeResult(
                operation_contexts=current_operation_contexts,
                scope_note=(
                    f"Feedback '{latest_feedback}' đã được hiểu là sửa scope, "
                    "nhưng không map được vào operation hiện có. Giữ nguyên phạm vi hiện tại."
                ),
            )

        if decision.action_mode == "replace_with_specific":
            return FeedbackScopeResult(
                operation_contexts=matched_operations,
                scope_note=f"Feedback đã thay phạm vi test thành: {latest_feedback}",
            )

        if decision.action_mode == "add_specific":
            merged = self._merge_operations(
                current_operation_contexts=current_operation_contexts,
                extra_operations=matched_operations,
            )
            return FeedbackScopeResult(
                operation_contexts=merged,
                scope_note=f"Feedback đã mở rộng phạm vi test theo yêu cầu: {latest_feedback}",
            )

        if decision.action_mode == "remove_specific":
            reduced = self._remove_operations(
                current_operation_contexts=current_operation_contexts,
                remove_operations=matched_operations,
            )
            return FeedbackScopeResult(
                operation_contexts=reduced,
                scope_note=f"Feedback đã loại bớt phạm vi test theo yêu cầu: {latest_feedback}",
            )

        return FeedbackScopeResult(
            operation_contexts=current_operation_contexts,
            scope_note="Feedback không thay đổi phạm vi test. Giữ nguyên scope hiện tại.",
        )

    def _build_operation_hints(self, operation_contexts: list[dict]) -> list[dict]:
        hints: list[dict] = []
        for item in operation_contexts:
            hints.append(
                {
                    "operation_id": item.get("operation_id"),
                    "method": item.get("method"),
                    "path": item.get("path"),
                    "tags": item.get("tags", []),
                    "summary": item.get("summary", ""),
                }
            )
        return hints

    def _resolve_operations(
        self,
        *,
        all_operation_contexts: list[dict],
        matched_operation_ids: list[str],
        matched_paths: list[str],
        matched_tags: list[str],
    ) -> list[dict]:
        matched_ids = {item for item in matched_operation_ids if item}
        matched_paths_set = {item for item in matched_paths if item}
        matched_tags_set = {item.lower() for item in matched_tags if item}

        resolved: list[dict] = []

        for operation in all_operation_contexts:
            op_id = operation.get("operation_id")
            path = operation.get("path")
            tags = {str(tag).lower() for tag in operation.get("tags", [])}

            if matched_ids and op_id in matched_ids:
                resolved.append(operation)
                continue

            if matched_paths_set and path in matched_paths_set:
                resolved.append(operation)
                continue

            if matched_tags_set and tags.intersection(matched_tags_set):
                resolved.append(operation)
                continue

        # unique theo operation_id + path + method
        unique: list[dict] = []
        seen: set[tuple[str, str, str]] = set()

        for item in resolved:
            key = (
                str(item.get("operation_id", "")),
                str(item.get("path", "")),
                str(item.get("method", "")),
            )
            if key not in seen:
                seen.add(key)
                unique.append(item)

        return unique

    def _merge_operations(
        self,
        *,
        current_operation_contexts: list[dict],
        extra_operations: list[dict],
    ) -> list[dict]:
        merged = list(current_operation_contexts)
        seen = {
            (
                str(item.get("operation_id", "")),
                str(item.get("path", "")),
                str(item.get("method", "")),
            )
            for item in merged
        }

        for item in extra_operations:
            key = (
                str(item.get("operation_id", "")),
                str(item.get("path", "")),
                str(item.get("method", "")),
            )
            if key not in seen:
                seen.add(key)
                merged.append(item)

        return merged

    def _remove_operations(
        self,
        *,
        current_operation_contexts: list[dict],
        remove_operations: list[dict],
    ) -> list[dict]:
        remove_keys = {
            (
                str(item.get("operation_id", "")),
                str(item.get("path", "")),
                str(item.get("method", "")),
            )
            for item in remove_operations
        }

        return [
            item
            for item in current_operation_contexts
            if (
                str(item.get("operation_id", "")),
                str(item.get("path", "")),
                str(item.get("method", "")),
            )
            not in remove_keys
        ]