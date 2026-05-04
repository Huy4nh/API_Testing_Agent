from __future__ import annotations

import re
import unicodedata

from api_testing_agent.logging_config import bind_logger, get_logger
from api_testing_agent.tasks.workflow_models import (
    RouterDecision,
    RouterIntent,
    WorkflowContextSnapshot,
    WorkflowPhase,
)


class ConversationRouter:
    def __init__(self) -> None:
        self._logger = get_logger(__name__)

    def route(
        self,
        *,
        message: str,
        snapshot: WorkflowContextSnapshot | None,
    ) -> RouterDecision:
        cleaned = message.strip()
        lowered = self._normalize(cleaned)
        lowered_ascii = self._normalize_ascii(cleaned)

        thread_id = snapshot.thread_id if snapshot is not None else "-"
        target_name = snapshot.selected_target if snapshot is not None else "-"

        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            target_name=str(target_name or "-"),
            payload_source="conversation_router_route",
        )
        logger.info(f"Routing message={cleaned!r}")

        if not cleaned:
            return RouterDecision(
                intent=RouterIntent.CLARIFY,
                confidence=0.2,
                reason="Empty message.",
                normalized_message=cleaned,
                clarification_question="Tin nhắn đang rỗng. Bạn hãy nhập nội dung cụ thể hơn.",
            )

        if snapshot is None:
            if self._looks_like_help(lowered, lowered_ascii):
                return RouterDecision(
                    intent=RouterIntent.HELP,
                    confidence=0.95,
                    reason="Help requested with no active workflow.",
                    normalized_message=cleaned,
                )

            if self._looks_like_status(lowered, lowered_ascii):
                return RouterDecision(
                    intent=RouterIntent.STATUS,
                    confidence=0.9,
                    reason="Status requested with no active workflow.",
                    normalized_message=cleaned,
                )

            return RouterDecision(
                intent=RouterIntent.START_NEW_WORKFLOW,
                confidence=0.95,
                reason="No active workflow snapshot. Treat as new workflow.",
                normalized_message=cleaned,
            )

        phase = snapshot.phase

        # Ưu tiên câu hỏi scope/function theo phase trước help/status chung
        if phase == WorkflowPhase.PENDING_REVIEW:
            if self._looks_like_review_scope_question(lowered, lowered_ascii):
                return RouterDecision(
                    intent=RouterIntent.SHOW_REVIEW_SCOPE,
                    confidence=0.96,
                    reason="Detected review scope question while pending review.",
                    normalized_message=cleaned,
                )

        if phase == WorkflowPhase.PENDING_SCOPE_CONFIRMATION:
            if self._looks_like_scope_recommendation_question(lowered, lowered_ascii):
                return RouterDecision(
                    intent=RouterIntent.ASK_SCOPE_RECOMMENDATION,
                    confidence=0.97,
                    reason="Detected scope recommendation question.",
                    normalized_message=cleaned,
                )

            if self._looks_like_apply_scope_recommendation(lowered, lowered_ascii):
                if self._has_latest_scope_recommendation(snapshot):
                    return RouterDecision(
                        intent=RouterIntent.APPLY_SCOPE_RECOMMENDATION,
                        confidence=0.97,
                        reason="Detected request to apply the latest scope recommendation.",
                        normalized_message=cleaned,
                    )

                return RouterDecision(
                    intent=RouterIntent.CLARIFY,
                    confidence=0.7,
                    reason="User referred to a recommendation, but no latest scope recommendation is available.",
                    normalized_message=cleaned,
                    clarification_question=(
                        "Tôi chưa có gợi ý scope nào gần đây để áp dụng. "
                        "Bạn muốn tôi gợi ý lại nhóm nên test trước không?"
                    ),
                )

            if self._looks_like_scope_catalog_question(lowered, lowered_ascii):
                return RouterDecision(
                    intent=RouterIntent.SHOW_SCOPE_CATALOG,
                    confidence=0.97,
                    reason="Detected scope catalog question.",
                    normalized_message=cleaned,
                )

            group_selector = self._extract_scope_group_selector(
                cleaned,
                lowered,
                lowered_ascii,
            )
            if group_selector is not None:
                return RouterDecision(
                    intent=RouterIntent.SHOW_SCOPE_GROUP_DETAILS,
                    confidence=0.95,
                    reason="Detected request to inspect a scope group.",
                    normalized_message=cleaned,
                    metadata={"group_selector": group_selector},
                )

            operation_selector = self._extract_scope_operation_selector(
                cleaned,
                lowered,
                lowered_ascii,
            )
            if operation_selector is not None:
                return RouterDecision(
                    intent=RouterIntent.SHOW_SCOPE_OPERATION_DETAILS,
                    confidence=0.95,
                    reason="Detected request to inspect a specific operation.",
                    normalized_message=cleaned,
                    metadata={"operation_selector": operation_selector},
                )

        if self._looks_like_help(lowered, lowered_ascii):
            return RouterDecision(
                intent=RouterIntent.HELP,
                confidence=0.98,
                reason="Detected help/meta request.",
                normalized_message=cleaned,
            )

        if self._looks_like_status(lowered, lowered_ascii):
            return RouterDecision(
                intent=RouterIntent.STATUS,
                confidence=0.98,
                reason="Detected status/meta request.",
                normalized_message=cleaned,
            )

        possible_new_workflow = self._looks_like_possible_new_workflow(
            lowered,
            lowered_ascii,
        )
        strong_new_workflow = self._looks_like_strong_new_workflow(
            lowered,
            lowered_ascii,
        )
        report_related = self._looks_like_report_related(lowered, lowered_ascii)

        if phase == WorkflowPhase.PENDING_TARGET_SELECTION:
            if strong_new_workflow:
                return RouterDecision(
                    intent=RouterIntent.CLARIFY,
                    confidence=0.84,
                    reason="Looks like a new task while target selection is pending.",
                    normalized_message=cleaned,
                    clarification_question=(
                        "Bạn đang ở bước chọn target cho workflow hiện tại. "
                        "Bạn muốn tiếp tục chọn target cho workflow này, hay mở workflow mới?"
                    ),
                )

            return RouterDecision(
                intent=RouterIntent.RESUME_TARGET_SELECTION,
                confidence=0.97,
                reason="Current phase is pending_target_selection.",
                normalized_message=cleaned,
            )

        if phase == WorkflowPhase.PENDING_SCOPE_CONFIRMATION:
            if self._looks_like_scope_confirmation_reply(lowered, lowered_ascii):
                return RouterDecision(
                    intent=RouterIntent.RESUME_SCOPE_CONFIRMATION,
                    confidence=0.96,
                    reason="Detected explicit scope confirmation or refinement reply.",
                    normalized_message=cleaned,
                )

            if strong_new_workflow and not report_related:
                return RouterDecision(
                    intent=RouterIntent.CLARIFY,
                    confidence=0.83,
                    reason="Looks like a new task while scope confirmation is pending.",
                    normalized_message=cleaned,
                    clarification_question=(
                        "Bạn đang ở bước xác nhận phạm vi test. "
                        "Bạn muốn tiếp tục chọn scope hiện tại, hay mở workflow mới?"
                    ),
                )

            return RouterDecision(
                intent=RouterIntent.CLARIFY,
                confidence=0.65,
                reason="Ambiguous message during pending scope confirmation.",
                normalized_message=cleaned,
                clarification_question=(
                    "Bạn có thể trả lời kiểu: `test hết`, `chỉ test 1 đến 3`, "
                    "`bỏ nhóm NFTs`, `xem chi tiết nhóm Coins`, hoặc `chi tiết GET /coins/{id}`."
                ),
            )

        if phase == WorkflowPhase.PENDING_REVIEW:
            if possible_new_workflow:
                return RouterDecision(
                    intent=RouterIntent.CLARIFY,
                    confidence=0.82,
                    reason="Looks like a new task while review is pending.",
                    normalized_message=cleaned,
                    clarification_question=(
                        "Bạn đang ở bước review testcase draft. "
                        "Bạn muốn phản hồi draft hiện tại, hay mở workflow mới?"
                    ),
                )

            if self._looks_like_review_action(lowered, lowered_ascii):
                return RouterDecision(
                    intent=RouterIntent.RESUME_REVIEW,
                    confidence=0.97,
                    reason="Detected pending review action.",
                    normalized_message=cleaned,
                )

            return RouterDecision(
                intent=RouterIntent.CLARIFY,
                confidence=0.6,
                reason="Ambiguous message during pending review.",
                normalized_message=cleaned,
                clarification_question=(
                    "Bạn đang ở bước review. Bạn có thể approve, yêu cầu revise, "
                    "hỏi về scope hiện tại, hoặc cancel."
                ),
            )

        if phase in {
            WorkflowPhase.FINAL_REPORT_STAGED,
            WorkflowPhase.REPORT_INTERACTION,
            WorkflowPhase.RERUN_REQUESTED,
        }:
            if strong_new_workflow and not report_related:
                return RouterDecision(
                    intent=RouterIntent.CLARIFY,
                    confidence=0.86,
                    reason="Looks like a brand-new task while report interaction is active.",
                    normalized_message=cleaned,
                    clarification_question=(
                        "Bạn đang ở phiên tương tác với final report hiện tại. "
                        "Bạn muốn tiếp tục report này, hay mở workflow test mới?"
                    ),
                )

            return RouterDecision(
                intent=RouterIntent.CONTINUE_REPORT_INTERACTION,
                confidence=0.95,
                reason="Current phase is report interaction or staged final report.",
                normalized_message=cleaned,
            )

        if phase in {
            WorkflowPhase.APPROVED,
            WorkflowPhase.EXECUTING,
            WorkflowPhase.VALIDATING,
        }:
            return RouterDecision(
                intent=RouterIntent.STATUS,
                confidence=0.84,
                reason="Workflow is in a processing phase; best response is status.",
                normalized_message=cleaned,
            )

        if phase in {WorkflowPhase.FINALIZED, WorkflowPhase.CANCELLED}:
            if strong_new_workflow or possible_new_workflow:
                return RouterDecision(
                    intent=RouterIntent.START_NEW_WORKFLOW,
                    confidence=0.95,
                    reason="Previous workflow is terminal; start a new one.",
                    normalized_message=cleaned,
                )

            return RouterDecision(
                intent=RouterIntent.CLARIFY,
                confidence=0.75,
                reason="Terminal workflow phase with ambiguous message.",
                normalized_message=cleaned,
                clarification_question=(
                    "Workflow hiện tại đã kết thúc. "
                    "Nếu bạn muốn test tiếp, hãy gửi yêu cầu test mới rõ ràng."
                ),
            )

        return RouterDecision(
            intent=RouterIntent.UNKNOWN,
            confidence=0.4,
            reason="No routing rule matched strongly.",
            normalized_message=cleaned,
            clarification_question=(
                "Tôi chưa xác định được bạn muốn làm gì ở workflow hiện tại. "
                "Bạn có thể nói rõ hơn không?"
            ),
        )

    def _normalize(self, text: str) -> str:
        text = text.strip().lower()
        text = re.sub(r"\s+", " ", text)
        return text

    def _normalize_ascii(self, text: str) -> str:
        lowered = self._normalize(text)
        normalized = unicodedata.normalize("NFD", lowered)
        without_accents = "".join(
            ch for ch in normalized if unicodedata.category(ch) != "Mn"
        )
        return without_accents.replace("đ", "d").replace("Đ", "D")

    def _contains_any(self, lowered: str, lowered_ascii: str, tokens: list[str]) -> bool:
        return any(token in lowered or token in lowered_ascii for token in tokens)

    def _has_latest_scope_recommendation(
        self,
        snapshot: WorkflowContextSnapshot | None,
    ) -> bool:
        if snapshot is None:
            return False
        recommendation = getattr(snapshot, "latest_scope_recommendation", None)
        if recommendation is None:
            return False
        has_payload = getattr(recommendation, "has_payload", None)
        if callable(has_payload):
            return bool(has_payload())
        return False

    def _looks_like_help(self, lowered: str, lowered_ascii: str) -> bool:
        tokens = [
            "help",
            "trợ giúp",
            "tro giup",
            "hướng dẫn",
            "huong dan",
        ]
        return self._contains_any(lowered, lowered_ascii, tokens)

    def _looks_like_status(self, lowered: str, lowered_ascii: str) -> bool:
        tokens = [
            "status",
            "đang ở bước nào",
            "dang o buoc nao",
            "đang làm gì",
            "dang lam gi",
            "tiến độ",
            "tien do",
            "workflow đang ở đâu",
            "workflow dang o dau",
            "phase",
            "trạng thái",
            "trang thai",
        ]
        return self._contains_any(lowered, lowered_ascii, tokens)

    def _looks_like_review_scope_question(self, lowered: str, lowered_ascii: str) -> bool:
        tokens = [
            "đang có những chức năng nào",
            "dang co nhung chuc nang nao",
            "hiện đang có những chức năng nào",
            "hien dang co nhung chuc nang nao",
            "có những chức năng nào",
            "co nhung chuc nang nao",
            "có những chức năng gì",
            "co nhung chuc nang gi",
            "hiện có những chức năng nào",
            "hien co nhung chuc nang nao",
            "hiện có những chức năng gì",
            "hien co nhung chuc nang gi",
            "chức năng nào",
            "chuc nang nao",
            "chức nang nào",
            "chuc nang nao",
            "operation nào",
            "operation nao",
            "operations nào",
            "operations nao",
            "scope hiện tại",
            "scope hien tai",
            "đang test những gì",
            "dang test nhung gi",
            "đang review cái gì",
            "dang review cai gi",
            "hiện có gì",
            "hien co gi",
            "what functions are available",
            "what operations are available",
            "what functions do we have",
            "what capabilities are available",
            "what can this target do",
            "what does this target do",
            "show current scope",
            "show review scope",
            "target này làm được gì",
            "target nay lam duoc gi",
            "target này làm được gì vậy",
            "target nay lam duoc gi vay",
            "target này có gì",
            "target nay co gi",
            "target này làm gì",
            "target nay lam gi",
        ]
        return self._contains_any(lowered, lowered_ascii, tokens)

    def _looks_like_scope_catalog_question(self, lowered: str, lowered_ascii: str) -> bool:
        tokens = [
            "có những chức năng nào",
            "co nhung chuc nang nao",
            "hiện có những chức năng nào",
            "hien co nhung chuc nang nao",
            "có những nhóm nào",
            "co nhung nhom nao",
            "những nhóm chức năng nào",
            "nhung nhom chuc nang nao",
            "liệt kê chức năng",
            "liet ke chuc nang",
            "liệt kê nhóm",
            "liet ke nhom",
            "xem catalog",
            "show catalog",
            "show groups",
            "show functions",
            "show capabilities",
            "what groups are available",
            "what functions are available",
            "what capabilities are available",
        ]
        return self._contains_any(lowered, lowered_ascii, tokens)

    def _looks_like_scope_recommendation_question(
        self,
        lowered: str,
        lowered_ascii: str,
    ) -> bool:
        tokens = [
            "gợi ý",
            "goi y",
            "đề xuất",
            "de xuat",
            "nên test gì",
            "nen test gi",
            "nên test trước",
            "nen test truoc",
            "nhóm nào nên test trước",
            "nhom nao nen test truoc",
            "nhóm nào nên thử trước",
            "nhom nao nen thu truoc",
            "recommend",
            "suggest",
            "what should i test first",
            "which group should i test first",
        ]
        return self._contains_any(lowered, lowered_ascii, tokens)

    def _looks_like_apply_scope_recommendation(
        self,
        lowered: str,
        lowered_ascii: str,
    ) -> bool:
        tokens = [
            "thực hiện theo gợi ý",
            "thuc hien theo goi y",
            "theo gợi ý đi",
            "theo goi y di",
            "làm theo gợi ý",
            "lam theo goi y",
            "thực hiện theo đề xuất",
            "thuc hien theo de xuat",
            "làm theo đề xuất",
            "lam theo de xuat",
            "theo đề xuất đó",
            "theo de xuat do",
            "theo hướng đó",
            "theo huong do",
            "ok theo đó",
            "ok theo do",
            "ok theo gợi ý",
            "ok theo goi y",
            "apply recommendation",
            "apply the recommendation",
            "go with the recommendation",
            "go with that suggestion",
            "follow your suggestion",
            "use your suggestion",
            "test theo gợi ý",
            "test theo goi y",
            "test theo đề xuất",
            "test theo de xuat",
        ]
        return self._contains_any(lowered, lowered_ascii, tokens)

    def _extract_scope_group_selector(
        self,
        cleaned: str,
        lowered: str,
        lowered_ascii: str,
    ) -> str | None:
        prefixes = [
            "xem chi tiết nhóm ",
            "xem chi tiet nhom ",
            "chi tiết nhóm ",
            "chi tiet nhom ",
            "xem chi tiết group ",
            "xem chi tiet group ",
            "chi tiết group ",
            "chi tiet group ",
            "show group ",
            "details for group ",
            "inspect group ",
        ]

        for prefix in prefixes:
            if lowered.startswith(prefix) or lowered_ascii.startswith(prefix):
                candidate = cleaned[len(prefix):].strip()
                return candidate or None

        return None

    def _extract_scope_operation_selector(
        self,
        cleaned: str,
        lowered: str,
        lowered_ascii: str,
    ) -> str | None:
        if re.match(r"^(get|post|put|patch|delete)\s+", lowered):
            return cleaned

        prefixes = [
            "chi tiết ",
            "chi tiet ",
            "xem chi tiết operation ",
            "xem chi tiet operation ",
            "xem chi tiết endpoint ",
            "xem chi tiet endpoint ",
            "show operation ",
            "details for ",
            "operation ",
            "endpoint ",
        ]

        for prefix in prefixes:
            if lowered.startswith(prefix) or lowered_ascii.startswith(prefix):
                candidate = cleaned[len(prefix):].strip()
                if candidate:
                    return candidate

        if "/" in cleaned and re.search(r"\b(get|post|put|patch|delete)\b", lowered):
            return cleaned

        return None

    def _looks_like_scope_confirmation_reply(
        self,
        lowered: str,
        lowered_ascii: str,
    ) -> bool:
        tokens = [
            "test hết",
            "test het",
            "all",
            "toàn bộ",
            "toan bo",
            "chỉ test",
            "chi test",
            "bỏ nhóm",
            "bo nhom",
            "bỏ operation",
            "bo operation",
            "bỏ endpoint",
            "bo endpoint",
            "test nhóm",
            "test nhom",
            "nhóm ",
            "nhom ",
            "group ",
            "operation ",
            "endpoint ",
            "từ ",
            "tu ",
            "đến",
            "den",
            "skip ",
            "only ",
            "just ",
            "excluding ",
        ]

        if self._contains_any(lowered, lowered_ascii, tokens):
            return True

        if re.search(r"\b\d+\s*(,|-|den|đến)\s*\d+", lowered) or re.search(
            r"\b\d+\s*(,|-|den|đến)\s*\d+",
            lowered_ascii,
        ):
            return True

        if re.match(r"^(get|post|put|patch|delete)\s+", lowered):
            return True

        return False

    def _looks_like_possible_new_workflow(self, lowered: str, lowered_ascii: str) -> bool:
        prefix_patterns = [
            r"^test\b",
            r"^test target\b",
            r"^chạy test\b",
            r"^chay test\b",
            r"^kiểm thử\b",
            r"^kiem thu\b",
            r"^hãy thử\b",
            r"^hay thu\b",
            r"^thử\b",
            r"^thu\b",
        ]
        prefix_match = any(
            re.search(pattern, lowered) or re.search(pattern, lowered_ascii)
            for pattern in prefix_patterns
        )
        if not prefix_match:
            return False

        task_signals = [
            "chức năng",
            "chuc nang",
            "login",
            "register",
            "auth",
            "module",
            "api",
            "endpoint",
            "staging",
            "production",
            "prod",
            "cms",
            "image",
            "img",
            "telegram",
            "post",
            "user",
            "yt",
            "youtube",
        ]
        return self._contains_any(lowered, lowered_ascii, task_signals)

    def _looks_like_strong_new_workflow(self, lowered: str, lowered_ascii: str) -> bool:
        prefix_patterns = [
            r"^test\b",
            r"^test target\b",
            r"^chạy test\b",
            r"^chay test\b",
            r"^kiểm thử\b",
            r"^kiem thu\b",
            r"^hãy thử\b",
            r"^hay thu\b",
        ]
        prefix_match = any(
            re.search(pattern, lowered) or re.search(pattern, lowered_ascii)
            for pattern in prefix_patterns
        )

        scope_signals = [
            " target ",
            " module ",
            " path ",
            " get",
            " post",
            " put",
            " patch",
            " delete",
            "/",
            " endpoint ",
            " api ",
            " staging",
            " production",
            " prod",
            " login",
            " register",
            " auth",
        ]
        has_scope_signal = any(
            signal in f" {lowered} " or signal in f" {lowered_ascii} "
            for signal in scope_signals
        )

        return prefix_match and has_scope_signal

    def _looks_like_review_action(self, lowered: str, lowered_ascii: str) -> bool:
        approve_tokens = [
            "tốt",
            "tot",
            "tốt rồi",
            "tot roi",
            "ổn",
            "on",
            "ổn rồi",
            "on roi",
            "ok",
            "ok rồi",
            "ok roi",
            "được",
            "duoc",
            "được rồi",
            "duoc roi",
            "approve",
            "approved",
            "duyet",
            "duyệt",
            "good",
            "looks good",
            "go on",
            "tiếp tục",
            "tiep tuc",
        ]
        revise_tokens = [
            "revise",
            "sửa",
            "sua",
            "chỉnh",
            "chinh",
            "thêm",
            "them",
            "bớt",
            "bot",
            "đổi",
            "doi",
            "viết lại",
            "viet lai",
            "change",
            "update",
        ]
        cancel_tokens = [
            "cancel",
            "hủy",
            "huy",
            "dừng",
            "dung",
            "stop",
        ]

        return (
            self._contains_any(lowered, lowered_ascii, approve_tokens)
            or self._contains_any(lowered, lowered_ascii, revise_tokens)
            or self._contains_any(lowered, lowered_ascii, cancel_tokens)
        )

    def _looks_like_report_related(self, lowered: str, lowered_ascii: str) -> bool:
        tokens = [
            "report",
            "báo cáo",
            "bao cao",
            "giải thích",
            "giai thich",
            "viết lại",
            "viet lai",
            "tóm tắt",
            "tom tat",
            "tóm tắt dễ hiểu",
            "tom tat de hieu",
            "dễ hiểu",
            "de hieu",
            "ngắn gọn",
            "ngan gon",
            "lưu",
            "luu",
            "hủy",
            "huy",
            "rerun",
            "chạy lại",
            "chay lai",
            "share",
            "summary",
            "summarize",
            "explain",
            "rewrite",
        ]
        return self._contains_any(lowered, lowered_ascii, tokens)