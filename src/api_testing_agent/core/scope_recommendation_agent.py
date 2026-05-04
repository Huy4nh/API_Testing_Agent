from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from api_testing_agent.logging_config import bind_logger, get_logger
from api_testing_agent.tasks.language_support import SupportedLanguage
from api_testing_agent.tasks.workflow_models import (
    WorkflowScopeCatalogGroup,
    WorkflowScopeCatalogOperation,
)


RecommendationMode = Literal["prioritize", "deprioritize"]


@dataclass(frozen=True)
class ScopeRecommendationResult:
    mode: RecommendationMode
    recommended_group_ids: list[str] = field(default_factory=list)
    deprioritized_group_ids: list[str] = field(default_factory=list)
    rationale: str = ""
    follow_up_suggestion: str | None = None


class _AIScopeRecommendationPayload(BaseModel):
    mode: RecommendationMode = Field(
        description="Use 'prioritize' when recommending what to test first, or 'deprioritize' when recommending what not to test first."
    )
    recommended_group_ids: list[str] = Field(
        default_factory=list,
        description="Ordered list of group_ids that should be tested first. Only use group_ids from the provided catalog.",
    )
    deprioritized_group_ids: list[str] = Field(
        default_factory=list,
        description="Ordered list of group_ids that should be tested later / not first. Only use group_ids from the provided catalog.",
    )
    rationale: str = Field(
        default="",
        description="Short explanation grounded in the catalog and the user message.",
    )
    follow_up_suggestion: str | None = Field(
        default=None,
        description="A short next-step suggestion in the user's language.",
    )


