from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from typing_extensions import NotRequired, TypedDict

from api_testing_agent.logging_config import bind_logger, get_logger
from api_testing_agent.tasks.language_support import SupportedLanguage
from api_testing_agent.tasks.workflow_models import (
    ScopeRecommendationMode,
    ScopeSelectionMode,
    WorkflowScopeCatalogGroup,
    WorkflowScopeCatalogOperation,
    WorkflowScopeRecommendation,
)

ScopeConversationMode = Literal["gate", "selection", "recommendation", "apply_recommendation"]
ScopeConversationAction = Literal[
    "require_scope_confirmation",
    "direct_to_review",
    "select_scope",
    "recommend_scope",
    "clarify",
]


@dataclass(frozen=True)
class ScopeConversationDecision:
    action: ScopeConversationAction
    reason: str
    source: str = "system"

    follow_up_question: str | None = None
    rationale: str | None = None

    scope_selection_mode: ScopeSelectionMode | None = None
    selected_group_ids: list[str] = field(default_factory=list)
    selected_operation_ids: list[str] = field(default_factory=list)
    excluded_group_ids: list[str] = field(default_factory=list)
    excluded_operation_ids: list[str] = field(default_factory=list)

    recommendation: WorkflowScopeRecommendation = field(
        default_factory=WorkflowScopeRecommendation
    )
    max_test_cases: int | None = None


class _AIGatePayload(BaseModel):
    action: Literal["require_scope_confirmation", "direct_to_review"] = Field(
        description="Whether the workflow should require scope confirmation or can go directly to review."
    )
    reason: str = Field(default="", description="Short explanation for the decision.")
    follow_up_question: str | None = Field(
        default=None,
        description="Question to ask the user if scope confirmation is required.",
    )
    rationale: str | None = Field(
        default=None,
        description="Extra reasoning grounded in the request and catalog.",
    )


class _AISelectionPayload(BaseModel):
    action: Literal["select_scope", "clarify"] = Field(
        description="Whether the user provided enough scope information to select scope, or if clarification is still needed."
    )
    scope_selection_mode: Literal["all", "groups", "operations", "custom", "none"] = Field(
        default="none",
        description="How the user's scope choice should be interpreted.",
    )
    selected_group_ids: list[str] = Field(default_factory=list)
    selected_operation_ids: list[str] = Field(default_factory=list)
    excluded_group_ids: list[str] = Field(default_factory=list)
    excluded_operation_ids: list[str] = Field(default_factory=list)
    reason: str = Field(default="")
    follow_up_question: str | None = Field(default=None)
    max_test_cases: int | None = Field(
        default=None,
        description="Small testcase budget if the user explicitly constrained it.",
    )


class _AIRecommendationPayload(BaseModel):
    recommendation_mode: Literal["prioritize", "deprioritize"] = Field(
        description="Whether to recommend what should be tested first or what should not be tested first."
    )
    group_ids: list[str] = Field(
        default_factory=list,
        description="Ordered list of recommended or deprioritized group_ids. Only use valid ids from the catalog.",
    )
    operation_ids: list[str] = Field(
        default_factory=list,
        description="Optional operation ids if recommendation is more specific than group level.",
    )
    rationale: str = Field(default="")
    follow_up_question: str | None = Field(default=None)
    max_test_cases: int | None = Field(
        default=None,
        description="Budget hint if the user asked for a small number of testcases.",
    )


class _ScopeConversationState(TypedDict):
    mode: ScopeConversationMode
    original_request: str
    user_message: str
    selected_target: str
    preferred_language: SupportedLanguage
    scope_catalog_groups: list[WorkflowScopeCatalogGroup]
    scope_catalog_operations: list[WorkflowScopeCatalogOperation]

    latest_recommendation: NotRequired[WorkflowScopeRecommendation | None]
    understanding_explanation: NotRequired[str | None]
    canonical_command: NotRequired[str | None]
    narrowed_scope_group_ids: NotRequired[list[str]]
    narrowed_scope_operation_ids: NotRequired[list[str]]
    scope_confirmation_history: NotRequired[list[str]]

    final_result: NotRequired[ScopeConversationDecision]


