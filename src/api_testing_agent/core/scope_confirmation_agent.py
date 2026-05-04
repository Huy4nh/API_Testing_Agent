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
    ScopeSelectionMode,
    WorkflowScopeCatalogGroup,
    WorkflowScopeCatalogOperation,
)

ScopeGateDecision = Literal["require_scope_confirmation", "direct_to_review"]
ScopeInteractionMode = Literal["entry_gate", "selection", "recommendation"]


@dataclass(frozen=True)
class ScopeConfirmationDecision:
    decision: ScopeGateDecision
    reason: str
    scope_selection_mode: ScopeSelectionMode | None = None
    selected_group_ids: list[str] = field(default_factory=list)
    selected_operation_ids: list[str] = field(default_factory=list)
    excluded_group_ids: list[str] = field(default_factory=list)
    excluded_operation_ids: list[str] = field(default_factory=list)
    recommendation_mode: Literal["prioritize", "deprioritize"] | None = None
    recommendation_group_ids: list[str] = field(default_factory=list)
    follow_up_question: str | None = None
    rationale: str | None = None


class _AIScopeDecisionPayload(BaseModel):
    decision: ScopeGateDecision = Field(
        description="Whether the workflow should require a scope confirmation step or can go directly to review."
    )
    reason: str = Field(default="", description="Short explanation for the decision.")
    rationale: str | None = Field(
        default=None,
        description="Extra reasoning for UI display or logs.",
    )


class _AIScopeSelectionPayload(BaseModel):
    scope_selection_mode: Literal["all", "groups", "operations", "custom", "clarify"] = Field(
        description="Interpretation of the user's scope selection message."
    )
    selected_group_ids: list[str] = Field(default_factory=list)
    selected_operation_ids: list[str] = Field(default_factory=list)
    excluded_group_ids: list[str] = Field(default_factory=list)
    excluded_operation_ids: list[str] = Field(default_factory=list)
    reason: str = Field(default="", description="Short explanation of the selection.")
    follow_up_question: str | None = Field(
        default=None,
        description="Clarifying question if the selection is ambiguous.",
    )


class _AIScopeRecommendationPayload(BaseModel):
    recommendation_mode: Literal["prioritize", "deprioritize"] = Field(
        description="Whether the user is asking what should be tested first or what should not be tested first."
    )
    recommendation_group_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(default="")
    follow_up_question: str | None = Field(default=None)


class _ScopeAgentState(TypedDict):
    interaction_mode: ScopeInteractionMode
    original_request: str
    user_message: str
    selected_target: str
    preferred_language: SupportedLanguage
    scope_catalog_groups: list[WorkflowScopeCatalogGroup]
    scope_catalog_operations: list[WorkflowScopeCatalogOperation]
    scope_confirmation_history: list[str]
    understanding_explanation: NotRequired[str | None]
    canonical_command: NotRequired[str | None]
    narrowed_scope_operation_ids: NotRequired[list[str]]
    narrowed_scope_group_ids: NotRequired[list[str]]
    final_result: NotRequired[ScopeConfirmationDecision]