class ScopeRecommendationAgent:
    def __init__(
        self,
        *,
        model_name: str,
        model_provider: str | None = None,
    ) -> None:
        self._logger = get_logger(__name__)
        self._model_name = model_name.strip()
        self._model_provider = (model_provider or "").strip() or None
        self._structured_model: Any | None = None
        self._enabled = False

        try:
            base_model = init_chat_model(
                model=self._model_name,
                model_provider=self._model_provider,
                temperature=0,
            )
            self._structured_model = base_model.with_structured_output(
                _AIScopeRecommendationPayload
            )
            self._enabled = True
            self._logger.info(
                "Initialized ScopeRecommendationAgent.",
                extra={"payload_source": "scope_recommendation_agent_init"},
            )
        except Exception as exc:
            self._logger.warning(
                f"ScopeRecommendationAgent disabled and will fall back to heuristics: {exc}",
                extra={"payload_source": "scope_recommendation_agent_init_failed"},
            )
            self._structured_model: Any | None = None
            self._enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled and self._structured_model is not None

    def recommend(
        self,
        *,
        user_message: str,
        target_name: str,
        original_request: str | None,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        scope_confirmation_history: list[str] | None = None,
    ) -> ScopeRecommendationResult:
        logger = bind_logger(
            self._logger,
            target_name=target_name,
            payload_source="scope_recommendation_agent_recommend",
        )
        logger.info("Generating scope recommendation.")

        if not scope_catalog_groups:
            return ScopeRecommendationResult(
                mode=self._infer_mode(user_message),
                rationale=self._localize(
                    preferred_language,
                    "Hiện chưa có nhóm chức năng nào để gợi ý.",
                    "There are no function groups available to recommend yet.",
                ),
                follow_up_suggestion=self._localize(
                    preferred_language,
                    "Bạn hãy yêu cầu xem lại catalog trước.",
                    "Ask to view the catalog first.",
                ),
            )

        model = self._structured_model
        if not self._enabled or model is None:
            return self._heuristic_recommend(
                user_message=user_message,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
            )

        try:
            system_prompt = self._build_system_prompt(preferred_language)
            human_prompt = self._build_human_prompt(
                user_message=user_message,
                target_name=target_name,
                original_request=original_request,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
                scope_confirmation_history=scope_confirmation_history or [],
            )

            raw_result = model.invoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=human_prompt),
                ]
            )
            payload = self._coerce_payload(raw_result)

            valid_group_ids = {
                str(item.group_id).strip() for item in scope_catalog_groups if item.group_id
            }

            recommended_group_ids = [
                item for item in payload.recommended_group_ids if item in valid_group_ids
            ]
            deprioritized_group_ids = [
                item for item in payload.deprioritized_group_ids if item in valid_group_ids
            ]

            if (
                not recommended_group_ids
                and not deprioritized_group_ids
            ):
                return self._heuristic_recommend(
                    user_message=user_message,
                    preferred_language=preferred_language,
                    scope_catalog_groups=scope_catalog_groups,
                    scope_catalog_operations=scope_catalog_operations,
                )

            return ScopeRecommendationResult(
                mode=payload.mode,
                recommended_group_ids=recommended_group_ids,
                deprioritized_group_ids=deprioritized_group_ids,
                rationale=payload.rationale.strip(),
                follow_up_suggestion=payload.follow_up_suggestion,
            )

        except Exception as exc:
            logger.warning(
                f"Scope recommendation AI failed. Falling back to heuristics: {exc}",
                extra={"payload_source": "scope_recommendation_agent_recommend_failed"},
            )
            return self._heuristic_recommend(
                user_message=user_message,
                preferred_language=preferred_language,
                scope_catalog_groups=scope_catalog_groups,
                scope_catalog_operations=scope_catalog_operations,
            )

    def _coerce_payload(self, raw_result: object) -> _AIScopeRecommendationPayload:
        if isinstance(raw_result, _AIScopeRecommendationPayload):
            return raw_result

        if isinstance(raw_result, dict):
            return _AIScopeRecommendationPayload.model_validate(raw_result)

        if isinstance(raw_result, BaseModel):
            return _AIScopeRecommendationPayload.model_validate(raw_result.model_dump())

        raise TypeError(f"Unsupported structured output type: {type(raw_result)!r}")

    def _build_system_prompt(self, preferred_language: SupportedLanguage) -> str:
        language_name = "Vietnamese" if preferred_language == "vi" else "English"
        return (
            "You are a scope recommendation agent for API testing.\n"
            "Your job is to recommend which FUNCTION GROUPS should be tested first, "
            "or which groups should NOT be tested first, based on the user's wording "
            "and the provided target catalog.\n"
            "Return only valid group_ids from the catalog.\n"
            "Do not invent group_ids.\n"
            "Prefer core smoke-test groups first: health, ping, simple, search, main entity lookup, "
            "core read endpoints, and commonly-used public endpoints.\n"
            "Deprioritize niche, beta, treasury, derivative, or auxiliary groups unless the user clearly wants them.\n"
            "If the user asks a negative question such as 'which group should NOT be tested first', "
            "use mode='deprioritize'. Otherwise use mode='prioritize'.\n"
            f"Write rationale and follow_up_suggestion in {language_name}."
        )

    def _build_human_prompt(
        self,
        *,
        user_message: str,
        target_name: str,
        original_request: str | None,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
        scope_confirmation_history: list[str],
    ) -> str:
        group_operation_lookup: dict[str, list[str]] = {}
        for group in scope_catalog_groups:
            previews: list[str] = []
            for operation_id in group.operation_ids[:4]:
                operation = next(
                    (
                        item
                        for item in scope_catalog_operations
                        if item.operation_id == operation_id
                    ),
                    None,
                )
                if operation is not None:
                    previews.append(f"{operation.method} {operation.path}")
                else:
                    previews.append(operation_id)
            group_operation_lookup[group.group_id] = previews

        group_lines: list[str] = []
        for group in scope_catalog_groups:
            group_lines.append(
                f"- group_id={group.group_id}; "
                f"title={group.title}; "
                f"description={group.description or '-'}; "
                f"operations={group_operation_lookup.get(group.group_id, [])}"
            )

        history_text = "\n".join(f"- {item}" for item in scope_confirmation_history[-10:]) or "-"

        return (
            f"Target: {target_name}\n"
            f"Original user request: {original_request or '-'}\n"
            f"Current user message: {user_message}\n"
            f"Scope confirmation history:\n{history_text}\n"
            "Available function groups:\n"
            + "\n".join(group_lines)
        )

    def _heuristic_recommend(
        self,
        *,
        user_message: str,
        preferred_language: SupportedLanguage,
        scope_catalog_groups: list[WorkflowScopeCatalogGroup],
        scope_catalog_operations: list[WorkflowScopeCatalogOperation],
    ) -> ScopeRecommendationResult:
        mode = self._infer_mode(user_message)

        scored: list[tuple[float, WorkflowScopeCatalogGroup]] = []
        for group in scope_catalog_groups:
            score = self._score_group_for_recommendation(
                group=group,
                scope_catalog_operations=scope_catalog_operations,
            )
            scored.append((score, group))

        scored.sort(key=lambda item: item[0], reverse=True)

        if mode == "prioritize":
            recommended = [group.group_id for _, group in scored[:3]]
            return ScopeRecommendationResult(
                mode="prioritize",
                recommended_group_ids=recommended,
                rationale=self._localize(
                    preferred_language,
                    "Ưu tiên các nhóm có tính smoke-test cao, dùng nhiều, và dễ xác minh trước.",
                    "Prioritize groups that are good smoke-test candidates, commonly used, and easy to validate first.",
                ),
                follow_up_suggestion=self._localize(
                    preferred_language,
                    "Bạn có thể nói: `test các nhóm được gợi ý`, hoặc `xem chi tiết nhóm Coins`.",
                    "You can say: `test the recommended groups`, or `show details for the Coins group`.",
                ),
            )

        deprioritized = [group.group_id for _, group in sorted(scored, key=lambda item: item[0])[:3]]
        return ScopeRecommendationResult(
            mode="deprioritize",
            deprioritized_group_ids=deprioritized,
            rationale=self._localize(
                preferred_language,
                "Các nhóm này nên để sau vì có xu hướng niche hơn, ít phù hợp cho smoke test đầu tiên, hoặc mang tính phụ trợ.",
                "These groups are better left for later because they tend to be more niche, less suitable for an initial smoke test, or more auxiliary.",
            ),
            follow_up_suggestion=self._localize(
                preferred_language,
                "Bạn có thể nói: `bỏ các nhóm này và test phần còn lại`, hoặc `gợi ý tiếp nhóm nào nên test đầu tiên`.",
                "You can say: `exclude these groups and test the rest`, or `recommend which groups should be tested first`.",
            ),
        )

    def _score_group_for_recommendation(
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
        get_ratio_bonus = sum(1 for item in matching_operations if item.method.upper() == "GET") * 0.1
        score += min(get_ratio_bonus, 1.0)

        return score

    def _infer_mode(self, user_message: str) -> RecommendationMode:
        normalized = self._normalize(user_message)
        negative_markers = [
            "khong test truoc",
            "khong nen test truoc",
            "khong nen uu tien",
            "de sau",
            "khong test dau",
            "not test first",
            "should not test first",
            "avoid first",
            "deprioritize",
            "skip first",
        ]
        if any(marker in normalized for marker in negative_markers):
            return "deprioritize"
        return "prioritize"

    def _normalize(self, value: str) -> str:
        lowered = value.strip().lower()
        normalized = unicodedata.normalize("NFD", lowered)
        without_accents = "".join(
            ch for ch in normalized if unicodedata.category(ch) != "Mn"
        )
        return " ".join(without_accents.split()).replace("đ", "d")

    def _localize(
        self,
        preferred_language: SupportedLanguage,
        vi_text: str,
        en_text: str,
    ) -> str:
        return en_text if preferred_language == "en" else vi_text