class ScopeConversationAgent:
    def __init__(
        self,
        *,
        model_name: str,
        model_provider: str | None = None,
    ) -> None:
        self._logger = get_logger(__name__)
        self._model_name = model_name.strip()
        self._model_provider = (model_provider or "").strip() or None

        self._gate_model: Any | None = None
        self._selection_model: Any | None = None
        self._recommendation_model: Any | None = None
        self._enabled = False

        try:
            base_model = init_chat_model(
                model=self._model_name,
                model_provider=self._model_provider,
                temperature=0,
            )
            self._gate_model = base_model.with_structured_output(_AIGatePayload)
            self._selection_model = base_model.with_structured_output(_AISelectionPayload)
            self._recommendation_model = base_model.with_structured_output(
                _AIRecommendationPayload
            )
            self._enabled = True
            self._logger.info(
                "Initialized ScopeConversationAgent.",
                extra={"payload_source": "scope_conversation_agent_init"},
            )
        except Exception as exc:
            self._logger.warning(
                f"ScopeConversationAgent disabled and will fall back to heuristics: {exc}",
                extra={"payload_source": "scope_conversation_agent_init_failed"},
            )
            self._gate_model = None
            self._selection_model = None
            self._recommendation_model = None
            self._enabled = False

        self._graph = self._build_graph()

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def should_require_scope_confirmation(
        self,
        *,
        original_request: str,
        selected_target: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        understanding_explanation: str | None = None,
        canonical_command: str | None = None,
        narrowed_scope_group_ids: list[str] | None = None,
        narrowed_scope_operation_ids: list[str] | None = None,
    ) -> ScopeConversationDecision:
        state: _ScopeConversationState = {
            "mode": "gate",
            "original_request": original_request,
            "user_message": original_request,
            "selected_target": selected_target,
            "preferred_language": preferred_language,
            "scope_catalog_groups": list(scope_catalog_groups),
            "scope_catalog_operations": list(scope_catalog_operations),
            "understanding_explanation": understanding_explanation,
            "canonical_command": canonical_command,
            "narrowed_scope_group_ids": list(narrowed_scope_group_ids or []),
            "narrowed_scope_operation_ids": list(narrowed_scope_operation_ids or []),
            "scope_confirmation_history": [],
            "latest_recommendation": None,
        }
        result = cast(_ScopeConversationState, self._graph.invoke(state))
        final_result = result.get("final_result")
        if final_result is None:
            return self._fallback_gate(
                original_request=original_request,
                selected_target=selected_target,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
                understanding_explanation=understanding_explanation,
                canonical_command=canonical_command,
                narrowed_scope_group_ids=list(narrowed_scope_group_ids or []),
                narrowed_scope_operation_ids=list(narrowed_scope_operation_ids or []),
            )
        return final_result

    def interpret_scope_selection(
        self,
        *,
        original_request: str,
        user_message: str,
        selected_target: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        latest_recommendation: WorkflowScopeRecommendation | None = None,
        scope_confirmation_history: list[str] | None = None,
    ) -> ScopeConversationDecision:
        latest = latest_recommendation or WorkflowScopeRecommendation()

        accept_reco = self._try_accept_latest_recommendation(
            user_message=user_message,
            preferred_language=preferred_language,
            scope_catalog_groups=scope_catalog_groups,
            scope_catalog_operations=scope_catalog_operations,
            latest_recommendation=latest,
        )
        if accept_reco is not None:
            return accept_reco

        state: _ScopeConversationState = {
            "mode": "selection",
            "original_request": original_request,
            "user_message": user_message,
            "selected_target": selected_target,
            "preferred_language": preferred_language,
            "scope_catalog_groups": list(scope_catalog_groups),
            "scope_catalog_operations": list(scope_catalog_operations),
            "scope_confirmation_history": list(scope_confirmation_history or []),
            "latest_recommendation": latest,
        }
        result = cast(_ScopeConversationState, self._graph.invoke(state))
        final_result = result.get("final_result")
        if final_result is None:
            return self._fallback_selection(
                user_message=user_message,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
            )
        return final_result

    def recommend_scope(
        self,
        *,
        original_request: str,
        user_message: str,
        selected_target: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        scope_confirmation_history: list[str] | None = None,
    ) -> ScopeConversationDecision:
        state: _ScopeConversationState = {
            "mode": "recommendation",
            "original_request": original_request,
            "user_message": user_message,
            "selected_target": selected_target,
            "preferred_language": preferred_language,
            "scope_catalog_groups": list(scope_catalog_groups),
            "scope_catalog_operations": list(scope_catalog_operations),
            "scope_confirmation_history": list(scope_confirmation_history or []),
            "latest_recommendation": None,
        }
        result = cast(_ScopeConversationState, self._graph.invoke(state))
        final_result = result.get("final_result")
        if final_result is None:
            return self._fallback_recommendation(
                user_message=user_message,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
            )
        return final_result

    def apply_recommendation(
        self,
        *,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        latest_recommendation: WorkflowScopeRecommendation | None,
        user_message: str | None = None,
    ) -> ScopeConversationDecision:
        recommendation = latest_recommendation or WorkflowScopeRecommendation()
        if not recommendation.has_payload():
            return ScopeConversationDecision(
                action="clarify",
                reason=self._localize(
                    preferred_language,
                    "Tôi chưa có gợi ý scope gần đây để áp dụng.",
                    "I do not have a recent scope recommendation to apply.",
                ),
                follow_up_question=self._localize(
                    preferred_language,
                    "Bạn muốn tôi gợi ý lại nhóm nên test trước không?",
                    "Would you like me to suggest which groups should be tested first again?",
                ),
                source="system",
            )

        return self._apply_recommendation_to_selection(
            preferred_language=preferred_language,
            scope_catalog_groups=scope_catalog_groups,
            scope_catalog_operations=scope_catalog_operations,
            recommendation=recommendation,
            user_message=user_message or "",
            source="recommendation_apply",
        )

    def _build_graph(self):
        builder = StateGraph(_ScopeConversationState)

        builder.add_node("gate", self._node_gate)
        builder.add_node("selection", self._node_selection)
        builder.add_node("recommendation", self._node_recommendation)
        builder.add_node("apply_recommendation", self._node_apply_recommendation)

        builder.add_conditional_edges(
            START,
            self._route_start,
            {
                "gate": "gate",
                "selection": "selection",
                "recommendation": "recommendation",
                "apply_recommendation": "apply_recommendation",
            },
        )

        builder.add_edge("gate", END)
        builder.add_edge("selection", END)
        builder.add_edge("recommendation", END)
        builder.add_edge("apply_recommendation", END)

        return builder.compile()

    def _route_start(
        self,
        state: _ScopeConversationState,
    ) -> ScopeConversationMode:
        return state["mode"]

    def _node_gate(
        self,
        state: _ScopeConversationState,
    ) -> dict[str, ScopeConversationDecision]:
        return {
            "final_result": self._ai_or_fallback_gate(
                original_request=state["original_request"],
                selected_target=state["selected_target"],
                preferred_language=state["preferred_language"],
                scope_catalog_groups=state["scope_catalog_groups"],
                scope_catalog_operations=state["scope_catalog_operations"],
                understanding_explanation=state.get("understanding_explanation"),
                canonical_command=state.get("canonical_command"),
                narrowed_scope_group_ids=list(state.get("narrowed_scope_group_ids", [])),
                narrowed_scope_operation_ids=list(
                    state.get("narrowed_scope_operation_ids", [])
                ),
            )
        }

    def _node_selection(
        self,
        state: _ScopeConversationState,
    ) -> dict[str, ScopeConversationDecision]:
        return {
            "final_result": self._ai_or_fallback_selection(
                original_request=state["original_request"],
                user_message=state["user_message"],
                selected_target=state["selected_target"],
                preferred_language=state["preferred_language"],
                scope_catalog_groups=state["scope_catalog_groups"],
                scope_catalog_operations=state["scope_catalog_operations"],
                latest_recommendation=state.get("latest_recommendation"),
                scope_confirmation_history=list(
                    state.get("scope_confirmation_history", [])
                ),
            )
        }

    def _node_recommendation(
        self,
        state: _ScopeConversationState,
    ) -> dict[str, ScopeConversationDecision]:
        return {
            "final_result": self._ai_or_fallback_recommendation(
                original_request=state["original_request"],
                user_message=state["user_message"],
                selected_target=state["selected_target"],
                preferred_language=state["preferred_language"],
                scope_catalog_groups=state["scope_catalog_groups"],
                scope_catalog_operations=state["scope_catalog_operations"],
                scope_confirmation_history=list(
                    state.get("scope_confirmation_history", [])
                ),
            )
        }

    def _node_apply_recommendation(
        self,
        state: _ScopeConversationState,
    ) -> dict[str, ScopeConversationDecision]:
        return {
            "final_result": self.apply_recommendation(
                preferred_language=state["preferred_language"],
                scope_catalog_groups=state["scope_catalog_groups"],
                scope_catalog_operations=state["scope_catalog_operations"],
                latest_recommendation=state.get("latest_recommendation"),
                user_message=state["user_message"],
            )
        }

    def _ai_or_fallback_gate(
        self,
        *,
        original_request: str,
        selected_target: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        understanding_explanation: str | None,
        canonical_command: str | None,
        narrowed_scope_group_ids: list[str],
        narrowed_scope_operation_ids: list[str],
    ) -> ScopeConversationDecision:
        logger = bind_logger(
            self._logger,
            target_name=selected_target,
            payload_source="scope_conversation_agent_gate",
        )
        logger.info("Running scope gate decision.")

        model = self._gate_model
        if not self._enabled or model is None:
            return self._fallback_gate(
                original_request=original_request,
                selected_target=selected_target,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
                understanding_explanation=understanding_explanation,
                canonical_command=canonical_command,
                narrowed_scope_group_ids=narrowed_scope_group_ids,
                narrowed_scope_operation_ids=narrowed_scope_operation_ids,
            )

        try:
            payload = cast(
                _AIGatePayload,
                model.invoke(
                    [
                        SystemMessage(
                            content=self._build_gate_system_prompt(
                                preferred_language=preferred_language
                            )
                        ),
                        HumanMessage(
                            content=self._build_gate_human_prompt(
                                original_request=original_request,
                                selected_target=selected_target,
                                scope_catalog_groups=scope_catalog_groups,
                                scope_catalog_operations=scope_catalog_operations,
                                understanding_explanation=understanding_explanation,
                                canonical_command=canonical_command,
                                narrowed_scope_group_ids=narrowed_scope_group_ids,
                                narrowed_scope_operation_ids=narrowed_scope_operation_ids,
                            )
                        ),
                    ]
                ),
            )

            return ScopeConversationDecision(
                action=payload.action,
                reason=payload.reason.strip() or self._localize(
                    preferred_language,
                    "Đã xác định quyết định gate cho scope confirmation.",
                    "Determined the gate decision for scope confirmation.",
                ),
                follow_up_question=payload.follow_up_question,
                rationale=payload.rationale,
                source="ai",
            )
        except Exception as exc:
            logger.warning(
                f"AI scope gate failed. Falling back to heuristics: {exc}",
                extra={"payload_source": "scope_conversation_agent_gate_failed"},
            )
            return self._fallback_gate(
                original_request=original_request,
                selected_target=selected_target,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
                understanding_explanation=understanding_explanation,
                canonical_command=canonical_command,
                narrowed_scope_group_ids=narrowed_scope_group_ids,
                narrowed_scope_operation_ids=narrowed_scope_operation_ids,
            )

    def _ai_or_fallback_selection(
        self,
        *,
        original_request: str,
        user_message: str,
        selected_target: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        latest_recommendation: WorkflowScopeRecommendation | None,
        scope_confirmation_history: list[str],
    ) -> ScopeConversationDecision:
        logger = bind_logger(
            self._logger,
            target_name=selected_target,
            payload_source="scope_conversation_agent_selection",
        )
        logger.info("Interpreting scope selection.")

        model = self._selection_model
        if not self._enabled or model is None:
            return self._fallback_selection(
                user_message=user_message,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
            )

        try:
            payload = cast(
                _AISelectionPayload,
                model.invoke(
                    [
                        SystemMessage(
                            content=self._build_selection_system_prompt(
                                preferred_language=preferred_language
                            )
                        ),
                        HumanMessage(
                            content=self._build_selection_human_prompt(
                                original_request=original_request,
                                user_message=user_message,
                                selected_target=selected_target,
                                scope_catalog_groups=scope_catalog_groups,
                                scope_catalog_operations=scope_catalog_operations,
                                latest_recommendation=latest_recommendation,
                                scope_confirmation_history=scope_confirmation_history,
                            )
                        ),
                    ]
                ),
            )

            if payload.action == "clarify":
                return ScopeConversationDecision(
                    action="clarify",
                    reason=payload.reason.strip() or self._localize(
                        preferred_language,
                        "Tôi cần bạn nói rõ hơn về phạm vi test mong muốn.",
                        "I need you to clarify the desired test scope.",
                    ),
                    follow_up_question=payload.follow_up_question
                    or self._default_scope_question(
                        preferred_language=preferred_language,
                        group_count=len(scope_catalog_groups),
                        operation_count=len(scope_catalog_operations),
                    ),
                    max_test_cases=payload.max_test_cases,
                    source="ai",
                )

            selected_group_ids = self._filter_valid_group_ids(
                payload.selected_group_ids,
                scope_catalog_groups,
            )
            selected_operation_ids = self._filter_valid_operation_ids(
                payload.selected_operation_ids,
                scope_catalog_operations,
            )
            excluded_group_ids = self._filter_valid_group_ids(
                payload.excluded_group_ids,
                scope_catalog_groups,
            )
            excluded_operation_ids = self._filter_valid_operation_ids(
                payload.excluded_operation_ids,
                scope_catalog_operations,
            )

            mode = self._coerce_scope_selection_mode(payload.scope_selection_mode)
            if mode == ScopeSelectionMode.GROUPS and selected_group_ids:
                selected_operation_ids = self._expand_group_ids_to_operation_ids(
                    group_ids=selected_group_ids,
                    scope_catalog_groups=scope_catalog_groups,
                )

            if mode == ScopeSelectionMode.ALL:
                selected_group_ids = [item.group_id for item in scope_catalog_groups]
                selected_operation_ids = [
                    item.operation_id for item in scope_catalog_operations
                ]

            if not selected_operation_ids and selected_group_ids:
                selected_operation_ids = self._expand_group_ids_to_operation_ids(
                    group_ids=selected_group_ids,
                    scope_catalog_groups=scope_catalog_groups,
                )

            if excluded_group_ids and not excluded_operation_ids:
                excluded_operation_ids = self._expand_group_ids_to_operation_ids(
                    group_ids=excluded_group_ids,
                    scope_catalog_groups=scope_catalog_groups,
                )

            if excluded_operation_ids and selected_operation_ids:
                selected_operation_ids = [
                    item
                    for item in selected_operation_ids
                    if item not in set(excluded_operation_ids)
                ]

            if excluded_group_ids and selected_group_ids:
                selected_group_ids = [
                    item for item in selected_group_ids if item not in set(excluded_group_ids)
                ]

            if not selected_operation_ids:
                return self._fallback_selection(
                    user_message=user_message,
                    preferred_language=preferred_language,
                    scope_catalog_groups=scope_catalog_groups,
                    scope_catalog_operations=scope_catalog_operations,
                )

            return ScopeConversationDecision(
                action="select_scope",
                reason=payload.reason.strip() or self._localize(
                    preferred_language,
                    "Đã xác định được phạm vi test từ phản hồi của người dùng.",
                    "Resolved the test scope from the user's reply.",
                ),
                scope_selection_mode=mode or ScopeSelectionMode.CUSTOM,
                selected_group_ids=selected_group_ids,
                selected_operation_ids=selected_operation_ids,
                excluded_group_ids=excluded_group_ids,
                excluded_operation_ids=excluded_operation_ids,
                max_test_cases=payload.max_test_cases,
                source="ai",
            )
        except Exception as exc:
            logger.warning(
                f"AI scope selection failed. Falling back to heuristics: {exc}",
                extra={"payload_source": "scope_conversation_agent_selection_failed"},
            )
            return self._fallback_selection(
                user_message=user_message,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
            )

    def _ai_or_fallback_recommendation(
        self,
        *,
        original_request: str,
        user_message: str,
        selected_target: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        scope_confirmation_history: list[str],
    ) -> ScopeConversationDecision:
        logger = bind_logger(
            self._logger,
            target_name=selected_target,
            payload_source="scope_conversation_agent_recommendation",
        )
        logger.info("Generating scope recommendation.")

        model = self._recommendation_model
        if not self._enabled or model is None:
            return self._fallback_recommendation(
                user_message=user_message,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
            )

        try:
            payload = cast(
                _AIRecommendationPayload,
                model.invoke(
                    [
                        SystemMessage(
                            content=self._build_recommendation_system_prompt(
                                preferred_language=preferred_language
                            )
                        ),
                        HumanMessage(
                            content=self._build_recommendation_human_prompt(
                                original_request=original_request,
                                user_message=user_message,
                                selected_target=selected_target,
                                scope_catalog_groups=scope_catalog_groups,
                                scope_catalog_operations=scope_catalog_operations,
                                scope_confirmation_history=scope_confirmation_history,
                            )
                        ),
                    ]
                ),
            )

            group_ids = self._filter_valid_group_ids(
                payload.group_ids,
                scope_catalog_groups,
            )
            operation_ids = self._filter_valid_operation_ids(
                payload.operation_ids,
                scope_catalog_operations,
            )
            if not group_ids and not operation_ids:
                return self._fallback_recommendation(
                    user_message=user_message,
                    preferred_language=preferred_language,
                    scope_catalog_groups=scope_catalog_groups,
                    scope_catalog_operations=scope_catalog_operations,
                )

            reco_mode = self._coerce_recommendation_mode(payload.recommendation_mode)
            recommendation = WorkflowScopeRecommendation(
                mode=reco_mode,
                group_ids=group_ids,
                operation_ids=operation_ids,
                rationale=payload.rationale.strip() or None,
                follow_up_question=payload.follow_up_question,
                source_user_message=user_message,
                rendered_message=None,
            )
            return ScopeConversationDecision(
                action="recommend_scope",
                reason=self._localize(
                    preferred_language,
                    "Đã tạo gợi ý scope dựa trên yêu cầu hiện tại.",
                    "Generated a scope recommendation based on the current request.",
                ),
                recommendation=recommendation,
                rationale=payload.rationale.strip() or None,
                follow_up_question=payload.follow_up_question,
                max_test_cases=payload.max_test_cases,
                source="ai",
            )
        except Exception as exc:
            logger.warning(
                f"AI scope recommendation failed. Falling back to heuristics: {exc}",
                extra={"payload_source": "scope_conversation_agent_recommendation_failed"},
            )
            return self._fallback_recommendation(
                user_message=user_message,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
            )

    def _fallback_gate(
        self,
        *,
        original_request: str,
        selected_target: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        understanding_explanation: str | None,
        canonical_command: str | None,
        narrowed_scope_group_ids: list[str],
        narrowed_scope_operation_ids: list[str],
    ) -> ScopeConversationDecision:
        normalized_request = self._normalize(original_request)

        if self._has_explicit_endpoint_scope(original_request):
            return ScopeConversationDecision(
                action="direct_to_review",
                reason=self._localize(
                    preferred_language,
                    "Yêu cầu đã chỉ rõ endpoint hoặc HTTP method, có thể vào review trực tiếp.",
                    "The request already specifies an endpoint or HTTP method, so it can go directly to review.",
                ),
                source="heuristic",
            )

        if len(scope_catalog_operations) <= 1:
            return ScopeConversationDecision(
                action="direct_to_review",
                reason=self._localize(
                    preferred_language,
                    "Target thực tế chỉ có một operation trong phạm vi hiện tại.",
                    "The target effectively exposes a single operation in the current scope.",
                ),
                source="heuristic",
            )

        looks_broad = self._looks_like_general_target_request(
            normalized_request=normalized_request,
            selected_target=selected_target,
        )
        valid_narrowed_groups = self._filter_valid_group_ids(
            narrowed_scope_group_ids,
            scope_catalog_groups,
        )
        valid_narrowed_ops = self._filter_valid_operation_ids(
            narrowed_scope_operation_ids,
            scope_catalog_operations,
        )

        if looks_broad and self._request_target_operation_collision(
            original_request=original_request,
            selected_target=selected_target,
            scope_catalog_operations=scope_catalog_operations,
            narrowed_scope_operation_ids=valid_narrowed_ops,
        ):
            return ScopeConversationDecision(
                action="require_scope_confirmation",
                reason=self._localize(
                    preferred_language,
                    "Yêu cầu gốc còn mơ hồ và token đang bị trùng giữa tên target với operation/path, nên cần xác nhận scope trước.",
                    "The original request is still ambiguous and a token overlaps between the target name and operation/path, so scope should be confirmed first.",
                ),
                rationale=(
                    f"understanding={understanding_explanation or '-'}; "
                    f"canonical_command={canonical_command or '-'}"
                ),
                follow_up_question=self._default_scope_question(
                    preferred_language=preferred_language,
                    group_count=len(scope_catalog_groups),
                    operation_count=len(scope_catalog_operations),
                ),
                source="heuristic",
            )

        if looks_broad and valid_narrowed_ops and len(valid_narrowed_ops) < len(
            scope_catalog_operations
        ):
            return ScopeConversationDecision(
                action="require_scope_confirmation",
                reason=self._localize(
                    preferred_language,
                    "Yêu cầu gốc còn rộng, nhưng hệ thống đã thu hẹp phạm vi bằng suy luận. Cần hỏi lại người dùng trước khi tạo testcase.",
                    "The original request is still broad, but the scope has already been narrowed heuristically. The user should confirm the scope before testcase generation.",
                ),
                rationale=(
                    f"understanding={understanding_explanation or '-'}; "
                    f"canonical_command={canonical_command or '-'}"
                ),
                follow_up_question=self._default_scope_question(
                    preferred_language=preferred_language,
                    group_count=len(scope_catalog_groups),
                    operation_count=len(scope_catalog_operations),
                ),
                source="heuristic",
            )

        if looks_broad and valid_narrowed_groups and len(valid_narrowed_groups) < len(
            scope_catalog_groups
        ):
            return ScopeConversationDecision(
                action="require_scope_confirmation",
                reason=self._localize(
                    preferred_language,
                    "Yêu cầu gốc vẫn đang ở mức target tổng quát và cần xác nhận nhóm chức năng trước.",
                    "The original request is still target-level and the function groups should be confirmed first.",
                ),
                follow_up_question=self._default_scope_question(
                    preferred_language=preferred_language,
                    group_count=len(scope_catalog_groups),
                    operation_count=len(scope_catalog_operations),
                ),
                source="heuristic",
            )

        if looks_broad:
            return ScopeConversationDecision(
                action="require_scope_confirmation",
                reason=self._localize(
                    preferred_language,
                    f"Target `{selected_target}` có nhiều chức năng và yêu cầu hiện tại chưa đủ cụ thể.",
                    f"Target `{selected_target}` has multiple capabilities and the current request is not specific enough yet.",
                ),
                follow_up_question=self._default_scope_question(
                    preferred_language=preferred_language,
                    group_count=len(scope_catalog_groups),
                    operation_count=len(scope_catalog_operations),
                ),
                source="heuristic",
            )

        return ScopeConversationDecision(
            action="direct_to_review",
            reason=self._localize(
                preferred_language,
                "Yêu cầu có vẻ đã đủ cụ thể để vào review.",
                "The request appears specific enough to move to review.",
            ),
            source="heuristic",
        )

    def _fallback_selection(
        self,
        *,
        user_message: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
    ) -> ScopeConversationDecision:
        normalized = self._normalize(user_message)
        max_test_cases = self._extract_max_test_cases(user_message)

        if normalized in {"test het", "all", "toan bo"}:
            return ScopeConversationDecision(
                action="select_scope",
                reason=self._localize(
                    preferred_language,
                    "Người dùng đã chọn test toàn bộ scope.",
                    "The user selected the full scope.",
                ),
                scope_selection_mode=ScopeSelectionMode.ALL,
                selected_group_ids=[item.group_id for item in scope_catalog_groups],
                selected_operation_ids=[item.operation_id for item in scope_catalog_operations],
                max_test_cases=max_test_cases,
                source="heuristic",
            )

        if self._looks_like_exclusion_request(normalized):
            excluded_group_ids = self._resolve_group_ids_by_text(
                normalized_message=normalized,
                scope_catalog_groups=scope_catalog_groups,
            )
            excluded_operation_ids = self._resolve_operation_ids_by_text(
                normalized_message=normalized,
                scope_catalog_operations=scope_catalog_operations,
            )

            selected_group_ids = [
                item.group_id
                for item in scope_catalog_groups
                if item.group_id not in set(excluded_group_ids)
            ]
            selected_operation_ids = [
                item.operation_id
                for item in scope_catalog_operations
                if item.operation_id not in set(excluded_operation_ids)
            ]
            if excluded_group_ids:
                excluded_from_groups = self._expand_group_ids_to_operation_ids(
                    group_ids=excluded_group_ids,
                    scope_catalog_groups=scope_catalog_groups,
                )
                selected_operation_ids = [
                    item
                    for item in selected_operation_ids
                    if item not in set(excluded_from_groups)
                ]

            if selected_operation_ids:
                return ScopeConversationDecision(
                    action="select_scope",
                    reason=self._localize(
                        preferred_language,
                        "Đã loại trừ một phần scope theo yêu cầu của người dùng.",
                        "Excluded part of the scope as requested by the user.",
                    ),
                    scope_selection_mode=ScopeSelectionMode.CUSTOM,
                    selected_group_ids=selected_group_ids,
                    selected_operation_ids=selected_operation_ids,
                    excluded_group_ids=excluded_group_ids,
                    excluded_operation_ids=excluded_operation_ids,
                    max_test_cases=max_test_cases,
                    source="heuristic",
                )

        indexes = [int(item) for item in re.findall(r"\d+", normalized)]
        if indexes:
            expanded_indexes = self._expand_numeric_selection(indexes)
            group_ids: list[str] = []
            operation_ids: list[str] = []

            if "nhom" in normalized or "group" in normalized:
                for index in expanded_indexes:
                    if 1 <= index <= len(scope_catalog_groups):
                        group_ids.append(scope_catalog_groups[index - 1].group_id)
                if group_ids:
                    operation_ids = self._expand_group_ids_to_operation_ids(
                        group_ids=group_ids,
                        scope_catalog_groups=scope_catalog_groups,
                    )
                    return ScopeConversationDecision(
                        action="select_scope",
                        reason=self._localize(
                            preferred_language,
                            "Người dùng đã chọn nhóm theo chỉ số.",
                            "The user selected groups by index.",
                        ),
                        scope_selection_mode=ScopeSelectionMode.GROUPS,
                        selected_group_ids=group_ids,
                        selected_operation_ids=operation_ids,
                        max_test_cases=max_test_cases,
                        source="heuristic",
                    )

            for index in expanded_indexes:
                if 1 <= index <= len(scope_catalog_operations):
                    operation_ids.append(scope_catalog_operations[index - 1].operation_id)

            if operation_ids:
                return ScopeConversationDecision(
                    action="select_scope",
                    reason=self._localize(
                        preferred_language,
                        "Người dùng đã chọn operation theo chỉ số.",
                        "The user selected operations by index.",
                    ),
                    scope_selection_mode=ScopeSelectionMode.OPERATIONS,
                    selected_operation_ids=operation_ids,
                    max_test_cases=max_test_cases,
                    source="heuristic",
                )

        group_ids = self._resolve_group_ids_by_text(
            normalized_message=normalized,
            scope_catalog_groups=scope_catalog_groups,
        )
        if group_ids:
            return ScopeConversationDecision(
                action="select_scope",
                reason=self._localize(
                    preferred_language,
                    "Người dùng đã chọn nhóm chức năng cụ thể.",
                    "The user selected specific function groups.",
                ),
                scope_selection_mode=ScopeSelectionMode.GROUPS,
                selected_group_ids=group_ids,
                selected_operation_ids=self._expand_group_ids_to_operation_ids(
                    group_ids=group_ids,
                    scope_catalog_groups=scope_catalog_groups,
                ),
                max_test_cases=max_test_cases,
                source="heuristic",
            )

        operation_ids = self._resolve_operation_ids_by_text(
            normalized_message=normalized,
            scope_catalog_operations=scope_catalog_operations,
        )
        if operation_ids:
            return ScopeConversationDecision(
                action="select_scope",
                reason=self._localize(
                    preferred_language,
                    "Người dùng đã chọn operation cụ thể.",
                    "The user selected specific operations.",
                ),
                scope_selection_mode=ScopeSelectionMode.OPERATIONS,
                selected_operation_ids=operation_ids,
                max_test_cases=max_test_cases,
                source="heuristic",
            )

        return ScopeConversationDecision(
            action="clarify",
            reason=self._localize(
                preferred_language,
                "Tôi chưa xác định được chính xác scope bạn muốn test.",
                "I could not determine the exact scope you want to test.",
            ),
            follow_up_question=self._default_scope_question(
                preferred_language=preferred_language,
                group_count=len(scope_catalog_groups),
                operation_count=len(scope_catalog_operations),
            ),
            max_test_cases=max_test_cases,
            source="heuristic",
        )

    def _fallback_recommendation(
        self,
        *,
        user_message: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
    ) -> ScopeConversationDecision:
        mode = (
            ScopeRecommendationMode.DEPRIORITIZE
            if self._looks_like_negative_recommendation(user_message)
            else ScopeRecommendationMode.PRIORITIZE
        )
        max_test_cases = self._extract_max_test_cases(user_message)

        scored: list[tuple[float, WorkflowScopeCatalogGroup]] = []
        for group in scope_catalog_groups:
            score = self._score_group(
                group=group,
                scope_catalog_operations=scope_catalog_operations,
            )
            scored.append((score, group))

        scored.sort(key=lambda item: item[0], reverse=True)

        limit = 3
        if max_test_cases is not None:
            if max_test_cases <= 2:
                limit = min(2, max(1, len(scope_catalog_groups)))
            elif max_test_cases == 3:
                limit = min(3, max(1, len(scope_catalog_groups)))

        if mode == ScopeRecommendationMode.PRIORITIZE:
            selected_groups = [group.group_id for _, group in scored[:limit]]
        else:
            selected_groups = [
                group.group_id
                for _, group in sorted(scored, key=lambda item: item[0])[:limit]
            ]

        recommendation = WorkflowScopeRecommendation(
            mode=mode,
            group_ids=selected_groups,
            operation_ids=self._expand_group_ids_to_operation_ids(
                group_ids=selected_groups,
                scope_catalog_groups=scope_catalog_groups,
            ),
            rationale=self._localize(
                preferred_language,
                "Gợi ý hiện tại ưu tiên các nhóm gần với smoke test, core flow và loại bớt các nhóm phụ/niche.",
                "This recommendation prioritizes groups that are closer to smoke tests and core flows, while pushing auxiliary/niche groups later.",
            ),
            follow_up_question=self._localize(
                preferred_language,
                "Bạn có thể nói `thực hiện theo gợi ý đi`, `chỉ test nhóm đầu tiên`, hoặc `bỏ nhóm X`.",
                "You can say `apply the recommendation`, `test only the first group`, or `exclude group X`.",
            ),
            source_user_message=user_message,
            rendered_message=None,
        )

        return ScopeConversationDecision(
            action="recommend_scope",
            reason=self._localize(
                preferred_language,
                "Đã tạo gợi ý scope theo heuristic fallback.",
                "Generated a scope recommendation using the fallback heuristic.",
            ),
            recommendation=recommendation,
            rationale=recommendation.rationale,
            follow_up_question=recommendation.follow_up_question,
            max_test_cases=max_test_cases,
            source="heuristic",
        )

    def _try_accept_latest_recommendation(
        self,
        *,
        user_message: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        latest_recommendation: WorkflowScopeRecommendation,
    ) -> ScopeConversationDecision | None:
        if not latest_recommendation.has_payload():
            return None

        if not self._looks_like_accept_recommendation(user_message):
            return None

        return self._apply_recommendation_to_selection(
            preferred_language=preferred_language,
            scope_catalog_groups=scope_catalog_groups,
            scope_catalog_operations=scope_catalog_operations,
            recommendation=latest_recommendation,
            user_message=user_message,
            source="latest_recommendation",
        )

    def _apply_recommendation_to_selection(
        self,
        *,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        recommendation: WorkflowScopeRecommendation,
        user_message: str,
        source: str,
    ) -> ScopeConversationDecision:
        if recommendation.mode == ScopeRecommendationMode.DEPRIORITIZE:
            excluded_group_ids = self._filter_valid_group_ids(
                recommendation.group_ids,
                scope_catalog_groups,
            )
            excluded_operation_ids = self._filter_valid_operation_ids(
                recommendation.operation_ids,
                scope_catalog_operations,
            )
            if excluded_group_ids and not excluded_operation_ids:
                excluded_operation_ids = self._expand_group_ids_to_operation_ids(
                    group_ids=excluded_group_ids,
                    scope_catalog_groups=scope_catalog_groups,
                )

            selected_group_ids = [
                item.group_id
                for item in scope_catalog_groups
                if item.group_id not in set(excluded_group_ids)
            ]
            selected_operation_ids = [
                item.operation_id
                for item in scope_catalog_operations
                if item.operation_id not in set(excluded_operation_ids)
            ]
            mode = ScopeSelectionMode.CUSTOM
            reason = self._localize(
                preferred_language,
                "Đã áp dụng gợi ý loại trừ các nhóm nên để sau.",
                "Applied the recommendation to exclude the groups that should be left for later.",
            )
        else:
            selected_group_ids = self._filter_valid_group_ids(
                recommendation.group_ids,
                scope_catalog_groups,
            )
            selected_operation_ids = self._filter_valid_operation_ids(
                recommendation.operation_ids,
                scope_catalog_operations,
            )
            if selected_group_ids and not selected_operation_ids:
                selected_operation_ids = self._expand_group_ids_to_operation_ids(
                    group_ids=selected_group_ids,
                    scope_catalog_groups=scope_catalog_groups,
                )
            excluded_group_ids = []
            excluded_operation_ids = []
            mode = ScopeSelectionMode.GROUPS
            reason = self._localize(
                preferred_language,
                "Đã áp dụng gợi ý các nhóm nên test trước.",
                "Applied the recommendation for the groups that should be tested first.",
            )

        if not selected_operation_ids:
            return ScopeConversationDecision(
                action="clarify",
                reason=self._localize(
                    preferred_language,
                    "Tôi chưa map được gợi ý gần nhất sang operation cụ thể để test.",
                    "I could not map the latest recommendation to concrete operations to test.",
                ),
                follow_up_question=self._localize(
                    preferred_language,
                    "Bạn hãy chọn rõ hơn theo nhóm hoặc operation.",
                    "Please choose more explicitly by group or operation.",
                ),
                source=source,
            )

        return ScopeConversationDecision(
            action="select_scope",
            reason=reason,
            scope_selection_mode=mode,
            selected_group_ids=selected_group_ids,
            selected_operation_ids=selected_operation_ids,
            excluded_group_ids=excluded_group_ids,
            excluded_operation_ids=excluded_operation_ids,
            recommendation=recommendation,
            max_test_cases=self._extract_max_test_cases(user_message),
            source=source,
        )

    def _build_gate_system_prompt(
        self,
        *,
        preferred_language: SupportedLanguage,
    ) -> str:
        language_name = "Vietnamese" if preferred_language == "vi" else "English"
        return (
            "You are a workflow gate decision agent for API test scope confirmation.\n"
            "Decide whether the workflow should require an intermediate scope confirmation step "
            "or can go directly to review.\n"
            "Use require_scope_confirmation when the original request is broad at target level, "
            "even if an upstream understanding step has already narrowed it heuristically.\n"
            "Important: if the original request only mentions a target-like token that also appears "
            "in an endpoint path or operation name (for example target 'img' and endpoint '/img'), "
            "do NOT treat that as explicit scope.\n"
            "Use direct_to_review only when the user truly specifies a function, endpoint, method, "
            "or narrow scope explicitly.\n"
            f"Write reason and follow_up_question in {language_name}."
        )

    def _build_gate_human_prompt(
        self,
        *,
        original_request: str,
        selected_target: str,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        understanding_explanation: str | None,
        canonical_command: str | None,
        narrowed_scope_group_ids: list[str],
        narrowed_scope_operation_ids: list[str],
    ) -> str:
        group_titles = [item.title for item in scope_catalog_groups[:20]]
        operation_previews = [
            f"{item.method} {item.path}" for item in scope_catalog_operations[:20]
        ]
        return (
            f"Selected target: {selected_target}\n"
            f"Original request: {original_request}\n"
            f"Group count: {len(scope_catalog_groups)}\n"
            f"Operation count: {len(scope_catalog_operations)}\n"
            f"Group titles: {group_titles}\n"
            f"Operation previews: {operation_previews}\n"
            f"Understanding explanation: {understanding_explanation or '-'}\n"
            f"Canonical command: {canonical_command or '-'}\n"
            f"Narrowed scope group ids: {narrowed_scope_group_ids}\n"
            f"Narrowed scope operation ids: {narrowed_scope_operation_ids}"
        )

    def _build_selection_system_prompt(
        self,
        *,
        preferred_language: SupportedLanguage,
    ) -> str:
        language_name = "Vietnamese" if preferred_language == "vi" else "English"
        return (
            "You are an API testing scope selection agent.\n"
            "Interpret the user's scope selection over the provided function groups and operations.\n"
            "Return only valid group_ids and operation_ids from the provided catalog.\n"
            "If the user's message is still ambiguous, choose action='clarify'.\n"
            "If the user says they want only a small number of testcases, preserve that budget in max_test_cases.\n"
            f"Write reason and follow_up_question in {language_name}."
        )

    def _build_selection_human_prompt(
        self,
        *,
        original_request: str,
        user_message: str,
        selected_target: str,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        latest_recommendation: WorkflowScopeRecommendation | None,
        scope_confirmation_history: list[str],
    ) -> str:
        group_lines = [
            f"group_id={item.group_id}; title={item.title}; description={item.description or '-'}; operation_ids={list(item.operation_ids)}"
            for item in scope_catalog_groups[:20]
        ]
        operation_lines = [
            f"operation_id={item.operation_id}; method={item.method}; path={item.path}; group_id={item.group_id}; summary={item.summary or '-'}"
            for item in scope_catalog_operations[:40]
        ]
        history_text = "\n".join(f"- {item}" for item in scope_confirmation_history[-10:]) or "-"
        latest_reco_dump = {
            "mode": latest_recommendation.mode.value
            if latest_recommendation and latest_recommendation.mode is not None
            else None,
            "group_ids": list(latest_recommendation.group_ids)
            if latest_recommendation
            else [],
            "operation_ids": list(latest_recommendation.operation_ids)
            if latest_recommendation
            else [],
            "rationale": latest_recommendation.rationale if latest_recommendation else None,
            "source_user_message": (
                latest_recommendation.source_user_message
                if latest_recommendation
                else None
            ),
        }
        return (
            f"Target: {selected_target}\n"
            f"Original request: {original_request}\n"
            f"Current user message: {user_message}\n"
            f"Latest recommendation: {latest_reco_dump}\n"
            f"Scope confirmation history:\n{history_text}\n"
            "Available groups:\n"
            + "\n".join(group_lines)
            + "\nAvailable operations:\n"
            + "\n".join(operation_lines)
        )

    def _build_recommendation_system_prompt(
        self,
        *,
        preferred_language: SupportedLanguage,
    ) -> str:
        language_name = "Vietnamese" if preferred_language == "vi" else "English"
        return (
            "You are a recommendation agent for API testing scope confirmation.\n"
            "Recommend which groups should be tested first, or which groups should not be tested first.\n"
            "Prefer smoke-test friendly groups first: health, ping, simple, search, core read/write flow, "
            "main business endpoints.\n"
            "Deprioritize beta, NFT, treasury, derivative, or clearly niche groups unless the user explicitly wants them.\n"
            "If the user asks for only a small number of testcases, reflect that through max_test_cases and a smaller recommendation set.\n"
            "Return only valid group_ids or operation_ids.\n"
            f"Write rationale and follow_up_question in {language_name}."
        )

    def _build_recommendation_human_prompt(
        self,
        *,
        original_request: str,
        user_message: str,
        selected_target: str,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        scope_confirmation_history: list[str],
    ) -> str:
        history_text = "\n".join(f"- {item}" for item in scope_confirmation_history[-10:]) or "-"
        operation_lookup = {item.operation_id: item for item in scope_catalog_operations}
        group_lines: list[str] = []

        for group in scope_catalog_groups:
            previews: list[str] = []
            for operation_id in group.operation_ids[:4]:
                operation = operation_lookup.get(operation_id)
                if operation is not None:
                    previews.append(f"{operation.method} {operation.path}")
            group_lines.append(
                f"group_id={group.group_id}; title={group.title}; description={group.description or '-'}; previews={previews}"
            )

        return (
            f"Target: {selected_target}\n"
            f"Original request: {original_request}\n"
            f"Current user message: {user_message}\n"
            f"Scope confirmation history:\n{history_text}\n"
            "Available groups:\n"
            + "\n".join(group_lines)
        )

    def _filter_valid_group_ids(
        self,
        group_ids: list[str],
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
    ) -> list[str]:
        valid = {item.group_id for item in scope_catalog_groups}
        seen: set[str] = set()
        result: list[str] = []
        for item in group_ids:
            cleaned = str(item).strip()
            if cleaned in valid and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result

    def _filter_valid_operation_ids(
        self,
        operation_ids: list[str],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
    ) -> list[str]:
        valid = {item.operation_id for item in scope_catalog_operations}
        seen: set[str] = set()
        result: list[str] = []
        for item in operation_ids:
            cleaned = str(item).strip()
            if cleaned in valid and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result

    def _coerce_scope_selection_mode(
        self,
        value: str | ScopeSelectionMode | None,
    ) -> ScopeSelectionMode | None:
        if value is None:
            return None
        if isinstance(value, ScopeSelectionMode):
            return value
        lowered = str(value).strip().lower()
        for item in ScopeSelectionMode:
            if item.value == lowered:
                return item
        return None

    def _coerce_recommendation_mode(
        self,
        value: str | ScopeRecommendationMode | None,
    ) -> ScopeRecommendationMode | None:
        if value is None:
            return None
        if isinstance(value, ScopeRecommendationMode):
            return value
        lowered = str(value).strip().lower()
        for item in ScopeRecommendationMode:
            if item.value == lowered:
                return item
        return None

    def _normalize(self, value: str) -> str:
        lowered = value.strip().lower()
        normalized = unicodedata.normalize("NFD", lowered)
        without_accents = "".join(
            ch for ch in normalized if unicodedata.category(ch) != "Mn"
        )
        return " ".join(without_accents.split()).replace("đ", "d")

    def _tokenize(self, value: str) -> list[str]:
        normalized = self._normalize(value)
        return [item for item in re.split(r"[^a-z0-9]+", normalized) if item]

    def _extract_max_test_cases(self, user_message: str) -> int | None:
        normalized = self._normalize(user_message)
        match = re.search(
            r"\b(\d+)\s*(testcase|testcases|test case|test case|case|cases)\b",
            normalized,
        )
        if match:
            return int(match.group(1))

        short_budget_tokens = [
            "it testcase",
            "it case",
            "few testcase",
            "few case",
            "nho gon",
            "ngan gon",
            "smoke test",
        ]
        if any(token in normalized for token in short_budget_tokens):
            return 2

        return None

    def _has_explicit_endpoint_scope(self, text: str) -> bool:
        lowered = text.strip().lower()
        if "/" in text:
            return True
        if re.search(r"\b(get|post|put|patch|delete)\b", lowered):
            return True
        explicit_tokens = ["endpoint", "operation", "operation_id", "path "]
        normalized = self._normalize(text)
        return any(token in lowered or token in normalized for token in explicit_tokens)

    def _target_tokens(self, selected_target: str) -> set[str]:
        tokens = set(self._tokenize(selected_target))
        ignored = {
            "api",
            "local",
            "staging",
            "stage",
            "prod",
            "production",
            "demo",
            "service",
        }
        return {token for token in tokens if token not in ignored}

    def _looks_like_general_target_request(
        self,
        *,
        normalized_request: str,
        selected_target: str,
    ) -> bool:
        request_tokens = set(self._tokenize(normalized_request))
        target_tokens = self._target_tokens(selected_target)

        generic_markers = {
            "test",
            "target",
            "hay",
            "kiem",
            "thu",
            "tra",
            "run",
            "start",
            "di",
        }
        semantic_request_tokens = {
            token for token in request_tokens if token not in generic_markers
        }

        if not semantic_request_tokens:
            return True

        if semantic_request_tokens.issubset(target_tokens):
            return True

        trigger_phrases = (
            "test target",
            "test ",
            "hay test",
            "kiem thu",
            "kiem tra",
            "thu ",
            "run test",
            "start test",
        )
        return any(phrase in normalized_request for phrase in trigger_phrases) and len(
            semantic_request_tokens
        ) <= 2

    def _request_target_operation_collision(
        self,
        *,
        original_request: str,
        selected_target: str,
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        narrowed_scope_operation_ids: list[str],
    ) -> bool:
        request_tokens = set(self._tokenize(original_request))
        target_tokens = self._target_tokens(selected_target)

        if not request_tokens or not target_tokens:
            return False
        if not request_tokens.intersection(target_tokens):
            return False

        narrowed_operations = [
            item
            for item in scope_catalog_operations
            if item.operation_id in set(narrowed_scope_operation_ids)
        ]
        if not narrowed_operations:
            return False

        operation_tokens: set[str] = set()
        for operation in narrowed_operations:
            operation_tokens.update(self._tokenize(operation.operation_id))
            operation_tokens.update(self._tokenize(operation.path))
            operation_tokens.update(self._tokenize(operation.summary or ""))
            operation_tokens.update(self._tokenize(operation.description or ""))

        collision_tokens = request_tokens.intersection(target_tokens).intersection(
            operation_tokens
        )
        return bool(collision_tokens)

    def _looks_like_exclusion_request(self, normalized_message: str) -> bool:
        tokens = ["bo nhom", "skip", "excluding", "tru ", "exclude", "bo "]
        return any(token in normalized_message for token in tokens)

    def _looks_like_negative_recommendation(self, user_message: str) -> bool:
        normalized = self._normalize(user_message)
        tokens = [
            "khong test truoc",
            "khong nen test truoc",
            "de sau",
            "not test first",
            "should not test first",
            "avoid first",
            "deprioritize",
        ]
        return any(token in normalized for token in tokens)

    def _looks_like_accept_recommendation(self, user_message: str) -> bool:
        normalized = self._normalize(user_message)
        tokens = [
            "theo goi y",
            "thuc hien theo goi y",
            "lam theo goi y",
            "test theo goi y",
            "theo de xuat",
            "thuc hien theo de xuat",
            "lam theo de xuat",
            "dung",
            "ok",
            "dong y",
            "chot",
            "go with that",
            "apply recommendation",
            "follow your suggestion",
            "use your suggestion",
        ]
        return any(token in normalized for token in tokens)

    def _resolve_group_ids_by_text(
        self,
        *,
        normalized_message: str,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
    ) -> list[str]:
        matched: list[str] = []
        seen: set[str] = set()

        for group in scope_catalog_groups:
            group_id_norm = self._normalize(group.group_id)
            title_norm = self._normalize(group.title)
            description_norm = self._normalize(group.description or "")

            if (
                (group_id_norm and group_id_norm in normalized_message)
                or (title_norm and title_norm in normalized_message)
                or (description_norm and description_norm in normalized_message)
            ):
                if group.group_id not in seen:
                    seen.add(group.group_id)
                    matched.append(group.group_id)

        return matched

    def _resolve_operation_ids_by_text(
        self,
        *,
        normalized_message: str,
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
    ) -> list[str]:
        matched: list[str] = []
        seen: set[str] = set()

        for operation in scope_catalog_operations:
            operation_id_norm = self._normalize(operation.operation_id)
            path_norm = self._normalize(operation.path)
            method_path_norm = self._normalize(f"{operation.method} {operation.path}")
            summary_norm = self._normalize(operation.summary or "")
            description_norm = self._normalize(operation.description or "")

            if (
                (operation_id_norm and operation_id_norm in normalized_message)
                or (path_norm and path_norm in normalized_message)
                or (method_path_norm and method_path_norm in normalized_message)
                or (summary_norm and summary_norm in normalized_message)
                or (description_norm and description_norm in normalized_message)
            ):
                if operation.operation_id not in seen:
                    seen.add(operation.operation_id)
                    matched.append(operation.operation_id)

        return matched

    def _expand_group_ids_to_operation_ids(
        self,
        *,
        group_ids: list[str],
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
    ) -> list[str]:
        wanted = set(group_ids)
        selected_operation_ids: list[str] = []
        seen: set[str] = set()

        for group in scope_catalog_groups:
            if group.group_id not in wanted:
                continue
            for operation_id in group.operation_ids:
                cleaned = str(operation_id).strip()
                if not cleaned or cleaned in seen:
                    continue
                seen.add(cleaned)
                selected_operation_ids.append(cleaned)

        return selected_operation_ids

    def _expand_numeric_selection(self, numbers: list[int]) -> list[int]:
        if not numbers:
            return []

        if len(numbers) == 2:
            start, end = numbers
            if start <= end:
                return list(range(start, end + 1))

        seen: set[int] = set()
        result: list[int] = []
        for item in numbers:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _score_group(
        self,
        *,
        group: WorkflowScopeCatalogGroup,
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
    ) -> float:
        normalized_title = self._normalize(group.title)
        normalized_description = self._normalize(group.description or "")
        blob = f"{normalized_title} {normalized_description}"

        score = 0.0

        positive_markers = {
            "ping": 6.0,
            "simple": 5.0,
            "search": 4.5,
            "coin": 4.0,
            "global": 3.8,
            "exchange rates": 3.5,
            "health": 5.0,
            "lookup": 3.0,
            "price": 4.0,
            "image": 4.0,
            "img": 4.0,
            "post": 3.8,
            "publish": 3.8,
        }
        negative_markers = {
            "beta": -5.0,
            "nft": -4.5,
            "treasury": -4.0,
            "derivative": -3.5,
            "contract": -2.5,
            "asset platform": -2.0,
            "onchain": -3.0,
        }

        for marker, value in positive_markers.items():
            if marker in blob:
                score += value

        for marker, value in negative_markers.items():
            if marker in blob:
                score += value

        operation_count = len(group.operation_ids)
        if 1 <= operation_count <= 3:
            score += 1.0
        elif operation_count >= 8:
            score -= 0.5

        matching_operations = [
            item
            for item in scope_catalog_operations
            if item.operation_id in set(group.operation_ids)
        ]
        get_ratio_bonus = (
            sum(1 for item in matching_operations if item.method.upper() == "GET") * 0.1
        )
        post_ratio_bonus = (
            sum(1 for item in matching_operations if item.method.upper() == "POST") * 0.1
        )
        score += min(get_ratio_bonus + post_ratio_bonus, 1.2)

        return score

    def _default_scope_question(
        self,
        *,
        preferred_language: SupportedLanguage,
        group_count: int,
        operation_count: int,
    ) -> str:
        return self._localize(
            preferred_language,
            (
                f"Hiện có {group_count} nhóm chức năng / {operation_count} operation. "
                "Bạn muốn test toàn bộ, chỉ một vài nhóm, hay một số operation cụ thể?"
            ),
            (
                f"There are currently {group_count} function groups / {operation_count} operations. "
                "Do you want to test all of them, just a few groups, or some specific operations?"
            ),
        )

    def _localize(
        self,
        preferred_language: SupportedLanguage,
        vi_text: str,
        en_text: str,
    ) -> str:
        return en_text if preferred_language == "en" else vi_text