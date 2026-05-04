from api_testing_agent.tasks.conversation_router import ConversationRouter
from api_testing_agent.tasks.workflow_language_policy import WorkflowLanguagePolicy
from api_testing_agent.tasks.workflow_models import (
    RouterIntent,
    ScopeSelectionMode,
    WorkflowArtifactRefs,
    WorkflowContextSnapshot,
    WorkflowPhase,
    WorkflowScopeCatalogGroup,
    WorkflowScopeCatalogOperation,
)


def build_scope_snapshot() -> WorkflowContextSnapshot:
    return WorkflowContextSnapshot(
        workflow_id="wf-1",
        thread_id="thread-scope-1",
        phase=WorkflowPhase.PENDING_SCOPE_CONFIRMATION,
        original_user_text="test target coingecko đi",
        selected_target="coingecko_demo",
        preferred_language="vi",
        language_policy=WorkflowLanguagePolicy.ADAPTIVE,
        scope_confirmation_question=(
            "Bạn muốn test toàn bộ, theo nhóm, hay theo một số operation cụ thể?"
        ),
        scope_confirmation_summary=(
            "Target `coingecko_demo` hiện có nhiều nhóm chức năng cần xác nhận scope."
        ),
        scope_selection_mode=None,
        scope_catalog_groups=[
            WorkflowScopeCatalogGroup(
                group_id="coins",
                title="Coins",
                description="Coin lookup and market data",
                operation_ids=["coins_list", "coins_markets", "coins_detail"],
                tags=["coins"],
            ),
            WorkflowScopeCatalogGroup(
                group_id="nfts",
                title="NFTs",
                description="NFT related operations",
                operation_ids=["nfts_list"],
                tags=["nfts"],
            ),
        ],
        scope_catalog_operations=[
            WorkflowScopeCatalogOperation(
                operation_id="coins_list",
                method="GET",
                path="/coins/list",
                group_id="coins",
                group_title="Coins",
                summary="List all coins",
                description="Return all listed coins.",
                tags=["coins"],
                auth_required=False,
            ),
            WorkflowScopeCatalogOperation(
                operation_id="coins_markets",
                method="GET",
                path="/coins/markets",
                group_id="coins",
                group_title="Coins",
                summary="Coin market data",
                description="Return market data for coins.",
                tags=["coins"],
                auth_required=False,
            ),
            WorkflowScopeCatalogOperation(
                operation_id="coins_detail",
                method="GET",
                path="/coins/{id}",
                group_id="coins",
                group_title="Coins",
                summary="Coin details",
                description="Return details for a coin.",
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
                description="Return NFT collection list.",
                tags=["nfts"],
                auth_required=False,
            ),
        ],
        selected_scope_group_ids=[],
        selected_scope_operation_ids=[],
        excluded_scope_group_ids=[],
        excluded_scope_operation_ids=[],
        scope_confirmation_history=[],
        review_feedback_history=[],
        artifacts=WorkflowArtifactRefs(),
    )


def test_router_scope_catalog_request():
    router = ConversationRouter()
    decision = router.route(
        message="có những chức năng nào?",
        snapshot=build_scope_snapshot(),
    )
    assert decision.intent == RouterIntent.SHOW_SCOPE_CATALOG


def test_router_scope_group_detail_request():
    router = ConversationRouter()
    decision = router.route(
        message="xem chi tiết nhóm Coins",
        snapshot=build_scope_snapshot(),
    )
    assert decision.intent == RouterIntent.SHOW_SCOPE_GROUP_DETAILS
    assert decision.metadata.get("group_selector") == "Coins"


def test_router_scope_operation_detail_request():
    router = ConversationRouter()
    decision = router.route(
        message="chi tiết GET /coins/{id}",
        snapshot=build_scope_snapshot(),
    )
    assert decision.intent == RouterIntent.SHOW_SCOPE_OPERATION_DETAILS
    assert "GET /coins/{id}" in str(decision.metadata.get("operation_selector"))


def test_router_scope_recommendation_request():
    router = ConversationRouter()
    decision = router.route(
        message="gợi ý nhóm nên test trước",
        snapshot=build_scope_snapshot(),
    )
    assert decision.intent == RouterIntent.ASK_SCOPE_RECOMMENDATION


def test_router_scope_confirmation_explicit_all():
    router = ConversationRouter()
    decision = router.route(
        message="test hết",
        snapshot=build_scope_snapshot(),
    )
    assert decision.intent == RouterIntent.RESUME_SCOPE_CONFIRMATION


def test_router_scope_confirmation_explicit_range():
    router = ConversationRouter()
    decision = router.route(
        message="chỉ test 1 đến 3",
        snapshot=build_scope_snapshot(),
    )
    assert decision.intent == RouterIntent.RESUME_SCOPE_CONFIRMATION


def test_router_scope_confirmation_explicit_exclusion():
    router = ConversationRouter()
    decision = router.route(
        message="bỏ nhóm NFTs",
        snapshot=build_scope_snapshot(),
    )
    assert decision.intent == RouterIntent.RESUME_SCOPE_CONFIRMATION