class ScopeConfirmationAgent:
    def __init__(
        self,
        *,
        model_name: str,
        model_provider: str | None = None,
    ) -> None:
        self._logger = get_logger(__name__)
        self._model_name = model_name.strip()
        self._model_provider = (model_provider or "").strip() or None

        self._entry_gate_model: Any | None = None
        self._selection_model: Any | None = None
        self._recommendation_model: Any | None = None
        self._enabled = False

        try:
            base_model = init_chat_model(
                model=self._model_name,
                model_provider=self._model_provider,
                temperature=0,
            )
            self._entry_gate_model = base_model.with_structured_output(
                _AIScopeDecisionPayload
            )
            self._selection_model = base_model.with_structured_output(
                _AIScopeSelectionPayload
            )
            self._recommendation_model = base_model.with_structured_output(
                _AIScopeRecommendationPayload
            )
            self._enabled = True
            self._logger.info(
                "Initialized ScopeConfirmationAgent.",
                extra={"payload_source": "scope_confirmation_agent_init"},
            )
        except Exception as exc:
            self._logger.warning(
                f"ScopeConfirmationAgent disabled and will fall back to heuristics: {exc}",
                extra={"payload_source": "scope_confirmation_agent_init_failed"},
            )
            self._entry_gate_model = None
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
        narrowed_scope_operation_ids: list[str] | None = None,
        narrowed_scope_group_ids: list[str] | None = None,
    ) -> ScopeConfirmationDecision:
        state: _ScopeAgentState = {
            "interaction_mode": "entry_gate",
            "original_request": original_request,
            "user_message": original_request,
            "selected_target": selected_target,
            "preferred_language": preferred_language,
            "scope_catalog_groups": list(scope_catalog_groups),
            "scope_catalog_operations": list(scope_catalog_operations),
            "scope_confirmation_history": [],
            "understanding_explanation": understanding_explanation,
            "canonical_command": canonical_command,
            "narrowed_scope_operation_ids": list(narrowed_scope_operation_ids or []),
            "narrowed_scope_group_ids": list(narrowed_scope_group_ids or []),
        }
        result = cast(_ScopeAgentState, self._graph.invoke(state))
        final_result = result.get("final_result")
        if final_result is None:
            return self._fallback_entry_gate(
                original_request=original_request,
                selected_target=selected_target,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
                understanding_explanation=understanding_explanation,
                canonical_command=canonical_command,
                narrowed_scope_operation_ids=list(narrowed_scope_operation_ids or []),
                narrowed_scope_group_ids=list(narrowed_scope_group_ids or []),
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
        scope_confirmation_history: list[str] | None = None,
    ) -> ScopeConfirmationDecision:
        state: _ScopeAgentState = {
            "interaction_mode": "selection",
            "original_request": original_request,
            "user_message": user_message,
            "selected_target": selected_target,
            "preferred_language": preferred_language,
            "scope_catalog_groups": list(scope_catalog_groups),
            "scope_catalog_operations": list(scope_catalog_operations),
            "scope_confirmation_history": list(scope_confirmation_history or []),
        }
        result = cast(_ScopeAgentState, self._graph.invoke(state))
        final_result = result.get("final_result")
        if final_result is None:
            return self._fallback_scope_selection(
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
    ) -> ScopeConfirmationDecision:
        state: _ScopeAgentState = {
            "interaction_mode": "recommendation",
            "original_request": original_request,
            "user_message": user_message,
            "selected_target": selected_target,
            "preferred_language": preferred_language,
            "scope_catalog_groups": list(scope_catalog_groups),
            "scope_catalog_operations": list(scope_catalog_operations),
            "scope_confirmation_history": list(scope_confirmation_history or []),
        }
        result = cast(_ScopeAgentState, self._graph.invoke(state))
        final_result = result.get("final_result")
        if final_result is None:
            return self._fallback_recommendation(
                user_message=user_message,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
            )
        return final_result

    def _build_graph(self):
        builder = StateGraph(_ScopeAgentState)

        builder.add_node("entry_gate", self._node_entry_gate)
        builder.add_node("selection", self._node_selection)
        builder.add_node("recommendation", self._node_recommendation)

        builder.add_conditional_edges(
            START,
            self._route_start,
            {
                "entry_gate": "entry_gate",
                "selection": "selection",
                "recommendation": "recommendation",
            },
        )
        builder.add_edge("entry_gate", END)
        builder.add_edge("selection", END)
        builder.add_edge("recommendation", END)

        return builder.compile()

    def _route_start(
        self,
        state: _ScopeAgentState,
    ) -> ScopeInteractionMode:
        return state["interaction_mode"]

    def _node_entry_gate(
        self,
        state: _ScopeAgentState,
    ) -> dict[str, ScopeConfirmationDecision]:
        decision = self._ai_or_fallback_entry_gate(
            original_request=state["original_request"],
            selected_target=state["selected_target"],
            preferred_language=state["preferred_language"],
            scope_catalog_groups=state["scope_catalog_groups"],
            scope_catalog_operations=state["scope_catalog_operations"],
            understanding_explanation=state.get("understanding_explanation"),
            canonical_command=state.get("canonical_command"),
            narrowed_scope_operation_ids=list(state.get("narrowed_scope_operation_ids", [])),
            narrowed_scope_group_ids=list(state.get("narrowed_scope_group_ids", [])),
        )
        return {"final_result": decision}

    def _node_selection(
        self,
        state: _ScopeAgentState,
    ) -> dict[str, ScopeConfirmationDecision]:
        decision = self._ai_or_fallback_scope_selection(
            original_request=state["original_request"],
            user_message=state["user_message"],
            selected_target=state["selected_target"],
            preferred_language=state["preferred_language"],
            scope_catalog_groups=state["scope_catalog_groups"],
            scope_catalog_operations=state["scope_catalog_operations"],
            scope_confirmation_history=state["scope_confirmation_history"],
        )
        return {"final_result": decision}

    def _node_recommendation(
        self,
        state: _ScopeAgentState,
    ) -> dict[str, ScopeConfirmationDecision]:
        decision = self._ai_or_fallback_recommendation(
            original_request=state["original_request"],
            user_message=state["user_message"],
            selected_target=state["selected_target"],
            preferred_language=state["preferred_language"],
            scope_catalog_groups=state["scope_catalog_groups"],
            scope_catalog_operations=state["scope_catalog_operations"],
            scope_confirmation_history=state["scope_confirmation_history"],
        )
        return {"final_result": decision}

    def _ai_or_fallback_entry_gate(
        self,
        *,
        original_request: str,
        selected_target: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        understanding_explanation: str | None,
        canonical_command: str | None,
        narrowed_scope_operation_ids: list[str],
        narrowed_scope_group_ids: list[str],
    ) -> ScopeConfirmationDecision:
        logger = bind_logger(
            self._logger,
            target_name=selected_target,
            payload_source="scope_confirmation_agent_entry_gate",
        )
        logger.info("Running entry gate decision for scope confirmation.")

        model = self._entry_gate_model
        if not self._enabled or model is None:
            return self._fallback_entry_gate(
                original_request=original_request,
                selected_target=selected_target,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
                understanding_explanation=understanding_explanation,
                canonical_command=canonical_command,
                narrowed_scope_operation_ids=narrowed_scope_operation_ids,
                narrowed_scope_group_ids=narrowed_scope_group_ids,
            )

        try:
            payload = cast(
                _AIScopeDecisionPayload,
                model.invoke(
                    [
                        SystemMessage(
                            content=self._build_entry_gate_system_prompt(
                                preferred_language
                            )
                        ),
                        HumanMessage(
                            content=self._build_entry_gate_human_prompt(
                                original_request=original_request,
                                selected_target=selected_target,
                                scope_catalog_groups=scope_catalog_groups,
                                scope_catalog_operations=scope_catalog_operations,
                                understanding_explanation=understanding_explanation,
                                canonical_command=canonical_command,
                                narrowed_scope_operation_ids=narrowed_scope_operation_ids,
                                narrowed_scope_group_ids=narrowed_scope_group_ids,
                            )
                        ),
                    ]
                ),
            )
            return ScopeConfirmationDecision(
                decision=payload.decision,
                reason=payload.reason.strip(),
                rationale=payload.rationale,
                follow_up_question=self._default_scope_question(
                    preferred_language=preferred_language,
                    group_count=len(scope_catalog_groups),
                    operation_count=len(scope_catalog_operations),
                )
                if payload.decision == "require_scope_confirmation"
                else None,
            )
        except Exception as exc:
            logger.warning(
                f"AI entry gate failed. Falling back to heuristics: {exc}",
                extra={"payload_source": "scope_confirmation_agent_entry_gate_failed"},
            )
            return self._fallback_entry_gate(
                original_request=original_request,
                selected_target=selected_target,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
                understanding_explanation=understanding_explanation,
                canonical_command=canonical_command,
                narrowed_scope_operation_ids=narrowed_scope_operation_ids,
                narrowed_scope_group_ids=narrowed_scope_group_ids,
            )

    def _ai_or_fallback_scope_selection(
        self,
        *,
        original_request: str,
        user_message: str,
        selected_target: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        scope_confirmation_history: list[str],
    ) -> ScopeConfirmationDecision:
        logger = bind_logger(
            self._logger,
            target_name=selected_target,
            payload_source="scope_confirmation_agent_selection",
        )
        logger.info("Interpreting scope selection message.")

        model = self._selection_model
        if not self._enabled or model is None:
            return self._fallback_scope_selection(
                user_message=user_message,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
            )

        try:
            payload = cast(
                _AIScopeSelectionPayload,
                model.invoke(
                    [
                        SystemMessage(
                            content=self._build_scope_selection_system_prompt(
                                preferred_language
                            )
                        ),
                        HumanMessage(
                            content=self._build_scope_selection_human_prompt(
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
                payload.selected_group_ids,
                scope_catalog_groups,
            )
            operation_ids = self._filter_valid_operation_ids(
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

            if payload.scope_selection_mode == "clarify":
                return ScopeConfirmationDecision(
                    decision="require_scope_confirmation",
                    reason=payload.reason.strip() or "Need clearer scope selection.",
                    follow_up_question=payload.follow_up_question
                    or self._default_scope_question(
                        preferred_language=preferred_language,
                        group_count=len(scope_catalog_groups),
                        operation_count=len(scope_catalog_operations),
                    ),
                )

            mode = self._coerce_scope_selection_mode(payload.scope_selection_mode)
            if mode is None:
                return self._fallback_scope_selection(
                    user_message=user_message,
                    preferred_language=preferred_language,
                    scope_catalog_groups=scope_catalog_groups,
                    scope_catalog_operations=scope_catalog_operations,
                )

            if mode == ScopeSelectionMode.GROUPS and group_ids:
                operation_ids = self._expand_group_ids_to_operation_ids(
                    group_ids=group_ids,
                    scope_catalog_groups=scope_catalog_groups,
                )

            if mode == ScopeSelectionMode.ALL and not operation_ids:
                group_ids = [item.group_id for item in scope_catalog_groups]
                operation_ids = [item.operation_id for item in scope_catalog_operations]

            return ScopeConfirmationDecision(
                decision="direct_to_review",
                reason=payload.reason.strip() or "Scope selection confirmed.",
                scope_selection_mode=mode,
                selected_group_ids=group_ids,
                selected_operation_ids=operation_ids,
                excluded_group_ids=excluded_group_ids,
                excluded_operation_ids=excluded_operation_ids,
            )
        except Exception as exc:
            logger.warning(
                f"AI scope selection failed. Falling back to heuristics: {exc}",
                extra={"payload_source": "scope_confirmation_agent_selection_failed"},
            )
            return self._fallback_scope_selection(
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
    ) -> ScopeConfirmationDecision:
        logger = bind_logger(
            self._logger,
            target_name=selected_target,
            payload_source="scope_confirmation_agent_recommendation",
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
                _AIScopeRecommendationPayload,
                model.invoke(
                    [
                        SystemMessage(
                            content=self._build_recommendation_system_prompt(
                                preferred_language
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

            recommendation_group_ids = self._filter_valid_group_ids(
                payload.recommendation_group_ids,
                scope_catalog_groups,
            )
            if not recommendation_group_ids:
                return self._fallback_recommendation(
                    user_message=user_message,
                    preferred_language=preferred_language,
                    scope_catalog_groups=scope_catalog_groups,
                    scope_catalog_operations=scope_catalog_operations,
                )

            return ScopeConfirmationDecision(
                decision="require_scope_confirmation",
                reason="Recommendation generated for scope confirmation.",
                recommendation_mode=payload.recommendation_mode,
                recommendation_group_ids=recommendation_group_ids,
                rationale=payload.rationale.strip(),
                follow_up_question=payload.follow_up_question
                or self._default_recommendation_followup(preferred_language),
            )
        except Exception as exc:
            logger.warning(
                f"AI recommendation failed. Falling back to heuristics: {exc}",
                extra={"payload_source": "scope_confirmation_agent_recommendation_failed"},
            )
            return self._fallback_recommendation(
                user_message=user_message,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
            )

    def _fallback_entry_gate(
        self,
        *,
        original_request: str,
        selected_target: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        understanding_explanation: str | None,
        canonical_command: str | None,
        narrowed_scope_operation_ids: list[str],
        narrowed_scope_group_ids: list[str],
    ) -> ScopeConfirmationDecision:
        normalized_request = self._normalize(original_request)
        total_operations = len(scope_catalog_operations)
        total_groups = len(scope_catalog_groups)

        if self._has_explicit_endpoint_scope(original_request):
            return ScopeConfirmationDecision(
                decision="direct_to_review",
                reason="The request explicitly mentions an endpoint or HTTP method.",
            )

        if total_operations <= 1:
            return ScopeConfirmationDecision(
                decision="direct_to_review",
                reason="The target effectively exposes only one operation in scope.",
            )

        broad_markers = [
            "test target",
            "test ",
            "hay test",
            "hãy test",
            "kiem thu",
            "kiểm thử",
            "kiem tra",
            "kiểm tra",
            "thu ",
            "thử ",
            "run test",
            "start test",
        ]
        looks_broad = any(marker in normalized_request for marker in broad_markers)

        if looks_broad and self._looks_like_general_target_request(
            normalized_request=normalized_request,
            selected_target=selected_target,
        ):
            return ScopeConfirmationDecision(
                decision="require_scope_confirmation",
                reason=(
                    f"Yêu cầu vẫn đang ở mức target tổng quát cho `{selected_target}`, "
                    "chưa chỉ rõ chức năng cụ thể."
                ),
                follow_up_question=self._default_scope_question(
                    preferred_language=preferred_language,
                    group_count=total_groups,
                    operation_count=total_operations,
                ),
            )

        narrowed_ops = self._filter_valid_operation_ids(
            narrowed_scope_operation_ids,
            scope_catalog_operations,
        )
        narrowed_groups = self._filter_valid_group_ids(
            narrowed_scope_group_ids,
            scope_catalog_groups,
        )

        if looks_broad and narrowed_ops and len(narrowed_ops) < total_operations:
            if self._request_target_operation_collision(
                original_request=original_request,
                selected_target=selected_target,
                scope_catalog_operations=scope_catalog_operations,
                narrowed_scope_operation_ids=narrowed_ops,
            ):
                return ScopeConfirmationDecision(
                    decision="require_scope_confirmation",
                    reason=(
                        "Request gốc còn mơ hồ và phần scope hiện tại có dấu hiệu bị thu hẹp "
                        "do trùng token giữa tên target và tên/path operation."
                    ),
                    rationale=(
                        f"understanding={understanding_explanation or '-'}; "
                        f"canonical_command={canonical_command or '-'}"
                    ),
                    follow_up_question=self._default_scope_question(
                        preferred_language=preferred_language,
                        group_count=total_groups,
                        operation_count=total_operations,
                    ),
                )

            if len(narrowed_ops) == 1:
                return ScopeConfirmationDecision(
                    decision="require_scope_confirmation",
                    reason=(
                        "Yêu cầu gốc vẫn rộng, nhưng scope hiện tại đã bị thu hẹp xuống 1 operation bằng suy luận. "
                        "Cần xác nhận lại với người dùng trước khi sinh testcase."
                    ),
                    rationale=(
                        f"understanding={understanding_explanation or '-'}; "
                        f"canonical_command={canonical_command or '-'}"
                    ),
                    follow_up_question=self._default_scope_question(
                        preferred_language=preferred_language,
                        group_count=total_groups,
                        operation_count=total_operations,
                    ),
                )

        if looks_broad and narrowed_groups and len(narrowed_groups) < total_groups:
            return ScopeConfirmationDecision(
                decision="require_scope_confirmation",
                reason=(
                    "Yêu cầu gốc còn rộng, nhưng hệ thống đã tự suy luận hẹp xuống một vài nhóm chức năng. "
                    "Cần hỏi lại scope để tránh hiểu sai."
                ),
                follow_up_question=self._default_scope_question(
                    preferred_language=preferred_language,
                    group_count=total_groups,
                    operation_count=total_operations,
                ),
            )

        return ScopeConfirmationDecision(
            decision="direct_to_review",
            reason="The request appears specific enough to move directly to review.",
        )

    def _fallback_scope_selection(
        self,
        *,
        user_message: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
    ) -> ScopeConfirmationDecision:
        normalized = self._normalize(user_message)

        if normalized in {"test het", "all", "toan bo"}:
            return ScopeConfirmationDecision(
                decision="direct_to_review",
                reason="User explicitly selected the full scope.",
                scope_selection_mode=ScopeSelectionMode.ALL,
                selected_group_ids=[item.group_id for item in scope_catalog_groups],
                selected_operation_ids=[item.operation_id for item in scope_catalog_operations],
            )

        if self._looks_like_exclusion_request(normalized):
            group_ids = self._resolve_group_ids_by_text(
                normalized_message=normalized,
                scope_catalog_groups=scope_catalog_groups,
            )
            operation_ids = self._resolve_operation_ids_by_text(
                normalized_message=normalized,
                scope_catalog_operations=scope_catalog_operations,
            )
            selected_group_ids = [
                item.group_id
                for item in scope_catalog_groups
                if item.group_id not in set(group_ids)
            ]
            selected_operation_ids = [
                item.operation_id
                for item in scope_catalog_operations
                if item.operation_id not in set(operation_ids)
            ]
            if group_ids:
                excluded_from_groups = self._expand_group_ids_to_operation_ids(
                    group_ids=group_ids,
                    scope_catalog_groups=scope_catalog_groups,
                )
                selected_operation_ids = [
                    item
                    for item in selected_operation_ids
                    if item not in set(excluded_from_groups)
                ]

            if selected_operation_ids:
                return ScopeConfirmationDecision(
                    decision="direct_to_review",
                    reason="User excluded part of the scope.",
                    scope_selection_mode=ScopeSelectionMode.CUSTOM,
                    selected_group_ids=selected_group_ids,
                    selected_operation_ids=selected_operation_ids,
                    excluded_group_ids=group_ids,
                    excluded_operation_ids=operation_ids,
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
                    return ScopeConfirmationDecision(
                        decision="direct_to_review",
                        reason="User selected groups by index.",
                        scope_selection_mode=ScopeSelectionMode.GROUPS,
                        selected_group_ids=group_ids,
                        selected_operation_ids=operation_ids,
                    )

            for index in expanded_indexes:
                if 1 <= index <= len(scope_catalog_operations):
                    operation_ids.append(scope_catalog_operations[index - 1].operation_id)

            if operation_ids:
                return ScopeConfirmationDecision(
                    decision="direct_to_review",
                    reason="User selected operations by index.",
                    scope_selection_mode=ScopeSelectionMode.CUSTOM,
                    selected_operation_ids=operation_ids,
                )

        group_ids = self._resolve_group_ids_by_text(
            normalized_message=normalized,
            scope_catalog_groups=scope_catalog_groups,
        )
        if group_ids:
            return ScopeConfirmationDecision(
                decision="direct_to_review",
                reason="User selected groups by name.",
                scope_selection_mode=ScopeSelectionMode.GROUPS,
                selected_group_ids=group_ids,
                selected_operation_ids=self._expand_group_ids_to_operation_ids(
                    group_ids=group_ids,
                    scope_catalog_groups=scope_catalog_groups,
                ),
            )

        operation_ids = self._resolve_operation_ids_by_text(
            normalized_message=normalized,
            scope_catalog_operations=scope_catalog_operations,
        )
        if operation_ids:
            return ScopeConfirmationDecision(
                decision="direct_to_review",
                reason="User selected specific operations.",
                scope_selection_mode=ScopeSelectionMode.OPERATIONS,
                selected_operation_ids=operation_ids,
            )

        return ScopeConfirmationDecision(
            decision="require_scope_confirmation",
            reason="The scope selection is still ambiguous.",
            follow_up_question=self._default_scope_question(
                preferred_language=preferred_language,
                group_count=len(scope_catalog_groups),
                operation_count=len(scope_catalog_operations),
            ),
        )

    def _fallback_recommendation(
        self,
        *,
        user_message: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
    ) -> ScopeConfirmationDecision:
        mode: Literal["prioritize", "deprioritize"] = (
            "deprioritize"
            if self._looks_like_negative_recommendation(user_message)
            else "prioritize"
        )

        scored: list[tuple[float, WorkflowScopeCatalogGroup]] = []
        for group in scope_catalog_groups:
            score = self._score_group(
                group=group,
                scope_catalog_operations=scope_catalog_operations,
            )
            scored.append((score, group))

        scored.sort(key=lambda item: item[0], reverse=True)

        if mode == "prioritize":
            recommendation_group_ids = [group.group_id for _, group in scored[:3]]
        else:
            recommendation_group_ids = [
                group.group_id
                for _, group in sorted(scored, key=lambda item: item[0])[:3]
            ]

        rationale = self._localize(
            preferred_language,
            "Gợi ý hiện tại ưu tiên các nhóm phù hợp cho smoke test đầu tiên và để các nhóm niche/beta ở sau.",
            "This recommendation currently prioritizes groups that are suitable for an initial smoke test and leaves niche/beta groups for later.",
        )

        return ScopeConfirmationDecision(
            decision="require_scope_confirmation",
            reason="Recommendation generated from fallback heuristics.",
            recommendation_mode=mode,
            recommendation_group_ids=recommendation_group_ids,
            rationale=rationale,
            follow_up_question=self._default_recommendation_followup(preferred_language),
        )

    def _build_entry_gate_system_prompt(
        self,
        preferred_language: SupportedLanguage,
    ) -> str:
        language_name = "Vietnamese" if preferred_language == "vi" else "English"
        return (
            "You are a workflow gate decision agent for API test scope confirmation.\n"
            "Decide whether the workflow should require an intermediate scope confirmation step "
            "or can go directly to review.\n"
            "Use require_scope_confirmation when the original user request is still broad at target level, "
            "even if an upstream understanding step has already narrowed it down heuristically.\n"
            "Important: if the original request only mentions a target-like token that also appears in an endpoint "
            "path or operation name (for example target 'img' and endpoint '/img'), do NOT treat that as explicit scope.\n"
            "Use direct_to_review only when the user truly and explicitly specifies a function, endpoint, HTTP method, or narrow scope.\n"
            f"Write the reason in {language_name}."
        )

    def _build_entry_gate_human_prompt(
        self,
        *,
        original_request: str,
        selected_target: str,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        understanding_explanation: str | None,
        canonical_command: str | None,
        narrowed_scope_operation_ids: list[str],
        narrowed_scope_group_ids: list[str],
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

    def _build_scope_selection_system_prompt(
        self,
        preferred_language: SupportedLanguage,
    ) -> str:
        language_name = "Vietnamese" if preferred_language == "vi" else "English"
        return (
            "You are an API testing scope selection agent.\n"
            "Interpret the user's message as a scope selection over the provided function groups and operations.\n"
            "Return only valid group_ids and operation_ids from the provided catalog.\n"
            "If the user is still ambiguous, use scope_selection_mode='clarify'.\n"
            f"Write reason and follow_up_question in {language_name}."
        )

    def _build_scope_selection_human_prompt(
        self,
        *,
        original_request: str,
        user_message: str,
        selected_target: str,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
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
        return (
            f"Target: {selected_target}\n"
            f"Original request: {original_request}\n"
            f"Current user message: {user_message}\n"
            f"Scope confirmation history:\n{history_text}\n"
            "Available groups:\n"
            + "\n".join(group_lines)
            + "\nAvailable operations:\n"
            + "\n".join(operation_lines)
        )

    def _build_recommendation_system_prompt(
        self,
        preferred_language: SupportedLanguage,
    ) -> str:
        language_name = "Vietnamese" if preferred_language == "vi" else "English"
        return (
            "You are a recommendation agent for API testing scope confirmation.\n"
            "Recommend which groups should be tested first, or which groups should not be tested first.\n"
            "Prefer smoke-test friendly groups first: health, ping, simple, search, common core read endpoints.\n"
            "Deprioritize beta, NFT, treasury, derivative, and niche groups unless the user specifically asks for them.\n"
            "Return only valid group_ids.\n"
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
        group_lines: list[str] = []
        operation_lookup = {
            item.operation_id: item for item in scope_catalog_operations
        }
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
        value: str,
    ) -> ScopeSelectionMode | None:
        lowered = str(value).strip().lower()
        for item in ScopeSelectionMode:
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

    def _has_explicit_endpoint_scope(self, text: str) -> bool:
        lowered = text.strip().lower()
        if "/" in text:
            return True
        if re.search(r"\b(get|post|put|patch|delete)\b", lowered):
            return True
        explicit_tokens = ["endpoint", "operation", "operation_id", "path "]
        normalized = self._normalize(text)
        return any(token in lowered or token in normalized for token in explicit_tokens)

    def _looks_like_general_target_request(
        self,
        *,
        normalized_request: str,
        selected_target: str,
    ) -> bool:
        request_tokens = set(self._tokenize(normalized_request))
        target_tokens = self._target_tokens(selected_target)

        generic_markers = {"test", "target", "hay", "kiem", "thu", "tra", "run", "start"}
        semantic_request_tokens = {
            token for token in request_tokens if token not in generic_markers
        }

        if not semantic_request_tokens:
            return True

        if semantic_request_tokens.issubset(target_tokens):
            return True

        return False

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

        collision_tokens = request_tokens.intersection(target_tokens).intersection(operation_tokens)
        return bool(collision_tokens)

    def _looks_like_exclusion_request(self, normalized_message: str) -> bool:
        tokens = ["bo nhom", "skip", "excluding", "tru ", "exclude"]
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
        if 1 <= operation_count <= 4:
            score += 1.0
        elif operation_count >= 8:
            score -= 0.5

        matching_operations = [
            item
            for item in scope_catalog_operations
            if item.operation_id in set(group.operation_ids)
        ]
        get_ratio_bonus = sum(
            1 for item in matching_operations if item.method.upper() == "GET"
        ) * 0.1
        score += min(get_ratio_bonus, 1.0)

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

    def _default_recommendation_followup(
        self,
        preferred_language: SupportedLanguage,
    ) -> str:
        return self._localize(
            preferred_language,
            "Bạn có thể nói: `test các nhóm được gợi ý`, `bỏ các nhóm này`, hoặc `xem chi tiết một nhóm cụ thể`.",
            "You can say: `test the recommended groups`, `exclude these groups`, or `show details for a specific group`.",
        )

    def _localize(
        self,
        preferred_language: SupportedLanguage,
        vi_text: str,
        en_text: str,
    ) -> str:
        return en_text if preferred_language == "en" else vi_text