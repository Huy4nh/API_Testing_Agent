from __future__ import annotations

import re
from typing import Any, Callable

from api_testing_agent.core.report_interaction_models import (
    ReportIntentDecision,
    ReportInteractionState,
    ReportUserIntent,
)
from api_testing_agent.logging_config import bind_logger, get_logger

from api_testing_agent.core.report_hybrid_ai import ReportIntentHybridAIProtocol

FallbackIntentResolver = Callable[
    [str, dict[str, Any]],
    ReportIntentDecision | None,
]


class ReportIntentAgent:
    def __init__(
        self,
        fallback_resolver: FallbackIntentResolver | None = None,
        hybrid_ai: ReportIntentHybridAIProtocol | None = None,
    ) -> None:
        self._fallback_resolver = fallback_resolver
        self._hybrid_ai = hybrid_ai
        self._logger = get_logger(__name__)
    def detect(
        self,
        message: str,
        state: ReportInteractionState | dict[str, Any] | None = None,
    ) -> ReportIntentDecision:
        cleaned = message.strip()
        lowered = self._normalize(cleaned)

        thread_id = self._safe_get(state, "thread_id")
        target_name = self._safe_get(state, "target_name")

        logger = bind_logger(
            self._logger,
            thread_id=str(thread_id or "-"),
            target_name=str(target_name or "-"),
            payload_source="report_intent_detect",
        )
        logger.info(f"Detecting report intent from message={cleaned!r}")

        if not cleaned:
            decision = ReportIntentDecision(
                intent=ReportUserIntent.UNKNOWN,
                confidence=0.2,
                reason="Empty message after final report.",
            )
            logger.info(f"Detected intent={decision.intent.value}")
            return decision

        cancel_decision = self._detect_cancel(cleaned, lowered)
        if cancel_decision is not None:
            logger.info(f"Detected intent={cancel_decision.intent.value}")
            return cancel_decision

        finalize_decision = self._detect_finalize(cleaned, lowered)
        if finalize_decision is not None:
            logger.info(f"Detected intent={finalize_decision.intent.value}")
            return finalize_decision

        share_decision = self._detect_share(cleaned, lowered)
        if share_decision is not None:
            logger.info(f"Detected intent={share_decision.intent.value}")
            return share_decision

        rerun_decision = self._detect_rerun(cleaned, lowered)
        if rerun_decision is not None:
            logger.info(f"Detected intent={rerun_decision.intent.value}")
            return rerun_decision

        revise_text_decision = self._detect_revise_report_text(cleaned, lowered)
        if revise_text_decision is not None:
            logger.info(f"Detected intent={revise_text_decision.intent.value}")
            return revise_text_decision

        ask_decision = self._detect_question(cleaned, lowered)
        if ask_decision is not None:
            logger.info(f"Detected intent={ask_decision.intent.value}")
            return ask_decision

        if self._hybrid_ai is not None:
            try:
                ai_result = self._hybrid_ai.decide_report_intent(
                    thread_id=str(thread_id or ""),
                    target_name=str(target_name or ""),
                    user_text=cleaned,
                    final_report_data=dict(self._safe_get(state, "final_report_data") or {}),
                    current_markdown=str(self._safe_get(state, "final_report_markdown") or ""),
                    messages=list(self._safe_get(state, "messages") or []),
                )

                raw_intent = str(
                    ai_result.get(
                        "intent",
                        ReportUserIntent.ASK_REPORT_QUESTION.value,
                    )
                )
                confidence = float(ai_result.get("confidence", 0.5))
                reason = str(
                    ai_result.get(
                        "reason",
                        "AI fallback intent classification.",
                    )
                )

                mapped_intent = ReportUserIntent(raw_intent)

                decision = ReportIntentDecision(
                    intent=mapped_intent,
                    confidence=confidence,
                    reason=reason,
                    revision_instruction=ai_result.get("revision_instruction"),
                    rerun_instruction=ai_result.get("rerun_instruction"),
                )
                logger.info(f"AI fallback detected intent={decision.intent.value}")
                return decision
            except Exception as exc:
                logger.warning(f"Hybrid AI report intent fallback failed: {exc}")

        if self._fallback_resolver is not None:
            try:
                resolved = self._fallback_resolver(cleaned, dict(state or {}))
                if resolved is not None:
                    logger.info(
                        f"Fallback resolver returned intent={resolved.intent.value}"
                    )
                    return resolved
            except Exception as exc:
                logger.warning(f"Fallback resolver failed: {exc}")

        decision = ReportIntentDecision(
            intent=ReportUserIntent.ASK_REPORT_QUESTION,
            confidence=0.45,
            reason="No strong action intent; fallback to conversational Q&A.",
        )
        logger.info(f"Detected intent={decision.intent.value}")
        return decision

    def _detect_cancel(
        self,
        raw: str,
        lowered: str,
    ) -> ReportIntentDecision | None:
        tokens = [
            "hủy",
            "huy",
            "cancel",
            "bỏ hết",
            "bo het",
            "không lưu",
            "khong luu",
            "discard",
            "bỏ kết quả",
            "bo ket qua",
        ]
        if self._contains_any(lowered, tokens):
            return ReportIntentDecision(
                intent=ReportUserIntent.CANCEL_REPORT,
                confidence=0.98,
                reason="Detected explicit cancel/discard instruction.",
            )
        return None

    def _detect_finalize(
        self,
        raw: str,
        lowered: str,
    ) -> ReportIntentDecision | None:
        exact_confirms = {
            "ok",
            "oke",
            "ok rồi",
            "ok roi",
            "ổn",
            "on",
            "ổn rồi",
            "on roi",
            "done",
            "save",
            "lưu",
            "luu",
            "lưu đi",
            "luu di",
            "đồng ý",
            "dong y",
            "chốt",
            "chot",
            "approve",
            "approved",
        }

        normalized_exact = lowered.strip()
        if normalized_exact in exact_confirms:
            return ReportIntentDecision(
                intent=ReportUserIntent.FINALIZE_REPORT,
                confidence=0.97,
                reason="Detected explicit short finalize confirmation.",
            )

        if (
            self._contains_any(lowered, ["lưu", "luu", "save", "finalize", "chốt", "dong y"])
            and not self._looks_like_question(lowered)
        ):
            return ReportIntentDecision(
                intent=ReportUserIntent.FINALIZE_REPORT,
                confidence=0.9,
                reason="Detected save/finalize language without question pattern.",
            )

        return None

    def _detect_share(
        self,
        raw: str,
        lowered: str,
    ) -> ReportIntentDecision | None:
        tokens = [
            "chia sẻ",
            "chia se",
            "share",
            "gửi team",
            "gui team",
            "gửi sếp",
            "gui sep",
            "tóm tắt để gửi",
            "tom tat de gui",
            "summary để gửi",
            "summary de gui",
        ]
        if self._contains_any(lowered, tokens):
            return ReportIntentDecision(
                intent=ReportUserIntent.SHARE_REPORT,
                confidence=0.92,
                reason="Detected share/export summary intent.",
            )
        return None

    def _detect_rerun(
        self,
        raw: str,
        lowered: str,
    ) -> ReportIntentDecision | None:
        strong_rerun_tokens = [
            "chạy lại",
            "chay lai",
            "rerun",
            "re-run",
            "test lại",
            "test lai",
            "run lại",
            "run lai",
            "retest",
        ]
        if self._contains_any(lowered, strong_rerun_tokens):
            return ReportIntentDecision(
                intent=ReportUserIntent.REVISE_AND_RERUN,
                confidence=0.97,
                reason="Detected explicit rerun instruction.",
                rerun_instruction=raw,
            )

        scope_change_tokens = [
            "bỏ ",
            "bo ",
            "thêm ",
            "them ",
            "chỉ ",
            "chi ",
            "only ",
            "exclude ",
            "include ",
            "không cần",
            "khong can",
            "đổi ",
            "doi ",
            "sửa ",
            "sua ",
        ]

        test_related_tokens = [
            "test",
            "case",
            "endpoint",
            "module",
            "positive",
            "negative",
            "unauthorized",
            "not found",
            "missing",
            "invalid",
            "get",
            "post",
            "put",
            "patch",
            "delete",
            "schema",
            "required",
            "field",
            "auth",
        ]

        if self._contains_any(lowered, scope_change_tokens) and self._contains_any(
            lowered,
            test_related_tokens,
        ):
            return ReportIntentDecision(
                intent=ReportUserIntent.REVISE_AND_RERUN,
                confidence=0.84,
                reason="Detected scope/test adjustment language likely requiring rerun.",
                rerun_instruction=raw,
            )

        return None

    def _detect_revise_report_text(
        self,
        raw: str,
        lowered: str,
    ) -> ReportIntentDecision | None:
        tokens = [
            "viết lại",
            "viet lai",
            "chỉnh report",
            "chinh report",
            "sửa report",
            "sua report",
            "đổi format",
            "doi format",
            "gọn hơn",
            "gon hon",
            "ngắn hơn",
            "ngan hon",
            "ngắn gọn",
            "ngan gon",
            "chi tiết hơn",
            "chi tiet hon",
            "chi tiết",
            "chi tiet",
            "dài hơn",
            "dai hon",
            "bullet",
            "gạch đầu dòng",
            "gach dau dong",
            "dễ hiểu hơn",
            "de hieu hon",
            "trình bày lại",
            "trinh bay lai",
            "summary ngắn",
            "summary ngan",
        ]
        if self._contains_any(lowered, tokens):
            return ReportIntentDecision(
                intent=ReportUserIntent.REVISE_REPORT_TEXT,
                confidence=0.9,
                reason="Detected report rewriting/reformatting intent.",
                revision_instruction=raw,
            )
        return None

    def _detect_question(
        self,
        raw: str,
        lowered: str,
    ) -> ReportIntentDecision | None:
        if "?" in raw:
            return ReportIntentDecision(
                intent=ReportUserIntent.ASK_REPORT_QUESTION,
                confidence=0.9,
                reason="Detected question mark in message.",
            )

        question_tokens = [
            "vì sao",
            "vi sao",
            "tại sao",
            "tai sao",
            "giải thích",
            "giai thich",
            "explain",
            "why",
            "how",
            "sao",
            "case nào",
            "case nao",
            "fail ở đâu",
            "fail o dau",
            "skip vì sao",
            "skip vi sao",
            "tóm tắt",
            "tom tat",
            "summary",
            "phân tích",
            "phan tich",
        ]
        if self._contains_any(lowered, question_tokens):
            return ReportIntentDecision(
                intent=ReportUserIntent.ASK_REPORT_QUESTION,
                confidence=0.82,
                reason="Detected explanatory or analytical question language.",
            )

        return None

    def _normalize(self, text: str) -> str:
        text = text.strip().lower()
        text = re.sub(r"\s+", " ", text)
        return text

    def _contains_any(
        self,
        text: str,
        tokens: list[str],
    ) -> bool:
        return any(token in text for token in tokens)

    def _looks_like_question(self, lowered: str) -> bool:
        return self._contains_any(
            lowered,
            [
                "?",
                "vì sao",
                "vi sao",
                "tại sao",
                "tai sao",
                "why",
                "how",
                "giải thích",
                "giai thich",
            ],
        )

    def _safe_get(
        self,
        state: ReportInteractionState | dict[str, Any] | None,
        key: str,
    ) -> Any:
        if state is None:
            return None
        if isinstance(state, dict):
            return state.get(key)
        return getattr(state, key, None)