from __future__ import annotations

from dataclasses import dataclass

from api_testing_agent.core.feedback_scope_agent import FeedbackScopeAgent
from api_testing_agent.logging_config import bind_logger, get_logger


@dataclass(frozen=True)
class FeedbackScopeResult:
    operation_contexts: list[dict]
    scope_note: str | None = None


class FeedbackScopeRefiner:
    """
    Applies AI-planned scope patches to current operation scope.

    This refiner is catalog-driven:
    - It does not hard-code endpoint names, tags, or groups.
    - It only applies operation ids / paths / tags that exist in all_operation_contexts.
    - If AI fails, it never crashes the workflow.
    """

    def __init__(self, feedback_scope_agent: FeedbackScopeAgent) -> None:
        self._feedback_scope_agent = feedback_scope_agent
        self._logger = get_logger(__name__)

        self._logger.info(
            "Initialized FeedbackScopeRefiner.",
            extra={"payload_source": "feedback_scope_refiner_init"},
        )

    def refine(
        self,
        *,
        target_name: str,
        current_operation_contexts: list[dict],
        all_operation_contexts: list[dict],
        feedback_history: list[str],
    ) -> FeedbackScopeResult:
        logger = bind_logger(
            self._logger,
            target_name=target_name,
            payload_source="feedback_scope_refine",
        )
        logger.info(
            "Starting scope refinement. "
            f"current_scope={len(current_operation_contexts)}, "
            f"all_scope={len(all_operation_contexts)}, "
            f"feedback_history={len(feedback_history)}"
        )

        if not feedback_history:
            logger.info("No feedback history found. Keeping current scope.")
            return FeedbackScopeResult(
                operation_contexts=current_operation_contexts,
                scope_note=None,
            )

        latest_feedback = feedback_history[-1].strip()
        if not latest_feedback:
            logger.info("Latest feedback is empty. Keeping current scope.")
            return FeedbackScopeResult(
                operation_contexts=current_operation_contexts,
                scope_note=None,
            )

        logger.info("Invoking FeedbackScopeAgent for scope refinement.")

        try:
            decision = self._feedback_scope_agent.decide(
                feedback_text=latest_feedback,
                target_name=target_name,
                all_operation_hints=self._build_operation_hints(all_operation_contexts),
                current_scope_hints=self._build_operation_hints(current_operation_contexts),
            )
        except Exception as exc:
            logger.exception(f"FeedbackScopeAgent failed; keeping current scope: {exc}")
            return FeedbackScopeResult(
                operation_contexts=current_operation_contexts,
                scope_note=(
                    "Không thể dùng AI để cập nhật phạm vi test ở lượt này "
                    f"do lỗi tạm thời: {exc}. Giữ nguyên scope hiện tại để workflow không bị hỏng."
                ),
            )

        logger.info(
            "Feedback scope refinement decision received. "
            f"action_mode={decision.action_mode}, confidence={decision.confidence}"
        )

        action_mode = str(decision.action_mode).strip()

        if action_mode == "keep":
            logger.info("Keeping current scope based on feedback decision.")
            return FeedbackScopeResult(
                operation_contexts=current_operation_contexts,
                scope_note="Feedback không thay đổi phạm vi test. Giữ nguyên scope hiện tại.",
            )

        if action_mode == "reset_all":
            logger.info("Resetting scope to all operations.")
            return FeedbackScopeResult(
                operation_contexts=all_operation_contexts,
                scope_note="Feedback đã chuyển phạm vi về: toàn bộ chức năng của target.",
            )

        if action_mode == "invalid_feedback":
            invalid_text = decision.invalid_feedback_text or latest_feedback
            logger.warning(f"Feedback marked as invalid. invalid_text={invalid_text}")
            return FeedbackScopeResult(
                operation_contexts=current_operation_contexts,
                scope_note=(
                    f"Không áp dụng được feedback '{invalid_text}' vì không map được vào "
                    "operation hiện có. Giữ nguyên phạm vi hiện tại."
                ),
            )

        if action_mode in {"update_scope", "mixed_mutation"}:
            patched = self._apply_patch_decision(
                current_operation_contexts=current_operation_contexts,
                all_operation_contexts=all_operation_contexts,
                final_operation_ids=list(decision.final_operation_ids),
                final_paths=list(decision.final_paths),
                final_tags=list(decision.final_tags),
                add_operation_ids=list(decision.add_operation_ids),
                add_paths=list(decision.add_paths),
                add_tags=list(decision.add_tags),
                remove_operation_ids=list(decision.remove_operation_ids),
                remove_paths=list(decision.remove_paths),
                remove_tags=list(decision.remove_tags),
            )

            if not patched:
                logger.warning("Mixed scope mutation produced an empty or unmapped scope.")
                return FeedbackScopeResult(
                    operation_contexts=current_operation_contexts,
                    scope_note=(
                        f"Feedback '{latest_feedback}' đã được hiểu là sửa scope phức hợp, "
                        "nhưng không map được đủ operation hợp lệ. Giữ nguyên phạm vi hiện tại."
                    ),
                )

            logger.info(
                f"Applied mixed scope mutation. final_scope={len(patched)}"
            )
            return FeedbackScopeResult(
                operation_contexts=patched,
                scope_note=f"Feedback đã cập nhật phạm vi test theo yêu cầu: {latest_feedback}",
            )

        matched_operations = self._resolve_operations(
            all_operation_contexts=all_operation_contexts,
            operation_ids=list(decision.matched_operation_ids),
            paths=list(decision.matched_paths),
            tags=list(decision.matched_tags),
        )

        logger.info(
            f"Resolved matched operations from feedback. count={len(matched_operations)}"
        )

        if not matched_operations:
            logger.warning(
                "Feedback intended to change scope but no operations could be mapped."
            )
            return FeedbackScopeResult(
                operation_contexts=current_operation_contexts,
                scope_note=(
                    f"Feedback '{latest_feedback}' đã được hiểu là sửa scope, "
                    "nhưng không map được vào operation hiện có. Giữ nguyên phạm vi hiện tại."
                ),
            )

        if action_mode == "replace_with_specific":
            logger.info("Replacing scope with specific matched operations.")
            return FeedbackScopeResult(
                operation_contexts=matched_operations,
                scope_note=f"Feedback đã thay phạm vi test thành: {latest_feedback}",
            )

        if action_mode == "add_specific":
            merged = self._merge_operations(
                current_operation_contexts=current_operation_contexts,
                extra_operations=matched_operations,
            )
            logger.info(
                f"Extended scope with specific operations. merged_count={len(merged)}"
            )
            return FeedbackScopeResult(
                operation_contexts=merged,
                scope_note=f"Feedback đã mở rộng phạm vi test theo yêu cầu: {latest_feedback}",
            )

        if action_mode == "remove_specific":
            reduced = self._remove_operations(
                current_operation_contexts=current_operation_contexts,
                remove_operations=matched_operations,
            )
            if not reduced:
                logger.warning("Remove operation would empty the scope. Keeping current scope.")
                return FeedbackScopeResult(
                    operation_contexts=current_operation_contexts,
                    scope_note=(
                        f"Feedback '{latest_feedback}' sẽ làm scope rỗng nên chưa áp dụng. "
                        "Bạn hãy chọn ít nhất một operation để test."
                    ),
                )

            logger.info(
                f"Reduced scope by removing specific operations. reduced_count={len(reduced)}"
            )
            return FeedbackScopeResult(
                operation_contexts=reduced,
                scope_note=f"Feedback đã loại bớt phạm vi test theo yêu cầu: {latest_feedback}",
            )

        logger.info("Fallback: keeping current scope.")
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
                    "auth_required": item.get("auth_required"),
                }
            )
        return hints

    def _apply_patch_decision(
        self,
        *,
        current_operation_contexts: list[dict],
        all_operation_contexts: list[dict],
        final_operation_ids: list[str],
        final_paths: list[str],
        final_tags: list[str],
        add_operation_ids: list[str],
        add_paths: list[str],
        add_tags: list[str],
        remove_operation_ids: list[str],
        remove_paths: list[str],
        remove_tags: list[str],
    ) -> list[dict]:
        final_operations = self._resolve_operations(
            all_operation_contexts=all_operation_contexts,
            operation_ids=final_operation_ids,
            paths=final_paths,
            tags=final_tags,
        )
        if final_operations:
            return final_operations

        add_operations = self._resolve_operations(
            all_operation_contexts=all_operation_contexts,
            operation_ids=add_operation_ids,
            paths=add_paths,
            tags=add_tags,
        )
        remove_operations = self._resolve_operations(
            all_operation_contexts=all_operation_contexts,
            operation_ids=remove_operation_ids,
            paths=remove_paths,
            tags=remove_tags,
        )

        patched = list(current_operation_contexts)

        if remove_operations:
            patched = self._remove_operations(
                current_operation_contexts=patched,
                remove_operations=remove_operations,
            )

        if add_operations:
            patched = self._merge_operations(
                current_operation_contexts=patched,
                extra_operations=add_operations,
            )

        return patched

    def _resolve_operations(
        self,
        *,
        all_operation_contexts: list[dict],
        operation_ids: list[str],
        paths: list[str],
        tags: list[str],
    ) -> list[dict]:
        matched_ids = {
            str(item).strip()
            for item in operation_ids
            if str(item).strip()
        }
        matched_paths = {
            self._normalize_ref(item)
            for item in paths
            if str(item).strip()
        }
        matched_tags = {
            self._normalize_ref(item)
            for item in tags
            if str(item).strip()
        }

        resolved: list[dict] = []

        for operation in all_operation_contexts:
            op_id = str(operation.get("operation_id", "")).strip()
            path = self._normalize_ref(operation.get("path", ""))
            operation_tags = {
                self._normalize_ref(tag)
                for tag in operation.get("tags", [])
                if str(tag).strip()
            }

            if matched_ids and op_id in matched_ids:
                resolved.append(operation)
                continue

            if matched_paths and path in matched_paths:
                resolved.append(operation)
                continue

            if matched_tags and operation_tags.intersection(matched_tags):
                resolved.append(operation)
                continue

        return self._unique_operations(resolved)

    def _merge_operations(
        self,
        *,
        current_operation_contexts: list[dict],
        extra_operations: list[dict],
    ) -> list[dict]:
        merged = list(current_operation_contexts)
        seen = self._operation_key_set(merged)

        for item in extra_operations:
            key = self._operation_key(item)
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
        remove_keys = self._operation_key_set(remove_operations)

        return [
            item
            for item in current_operation_contexts
            if self._operation_key(item) not in remove_keys
        ]

    def _unique_operations(self, operations: list[dict]) -> list[dict]:
        unique: list[dict] = []
        seen: set[tuple[str, str, str]] = set()

        for item in operations:
            key = self._operation_key(item)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)

        return unique

    def _operation_key_set(self, operations: list[dict]) -> set[tuple[str, str, str]]:
        return {self._operation_key(item) for item in operations}

    def _operation_key(self, operation: dict) -> tuple[str, str, str]:
        return (
            str(operation.get("operation_id", "")),
            str(operation.get("path", "")),
            str(operation.get("method", "")),
        )

    def _normalize_ref(self, value: object) -> str:
        return str(value or "").strip().lower()