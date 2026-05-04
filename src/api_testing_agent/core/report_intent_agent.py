from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable

from api_testing_agent.core.report_hybrid_ai import ReportIntentHybridAIProtocol
from api_testing_agent.core.report_interaction_models import (
    ReportIntentDecision,
    ReportInteractionState,
    ReportUserIntent,
)
from api_testing_agent.logging_config import bind_logger, get_logger

FallbackIntentResolver = Callable[
    [str, dict[str, Any]],
    ReportIntentDecision | None,
]


class ReportIntentAgent:
    """
    AI-first report intent detector.

    Design:
    - Keep only a very thin hard-stop layer for *extremely explicit* destructive commands.
    - Let hybrid AI classify most realistic user messages first.
    - Use heuristics only as a fallback when AI is unavailable / fails / is too uncertain.
    """

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
        normalized = self._normalize(cleaned)

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

        # 1) Very thin hard-stop layer only for extremely explicit destructive commands.
        cancel_decision = self._detect_explicit_cancel(cleaned, normalized)
        if cancel_decision is not None:
            logger.info(f"Detected intent={cancel_decision.intent.value}")
            return cancel_decision

        finalize_decision = self._detect_explicit_finalize(cleaned, normalized)
        if finalize_decision is not None:
            logger.info(f"Detected intent={finalize_decision.intent.value}")
            return finalize_decision

        # 2) AI-first for realistic conversational requests.
        ai_decision = self._detect_with_ai(
            cleaned=cleaned,
            state=state,
            thread_id=str(thread_id or ""),
            target_name=str(target_name or ""),
            logger=logger,
        )
        if ai_decision is not None:
            logger.info(
                f"AI-first detected intent={ai_decision.intent.value} "
                f"confidence={ai_decision.confidence:.2f}"
            )
            return ai_decision

        # 3) Heuristic fallback only if AI is absent / failed / too uncertain.
        heuristic_decision = self._detect_with_heuristics(cleaned, normalized)
        if heuristic_decision is not None:
            logger.info(
                f"Heuristic fallback detected intent={heuristic_decision.intent.value}"
            )
            return heuristic_decision

        # 4) External fallback if configured.
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

    def _detect_with_ai(
        self,
        *,
        cleaned: str,
        state: ReportInteractionState | dict[str, Any] | None,
        thread_id: str,
        target_name: str,
        logger: Any,
    ) -> ReportIntentDecision | None:
        if self._hybrid_ai is None:
            return None

        try:
            ai_result = self._hybrid_ai.decide_report_intent(
                thread_id=thread_id,
                target_name=target_name,
                user_text=cleaned,
                final_report_data=dict(self._safe_get(state, "final_report_data") or {}),
                current_markdown=self._truncate_text(
                    str(self._safe_get(state, "final_report_markdown") or ""),
                    limit=6000,
                ),
                messages=self._trim_messages(
                    list(self._safe_get(state, "messages") or []),
                    keep_last=12,
                ),
            )

            raw_intent = str(
                ai_result.get(
                    "intent",
                    ReportUserIntent.ASK_REPORT_QUESTION.value,
                )
            )
            mapped_intent = self._safe_map_intent(raw_intent)
            confidence = self._coerce_confidence(ai_result.get("confidence", 0.5))
            reason = str(
                ai_result.get(
                    "reason",
                    "AI-first report intent classification.",
                )
            ).strip() or "AI-first report intent classification."

            decision = ReportIntentDecision(
                intent=mapped_intent,
                confidence=confidence,
                reason=reason,
                revision_instruction=self._coerce_optional_str(
                    ai_result.get("revision_instruction")
                ),
                rerun_instruction=self._coerce_optional_str(
                    ai_result.get("rerun_instruction")
                ),
            )

            if not self._accept_ai_decision(decision):
                logger.info(
                    "AI result was too uncertain for direct use; falling back.",
                    extra={
                        "payload_source": "report_intent_ai_uncertain",
                        "ai_intent": decision.intent.value,
                        "ai_confidence": decision.confidence,
                    },
                )
                return None

            return decision

        except Exception as exc:
            logger.warning(f"Hybrid AI report intent classification failed: {exc}")
            return None

    def _accept_ai_decision(self, decision: ReportIntentDecision) -> bool:
        """
        Allow AI-first routing, but require stronger confidence for destructive actions.
        Graph-level confirmation will still protect borderline destructive cases.
        """
        if decision.intent == ReportUserIntent.CANCEL_REPORT:
            return decision.confidence >= 0.70

        if decision.intent == ReportUserIntent.FINALIZE_REPORT:
            return decision.confidence >= 0.68

        if decision.intent in {
            ReportUserIntent.REVISE_REPORT_TEXT,
            ReportUserIntent.REVISE_AND_RERUN,
            ReportUserIntent.SHARE_REPORT,
            ReportUserIntent.ASK_REPORT_QUESTION,
        }:
            return decision.confidence >= 0.55

        if decision.intent == ReportUserIntent.UNKNOWN:
            return False

        return decision.confidence >= 0.60

    def _detect_with_heuristics(
        self,
        raw: str,
        normalized: str,
    ) -> ReportIntentDecision | None:
        # Order matters: rewrite/explain first, then rerun/share, then generic Q&A.
        revise_text_decision = self._detect_revise_report_text(raw, normalized)
        if revise_text_decision is not None:
            return revise_text_decision

        rerun_decision = self._detect_rerun(raw, normalized)
        if rerun_decision is not None:
            return rerun_decision

        share_decision = self._detect_share(raw, normalized)
        if share_decision is not None:
            return share_decision

        ask_decision = self._detect_question(raw, normalized)
        if ask_decision is not None:
            return ask_decision

        return None

    def _detect_explicit_cancel(
        self,
        raw: str,
        normalized: str,
    ) -> ReportIntentDecision | None:
        exact_commands = {
            "cancel",
            "cancel report",
            "cancel workflow",
            "huy",
            "huy di",
            "huy het",
            "huy report",
            "huy workflow",
            "bo report",
            "bo ket qua",
            "discard",
            "discard report",
            "stop report",
        }

        if normalized in exact_commands:
            return ReportIntentDecision(
                intent=ReportUserIntent.CANCEL_REPORT,
                confidence=0.99,
                reason="Detected explicit cancel/discard command.",
            )

        cancel_tokens = [
            "huy",
            "cancel",
            "discard",
            "stop",
            "bo",
        ]
        cancel_object_tokens = [
            "report",
            "workflow",
            "ket qua",
            "het",
            "tat ca",
            "di",
            "luon",
        ]
        non_cancel_tokens = [
            "viet lai",
            "giai thich",
            "phan tich",
            "tom tat",
            "summary",
            "rewrite",
            "explain",
            "rerun",
            "chay lai",
            "share",
            "chia se",
            "luu",
            "save",
            "finalize",
        ]

        if self._contains_any(normalized, cancel_tokens) and self._contains_any(
            normalized,
            cancel_object_tokens,
        ) and not self._contains_any(normalized, non_cancel_tokens):
            return ReportIntentDecision(
                intent=ReportUserIntent.CANCEL_REPORT,
                confidence=0.95,
                reason="Detected strong cancel language.",
            )

        return None

    def _detect_explicit_finalize(
        self,
        raw: str,
        normalized: str,
    ) -> ReportIntentDecision | None:
        exact_confirms = {
            "ok",
            "oke",
            "ok roi",
            "ok luu",
            "ok luu di",
            "on",
            "on roi",
            "done",
            "save",
            "save report",
            "luu",
            "luu di",
            "dong y",
            "dong y luu",
            "chot",
            "chot di",
            "finalize",
            "finalize report",
            "approve",
            "approve report",
            "approved",
        }

        if normalized in exact_confirms:
            return ReportIntentDecision(
                intent=ReportUserIntent.FINALIZE_REPORT,
                confidence=0.98,
                reason="Detected explicit finalize confirmation.",
            )

        finalize_tokens = [
            "luu",
            "save",
            "finalize",
            "approve",
            "approved",
            "chot",
        ]
        confirm_tokens = [
            "ok",
            "oke",
            "dong y",
            "done",
            "go ahead",
            "please",
            "di",
            "luon",
        ]
        non_finalize_tokens = [
            "viet lai",
            "giai thich",
            "phan tich",
            "tom tat",
            "summary",
            "rewrite",
            "explain",
            "rerun",
            "chay lai",
            "share",
            "chia se",
            "huy",
            "cancel",
            "discard",
        ]

        if self._contains_any(normalized, finalize_tokens) and not self._contains_any(
            normalized,
            non_finalize_tokens,
        ):
            if self._contains_any(normalized, confirm_tokens) or normalized in {
                "luu",
                "luu di",
                "save",
                "save report",
                "chot",
                "chot di",
                "finalize",
                "finalize report",
            }:
                return ReportIntentDecision(
                    intent=ReportUserIntent.FINALIZE_REPORT,
                    confidence=0.94,
                    reason="Detected strong finalize/save command.",
                )

        return None

    def _detect_share(
        self,
        raw: str,
        normalized: str,
    ) -> ReportIntentDecision | None:
        tokens = [
            "chia se",
            "share",
            "gui team",
            "gui sep",
            "de gui",
            "export",
            "send this report",
            "share this report",
            "send to team",
        ]
        if self._contains_any(normalized, tokens):
            return ReportIntentDecision(
                intent=ReportUserIntent.SHARE_REPORT,
                confidence=0.86,
                reason="Detected report sharing/export intent.",
            )
        return None

    def _detect_rerun(
        self,
        raw: str,
        normalized: str,
    ) -> ReportIntentDecision | None:
        strong_rerun_tokens = [
            "chay lai",
            "rerun",
            "re-run",
            "retest",
            "test lai",
            "run lai",
        ]
        if self._contains_any(normalized, strong_rerun_tokens):
            return ReportIntentDecision(
                intent=ReportUserIntent.REVISE_AND_RERUN,
                confidence=0.92,
                reason="Detected explicit rerun instruction.",
                rerun_instruction=raw,
            )

        scope_change_tokens = [
            "bo ",
            "them ",
            "chi ",
            "only ",
            "exclude ",
            "include ",
            "khong can",
            "doi ",
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

        if self._contains_any(normalized, scope_change_tokens) and self._contains_any(
            normalized,
            test_related_tokens,
        ):
            return ReportIntentDecision(
                intent=ReportUserIntent.REVISE_AND_RERUN,
                confidence=0.78,
                reason="Detected scope/test adjustment language likely requiring rerun.",
                rerun_instruction=raw,
            )

        return None

    def _detect_revise_report_text(
        self,
        raw: str,
        normalized: str,
    ) -> ReportIntentDecision | None:
        tokens = [
            "viet lai",
            "chinh report",
            "sua report",
            "doi format",
            "gon hon",
            "ngan hon",
            "ngan gon",
            "chi tiet hon",
            "chi tiet",
            "dai hon",
            "bullet",
            "gach dau dong",
            "de hieu hon",
            "trinh bay lai",
            "summary ngan",
            "ngon ngu tu nhien",
            "dien giai",
            "giai thich ro rang",
            "phan tich",
            "nhan xet",
            "rewrite report",
            "rewrite the report",
            "rephrase report",
            "natural language",
            "easy to understand",
            "explain the report",
            "make it clearer",
            "make it easier to understand",
        ]
        if self._contains_any(normalized, tokens):
            return ReportIntentDecision(
                intent=ReportUserIntent.REVISE_REPORT_TEXT,
                confidence=0.84,
                reason="Detected report rewriting/rephrasing/explanation intent.",
                revision_instruction=raw,
            )
        return None

    def _detect_question(
        self,
        raw: str,
        normalized: str,
    ) -> ReportIntentDecision | None:
        if "?" in raw:
            return ReportIntentDecision(
                intent=ReportUserIntent.ASK_REPORT_QUESTION,
                confidence=0.9,
                reason="Detected question mark in message.",
            )

        question_tokens = [
            "vi sao",
            "tai sao",
            "why",
            "how",
            "case nao",
            "fail o dau",
            "skip vi sao",
            "what happened",
            "what failed",
            "what is wrong",
        ]
        if self._contains_any(normalized, question_tokens):
            return ReportIntentDecision(
                intent=ReportUserIntent.ASK_REPORT_QUESTION,
                confidence=0.8,
                reason="Detected explanatory or analytical question language.",
            )

        return None

    def _safe_map_intent(self, raw_intent: str) -> ReportUserIntent:
        try:
            return ReportUserIntent(raw_intent)
        except Exception:
            return ReportUserIntent.ASK_REPORT_QUESTION

    def _coerce_confidence(self, value: Any) -> float:
        try:
            number = float(value)
        except Exception:
            return 0.5
        return max(0.0, min(1.0, number))

    def _coerce_optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _trim_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        keep_last: int,
    ) -> list[dict[str, Any]]:
        if len(messages) <= keep_last:
            return messages
        return messages[-keep_last:]

    def _truncate_text(
        self,
        text: str,
        *,
        limit: int,
    ) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + "\n...[truncated]"

    def _normalize(self, text: str) -> str:
        lowered = text.strip().lower()
        normalized = unicodedata.normalize("NFD", lowered)
        without_accents = "".join(
            ch for ch in normalized if unicodedata.category(ch) != "Mn"
        )
        without_accents = without_accents.replace("đ", "d").replace("Đ", "D")
        without_accents = re.sub(r"\s+", " ", without_accents)
        return without_accents.strip()

    def _contains_any(
        self,
        text: str,
        tokens: list[str],
    ) -> bool:
        return any(token in text for token in tokens)

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