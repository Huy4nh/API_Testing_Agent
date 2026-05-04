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
    - Add a small safety disambiguation layer so rewrite/explain/rerun requests
      are not misrouted into destructive actions.
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
            ai_decision = self._apply_safety_disambiguation(
                raw=cleaned,
                normalized=normalized,
                decision=ai_decision,
            )
            logger.info(
                f"AI-first detected intent={ai_decision.intent.value} "
                f"confidence={ai_decision.confidence:.2f}"
            )
            return ai_decision

        # 3) Heuristic fallback only if AI is absent / failed / too uncertain.
        heuristic_decision = self._detect_with_heuristics(cleaned, normalized)
        if heuristic_decision is not None:
            heuristic_decision = self._apply_safety_disambiguation(
                raw=cleaned,
                normalized=normalized,
                decision=heuristic_decision,
            )
            logger.info(
                f"Heuristic fallback detected intent={heuristic_decision.intent.value}"
            )
            return heuristic_decision

        # 4) External fallback if configured.
        if self._fallback_resolver is not None:
            try:
                resolved = self._fallback_resolver(cleaned, dict(state or {}))
                if resolved is not None:
                    resolved = self._apply_safety_disambiguation(
                        raw=cleaned,
                        normalized=normalized,
                        decision=resolved,
                    )
                    logger.info(
                        f"Fallback resolver returned intent={resolved.intent.value}"
                    )
                    return resolved
            except Exception as exc:
                logger.warning(f"Fallback resolver failed: {exc}")

        # 5) Final safe default.
        if self._is_strong_rewrite_signal(normalized):
            decision = ReportIntentDecision(
                intent=ReportUserIntent.REVISE_REPORT_TEXT,
                confidence=0.78,
                reason="Strong rewrite/explanation markers detected in final fallback.",
                revision_instruction=cleaned,
            )
            logger.info(f"Detected intent={decision.intent.value}")
            return decision

        if self._is_strong_rerun_signal(normalized):
            decision = ReportIntentDecision(
                intent=ReportUserIntent.REVISE_AND_RERUN,
                confidence=0.76,
                reason="Strong rerun/scope-adjustment markers detected in final fallback.",
                rerun_instruction=cleaned,
            )
            logger.info(f"Detected intent={decision.intent.value}")
            return decision

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

    def _apply_safety_disambiguation(
        self,
        *,
        raw: str,
        normalized: str,
        decision: ReportIntentDecision,
    ) -> ReportIntentDecision:
        """
        Safety layer:
        - If the message strongly looks like rewrite/explain/summarize, never let it
          collapse into cancel/finalize/question.
        - If the message strongly looks like rerun/scope-adjust, never let it collapse
          into cancel/finalize/question.
        """
        if self._is_strong_rewrite_signal(normalized):
            if decision.intent in {
                ReportUserIntent.CANCEL_REPORT,
                ReportUserIntent.FINALIZE_REPORT,
                ReportUserIntent.ASK_REPORT_QUESTION,
                ReportUserIntent.UNKNOWN,
            }:
                return ReportIntentDecision(
                    intent=ReportUserIntent.REVISE_REPORT_TEXT,
                    confidence=max(decision.confidence, 0.82),
                    reason=(
                        "Safety disambiguation: the message strongly indicates "
                        "rewrite/explanation rather than a destructive action."
                    ),
                    revision_instruction=decision.revision_instruction or raw,
                )

        if self._is_strong_rerun_signal(normalized):
            if decision.intent in {
                ReportUserIntent.CANCEL_REPORT,
                ReportUserIntent.FINALIZE_REPORT,
                ReportUserIntent.ASK_REPORT_QUESTION,
                ReportUserIntent.UNKNOWN,
            }:
                return ReportIntentDecision(
                    intent=ReportUserIntent.REVISE_AND_RERUN,
                    confidence=max(decision.confidence, 0.80),
                    reason=(
                        "Safety disambiguation: the message strongly indicates "
                        "rerun/scope adjustment rather than a destructive action."
                    ),
                    rerun_instruction=decision.rerun_instruction or raw,
                )

        return decision

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
        if self._is_strong_rewrite_signal(normalized):
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

    def _is_strong_rewrite_signal(
        self,
        normalized: str,
    ) -> bool:
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
            "de hieu",
            "trinh bay lai",
            "summary ngan",
            "ngon ngu tu nhien",
            "tieng viet",
            "chuyen report",
            "chuyen bao cao",
            "dien giai",
            "dien giai ro",
            "giai thich",
            "giai thich ro rang",
            "phan tich",
            "nhan xet",
            "binh luan",
            "bien giai",
            "viet de hieu",
            "viet lai cho de hieu",
            "rewrite report",
            "rewrite the report",
            "rephrase report",
            "natural language",
            "easy to understand",
            "explain the report",
            "make it clearer",
            "make it easier to understand",
            "rewrite this report",
            "rewrite this in vietnamese",
        ]
        return self._contains_any(normalized, tokens)

    def _is_strong_rerun_signal(
        self,
        normalized: str,
    ) -> bool:
        rerun_tokens = [
            "chay lai",
            "rerun",
            "re-run",
            "retest",
            "test lai",
            "run lai",
        ]
        scope_tokens = [
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
        test_tokens = [
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
            "/img",
            "/post",
        ]

        if self._contains_any(normalized, rerun_tokens):
            return True

        if self._contains_any(normalized, scope_tokens) and self._contains_any(
            normalized,
            test_tokens,
        ):
            return True

        return False

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