from __future__ import annotations

from typing import Literal, cast

from langgraph.graph import END, START, StateGraph

from api_testing_agent.logging_config import get_logger
from api_testing_agent.tasks.ai_intent_agent import AIIntentAgent
from api_testing_agent.tasks.ai_router_models import AIIntentClassification, HybridRouterState
from api_testing_agent.tasks.conversation_router import ConversationRouter
from api_testing_agent.tasks.workflow_models import (
    RouterDecision,
    RouterIntent,
    WorkflowContextSnapshot,
    WorkflowPhase,
)


class HybridConversationRouter:
    def __init__(
        self,
        *,
        deterministic_router: ConversationRouter | None = None,
        ai_intent_agent: AIIntentAgent | None = None,
        model_name: str | None = None,
        model_provider: str | None = None,
    ) -> None:
        self._logger = get_logger(__name__)
        self._deterministic_router = deterministic_router or ConversationRouter()
        self._ai_intent_agent = ai_intent_agent

        if self._ai_intent_agent is None and model_name:
            self._ai_intent_agent = AIIntentAgent(
                model_name=model_name,
                model_provider=model_provider,
            )

        self._graph = self._build_graph()

        self._logger.info(
            "Initialized HybridConversationRouter.",
            extra={"payload_source": "hybrid_router_init"},
        )

    def _is_explicit_meta_command(self, message: str) -> bool:
        cleaned = " ".join(message.strip().lower().split())

        explicit_help_commands = {
            "help",
            "trợ giúp",
            "tro giup",
            "hướng dẫn",
            "huong dan",
        }
        explicit_status_commands = {
            "status",
            "trạng thái",
            "trang thai",
            "phase",
        }

        return cleaned in explicit_help_commands or cleaned in explicit_status_commands

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

    def route(
        self,
        *,
        message: str,
        snapshot: WorkflowContextSnapshot | None,
    ) -> RouterDecision:
        if self._ai_intent_agent is None or not self._ai_intent_agent.is_enabled:
            return self._deterministic_router.route(message=message, snapshot=snapshot)

        state: HybridRouterState = {
            "message": message,
            "snapshot": snapshot,
        }

        result = cast(HybridRouterState, self._graph.invoke(state))
        final_decision = result.get("final_decision")

        if final_decision is None:
            return self._deterministic_router.route(message=message, snapshot=snapshot)

        return final_decision

    def _build_graph(self):
        builder = StateGraph(HybridRouterState)

        builder.add_node("hard_rule_gate", self._node_hard_rule_gate)
        builder.add_node("ai_classify", self._node_ai_classify)
        builder.add_node("phase_policy", self._node_phase_policy)
        builder.add_node("finalize_from_rule", self._node_finalize_from_rule)

        builder.add_edge(START, "hard_rule_gate")
        builder.add_conditional_edges(
            "hard_rule_gate",
            self._route_after_hard_rule_gate,
            {
                "finalize_from_rule": "finalize_from_rule",
                "ai_classify": "ai_classify",
            },
        )
        builder.add_edge("finalize_from_rule", END)
        builder.add_edge("ai_classify", "phase_policy")
        builder.add_edge("phase_policy", END)

        return builder.compile()

    def _node_hard_rule_gate(
        self,
        state: HybridRouterState,
    ) -> dict[str, RouterDecision]:
        decision = self._deterministic_router.route(
            message=state["message"],
            snapshot=state["snapshot"],
        )
        return {"deterministic_decision": decision}

    def _route_after_hard_rule_gate(
        self,
        state: HybridRouterState,
    ) -> Literal["finalize_from_rule", "ai_classify"]:
        decision = state.get("deterministic_decision")
        snapshot = state["snapshot"]
        message = state["message"]

        if decision is None:
            return "ai_classify"

        if not self._should_use_ai(
            decision=decision,
            snapshot=snapshot,
            message=message,
        ):
            return "finalize_from_rule"

        return "ai_classify"

    def _node_finalize_from_rule(
        self,
        state: HybridRouterState,
    ) -> dict[str, RouterDecision]:
        decision = state.get("deterministic_decision")

        if decision is None:
            fallback = self._deterministic_router.route(
                message=state["message"],
                snapshot=state["snapshot"],
            )
            return {"final_decision": fallback}

        return {"final_decision": decision}

    def _node_ai_classify(
        self,
        state: HybridRouterState,
    ) -> dict[str, AIIntentClassification | None]:
        if self._ai_intent_agent is None:
            return {"llm_classification": None}

        classification = self._ai_intent_agent.classify(
            message=state["message"],
            snapshot=state["snapshot"],
        )
        return {"llm_classification": classification}

    def _node_phase_policy(
        self,
        state: HybridRouterState,
    ) -> dict[str, RouterDecision]:
        deterministic = state.get("deterministic_decision")
        if deterministic is None:
            deterministic = self._deterministic_router.route(
                message=state["message"],
                snapshot=state["snapshot"],
            )

        snapshot = state["snapshot"]
        classification = state.get("llm_classification")

        if classification is None:
            return {"final_decision": deterministic}

        final_decision = self._apply_phase_policy(
            classification=classification,
            deterministic=deterministic,
            snapshot=snapshot,
        )
        return {"final_decision": final_decision}

    def _should_use_ai(
        self,
        *,
        decision: RouterDecision,
        snapshot: WorkflowContextSnapshot | None,
        message: str,
    ) -> bool:
        cleaned = message.strip()

        if snapshot is None:
            return False

        if snapshot.phase not in {
            WorkflowPhase.PENDING_SCOPE_CONFIRMATION,
            WorkflowPhase.PENDING_REVIEW,
            WorkflowPhase.REPORT_INTERACTION,
            WorkflowPhase.FINAL_REPORT_STAGED,
            WorkflowPhase.RERUN_REQUESTED,
        }:
            return False

        if not cleaned or cleaned.isdigit():
            return False

        if decision.intent == RouterIntent.RESUME_TARGET_SELECTION:
            return False

        if decision.intent == RouterIntent.START_NEW_WORKFLOW:
            return False

        if decision.intent in {RouterIntent.HELP, RouterIntent.STATUS}:
            return not self._is_explicit_meta_command(message)

        if snapshot.phase == WorkflowPhase.PENDING_SCOPE_CONFIRMATION:
            if decision.intent in {
                RouterIntent.SHOW_SCOPE_CATALOG,
                RouterIntent.SHOW_SCOPE_GROUP_DETAILS,
                RouterIntent.SHOW_SCOPE_OPERATION_DETAILS,
                RouterIntent.ASK_SCOPE_RECOMMENDATION,
            }:
                return False

            return decision.intent in {
                RouterIntent.RESUME_SCOPE_CONFIRMATION,
                RouterIntent.CLARIFY,
                RouterIntent.HELP,
                RouterIntent.STATUS,
            }

        if decision.intent == RouterIntent.CLARIFY:
            return False

        if decision.intent == RouterIntent.SHOW_REVIEW_SCOPE:
            return False

        return decision.intent in {
            RouterIntent.RESUME_REVIEW,
            RouterIntent.CONTINUE_REPORT_INTERACTION,
            RouterIntent.HELP,
            RouterIntent.STATUS,
        }

    def _apply_phase_policy(
        self,
        *,
        classification: AIIntentClassification,
        deterministic: RouterDecision,
        snapshot: WorkflowContextSnapshot | None,
    ) -> RouterDecision:
        lang = snapshot.preferred_language if snapshot is not None else "vi"
        phase = snapshot.phase if snapshot is not None else None
        confidence = max(0.0, min(1.0, float(classification.confidence)))
        reason = (
            f"ai_intent={classification.intent}; "
            f"confidence={confidence:.2f}; "
            f"rationale={classification.rationale}; "
            f"followup_reference={classification.followup_reference}; "
            f"scope_followup_kind={classification.scope_followup_kind}"
        )

        if confidence < 0.60:
            return deterministic

        if classification.intent == "help":
            return RouterDecision(
                intent=RouterIntent.HELP,
                confidence=confidence,
                reason=reason,
                normalized_message=deterministic.normalized_message,
            )

        if classification.intent == "status":
            return RouterDecision(
                intent=RouterIntent.STATUS,
                confidence=confidence,
                reason=reason,
                normalized_message=deterministic.normalized_message,
            )

        if phase == WorkflowPhase.PENDING_SCOPE_CONFIRMATION:
            if classification.intent == "show_scope_catalog":
                return RouterDecision(
                    intent=RouterIntent.SHOW_SCOPE_CATALOG,
                    confidence=confidence,
                    reason=reason,
                    normalized_message=deterministic.normalized_message,
                )

            if classification.intent == "show_scope_group_details":
                return RouterDecision(
                    intent=RouterIntent.SHOW_SCOPE_GROUP_DETAILS,
                    confidence=confidence,
                    reason=reason,
                    normalized_message=deterministic.normalized_message,
                    metadata={"group_selector": deterministic.normalized_message},
                )

            if classification.intent == "show_scope_operation_details":
                return RouterDecision(
                    intent=RouterIntent.SHOW_SCOPE_OPERATION_DETAILS,
                    confidence=confidence,
                    reason=reason,
                    normalized_message=deterministic.normalized_message,
                    metadata={"operation_selector": deterministic.normalized_message},
                )

            if classification.intent == "ask_scope_recommendation":
                return RouterDecision(
                    intent=RouterIntent.ASK_SCOPE_RECOMMENDATION,
                    confidence=confidence,
                    reason=reason,
                    normalized_message=deterministic.normalized_message,
                )

            if classification.intent == "apply_scope_recommendation":
                if self._has_latest_scope_recommendation(snapshot):
                    return RouterDecision(
                        intent=RouterIntent.APPLY_SCOPE_RECOMMENDATION,
                        confidence=confidence,
                        reason=reason,
                        normalized_message=deterministic.normalized_message,
                        metadata={
                            "followup_reference": classification.followup_reference,
                            "scope_followup_kind": classification.scope_followup_kind,
                        },
                    )

                return RouterDecision(
                    intent=RouterIntent.CLARIFY,
                    confidence=confidence,
                    reason=reason,
                    normalized_message=deterministic.normalized_message,
                    clarification_question=self._localize(
                        lang,
                        "Tôi chưa thấy gợi ý scope nào gần đây để áp dụng. Bạn muốn tôi gợi ý lại nhóm nên test trước không?",
                        "I do not see a recent scope recommendation to apply. Would you like me to suggest which groups should be tested first again?",
                    ),
                )

            if classification.intent == "resume_scope_confirmation":
                if (
                    classification.followup_reference == "latest_scope_recommendation"
                    and classification.scope_followup_kind == "accept_recommendation"
                    and self._has_latest_scope_recommendation(snapshot)
                ):
                    return RouterDecision(
                        intent=RouterIntent.APPLY_SCOPE_RECOMMENDATION,
                        confidence=confidence,
                        reason=reason,
                        normalized_message=deterministic.normalized_message,
                        metadata={
                            "followup_reference": classification.followup_reference,
                            "scope_followup_kind": classification.scope_followup_kind,
                        },
                    )

                return RouterDecision(
                    intent=RouterIntent.RESUME_SCOPE_CONFIRMATION,
                    confidence=confidence,
                    reason=reason,
                    normalized_message=deterministic.normalized_message,
                )

            if classification.intent == "start_new_workflow":
                return RouterDecision(
                    intent=RouterIntent.CLARIFY,
                    confidence=confidence,
                    reason=reason,
                    normalized_message=deterministic.normalized_message,
                    clarification_question=self._localize(
                        lang,
                        "Bạn đang ở bước xác nhận phạm vi test. Bạn muốn tiếp tục chọn scope hiện tại, hay mở workflow test mới?",
                        "You are currently confirming the test scope. Do you want to continue refining this scope, or start a new test workflow?",
                    ),
                )

        if phase == WorkflowPhase.PENDING_REVIEW:
            if classification.intent == "show_review_scope":
                return RouterDecision(
                    intent=RouterIntent.SHOW_REVIEW_SCOPE,
                    confidence=confidence,
                    reason=reason,
                    normalized_message=deterministic.normalized_message,
                )

            if classification.intent == "resume_review":
                return RouterDecision(
                    intent=RouterIntent.RESUME_REVIEW,
                    confidence=confidence,
                    reason=reason,
                    normalized_message=deterministic.normalized_message,
                )

            if classification.intent == "start_new_workflow":
                return RouterDecision(
                    intent=RouterIntent.CLARIFY,
                    confidence=confidence,
                    reason=reason,
                    normalized_message=deterministic.normalized_message,
                    clarification_question=self._localize(
                        lang,
                        "Bạn đang ở bước review testcase draft. Bạn muốn tiếp tục chỉnh draft hiện tại, hay mở workflow test mới?",
                        "You are currently reviewing the testcase draft. Do you want to continue revising this draft, or start a new test workflow?",
                    ),
                )

        if phase in {
            WorkflowPhase.REPORT_INTERACTION,
            WorkflowPhase.FINAL_REPORT_STAGED,
            WorkflowPhase.RERUN_REQUESTED,
        }:
            if classification.intent == "continue_report_interaction":
                return RouterDecision(
                    intent=RouterIntent.CONTINUE_REPORT_INTERACTION,
                    confidence=confidence,
                    reason=reason,
                    normalized_message=deterministic.normalized_message,
                )

            if classification.intent == "start_new_workflow":
                return RouterDecision(
                    intent=RouterIntent.CLARIFY,
                    confidence=confidence,
                    reason=reason,
                    normalized_message=deterministic.normalized_message,
                    clarification_question=self._localize(
                        lang,
                        "Bạn đang ở phiên tương tác với final report hiện tại. Bạn muốn tiếp tục report này, hay mở workflow test mới?",
                        "You are currently in the final report interaction session. Do you want to continue with this report, or start a new test workflow?",
                    ),
                )

        if classification.intent == "clarify":
            return RouterDecision(
                intent=RouterIntent.CLARIFY,
                confidence=confidence,
                reason=reason,
                normalized_message=deterministic.normalized_message,
                clarification_question=classification.clarification_question
                or self._localize(
                    lang,
                    "Tôi chưa chắc bạn muốn làm gì tiếp theo. Bạn có thể diễn đạt lại rõ hơn không?",
                    "I am not fully sure what you want to do next. Could you rephrase it more clearly?",
                ),
            )

        return deterministic

    def _localize(
        self,
        preferred_language: str,
        vi_text: str,
        en_text: str,
    ) -> str:
        return en_text if preferred_language == "en" else vi_text