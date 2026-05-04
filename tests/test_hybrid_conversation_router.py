from typing import cast
from api_testing_agent.tasks.language_support import SupportedLanguage
from typing import cast

from api_testing_agent.tasks.ai_intent_agent import AIIntentAgent
from api_testing_agent.tasks.ai_router_models import AIIntentClassification
from api_testing_agent.tasks.hybrid_conversation_router import HybridConversationRouter
from api_testing_agent.tasks.workflow_language_policy import WorkflowLanguagePolicy
from api_testing_agent.tasks.workflow_models import (
    RouterIntent,
    WorkflowArtifactRefs,
    WorkflowContextSnapshot,
    WorkflowPhase,
    WorkflowScopeCatalogGroup,
    WorkflowScopeCatalogOperation,
)


class FakeAIIntentAgent:
    def __init__(self, mapping: dict[str, AIIntentClassification]) -> None:
        self._mapping = mapping
        self.is_enabled = True

    def classify(
        self,
        *,
        message: str,
        snapshot: WorkflowContextSnapshot | None,
    ) -> AIIntentClassification | None:
        return self._mapping.get(message)


def build_snapshot(
    phase: WorkflowPhase,
    *,
    preferred_language: SupportedLanguage = "vi",
) -> WorkflowContextSnapshot:
    return WorkflowContextSnapshot(
        workflow_id="wf-1",
        thread_id="thread-1",
        phase=phase,
        original_user_text="test img staging",
        selected_target="img_api_staging",
        current_markdown="Preview draft here",
        canonical_command="test target img_api_staging /img POST",
        understanding_explanation="Matched POST /img",
        preferred_language=preferred_language,
    )


def test_hybrid_router_uses_ai_for_freeform_review_scope_question():
    message = "target này làm được gì vậy"
    ai_agent = FakeAIIntentAgent(
        {
            message: AIIntentClassification(
                intent="show_review_scope",
                confidence=0.93,
                rationale="The user is asking about the available capabilities of the current target.",
            )
        }
    )
    router = HybridConversationRouter(
        ai_intent_agent=cast(AIIntentAgent, ai_agent)
    )

    decision = router.route(
        message=message,
        snapshot=build_snapshot(WorkflowPhase.PENDING_REVIEW),
    )

    assert decision.intent == RouterIntent.SHOW_REVIEW_SCOPE


def test_hybrid_router_clarifies_new_task_during_report_interaction():
    message = "please test login on staging"
    ai_agent = FakeAIIntentAgent(
        {
            message: AIIntentClassification(
                intent="start_new_workflow",
                confidence=0.91,
                rationale="The user is clearly starting a new test task unrelated to the current report.",
            )
        }
    )
    router = HybridConversationRouter(
        ai_intent_agent=cast(AIIntentAgent, ai_agent)
    )

    decision = router.route(
        message=message,
        snapshot=build_snapshot(
            WorkflowPhase.REPORT_INTERACTION,
            preferred_language="en",
        ),
    )

    assert decision.intent == RouterIntent.CLARIFY
    assert decision.clarification_question is not None
    assert "start a new test workflow" in decision.clarification_question.lower()


def test_hybrid_router_falls_back_to_deterministic_when_ai_is_missing():
    router = HybridConversationRouter(ai_intent_agent=None)

    decision = router.route(
        message="help",
        snapshot=build_snapshot(WorkflowPhase.PENDING_REVIEW),
    )

    assert decision.intent == RouterIntent.HELP

from typing import cast

from api_testing_agent.tasks.ai_intent_agent import AIIntentAgent
from api_testing_agent.tasks.ai_router_models import AIIntentClassification
from api_testing_agent.tasks.hybrid_conversation_router import HybridConversationRouter
from api_testing_agent.tasks.workflow_language_policy import WorkflowLanguagePolicy
from api_testing_agent.tasks.workflow_models import (
    RouterIntent,
    WorkflowArtifactRefs,
    WorkflowContextSnapshot,
    WorkflowPhase,
    WorkflowScopeCatalogGroup,
    WorkflowScopeCatalogOperation,
)

def build_scope_snapshot() -> WorkflowContextSnapshot:
    return WorkflowContextSnapshot(
        workflow_id="wf-scope",
        thread_id="thread-scope",
        phase=WorkflowPhase.PENDING_SCOPE_CONFIRMATION,
        original_user_text="test target coingecko đi",
        selected_target="coingecko_demo",
        preferred_language="vi",
        language_policy=WorkflowLanguagePolicy.ADAPTIVE,
        scope_confirmation_question="Bạn muốn test toàn bộ, theo nhóm, hay theo operation?",
        scope_confirmation_summary="Target có nhiều nhóm chức năng.",
        scope_catalog_groups=[
            WorkflowScopeCatalogGroup(
                group_id="coins",
                title="Coins",
                description="Coin related APIs",
                operation_ids=["coins_markets", "coins_detail"],
                tags=["coins"],
            ),
            WorkflowScopeCatalogGroup(
                group_id="nfts",
                title="NFTs",
                description="NFT related APIs",
                operation_ids=["nfts_list"],
                tags=["nfts"],
            ),
        ],
        scope_catalog_operations=[
            WorkflowScopeCatalogOperation(
                operation_id="coins_markets",
                method="GET",
                path="/coins/markets",
                group_id="coins",
                group_title="Coins",
                summary="Coin markets",
                description="Get coin markets",
                tags=["coins"],
                auth_required=False,
            ),
            WorkflowScopeCatalogOperation(
                operation_id="coins_detail",
                method="GET",
                path="/coins/{id}",
                group_id="coins",
                group_title="Coins",
                summary="Coin detail",
                description="Get coin detail",
                tags=["coins"],
                auth_required=False,
            ),
            WorkflowScopeCatalogOperation(
                operation_id="nfts_list",
                method="GET",
                path="/nfts/list",
                group_id="nfts",
                group_title="NFTs",
                summary="NFT list",
                description="Get NFT list",
                tags=["nfts"],
                auth_required=False,
            ),
        ],
        artifacts=WorkflowArtifactRefs(),
    )


def test_hybrid_router_uses_ai_for_fuzzy_scope_confirmation():
    message = "mấy cái cơ bản thôi"
    ai_agent = FakeAIIntentAgent(
        {
            message: AIIntentClassification(
                intent="resume_scope_confirmation",
                confidence=0.92,
                rationale="The user is refining the test scope in a fuzzy way.",
            )
        }
    )
    router = HybridConversationRouter(
        ai_intent_agent=cast(AIIntentAgent, ai_agent)
    )

    decision = router.route(
        message=message,
        snapshot=build_scope_snapshot(),
    )

    assert decision.intent == RouterIntent.RESUME_SCOPE_CONFIRMATION


def test_hybrid_router_uses_ai_for_scope_group_details():
    message = "cho tôi xem kỹ nhóm coin market"
    ai_agent = FakeAIIntentAgent(
        {
            message: AIIntentClassification(
                intent="show_scope_group_details",
                confidence=0.88,
                rationale="The user wants details for a function group.",
            )
        }
    )
    router = HybridConversationRouter(
        ai_intent_agent=cast(AIIntentAgent, ai_agent)
    )

    decision = router.route(
        message=message,
        snapshot=build_scope_snapshot(),
    )

    assert decision.intent == RouterIntent.SHOW_SCOPE_GROUP_DETAILS


def test_hybrid_router_uses_ai_for_scope_recommendation():
    message = "nhóm nào nên test trước"
    ai_agent = FakeAIIntentAgent(
        {
            message: AIIntentClassification(
                intent="ask_scope_recommendation",
                confidence=0.9,
                rationale="The user is asking for a suggested starting subset.",
            )
        }
    )
    router = HybridConversationRouter(
        ai_intent_agent=cast(AIIntentAgent, ai_agent)
    )

    decision = router.route(
        message=message,
        snapshot=build_scope_snapshot(),
    )

    assert decision.intent == RouterIntent.ASK_SCOPE_RECOMMENDATION