from __future__ import annotations

from typing import Any, Iterable, cast

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from api_testing_agent.logging_config import bind_logger, get_logger
from api_testing_agent.tasks.ai_router_models import AIIntentClassification
from api_testing_agent.tasks.workflow_models import WorkflowContextSnapshot, WorkflowPhase


class AIIntentAgent:
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
                AIIntentClassification
            )
            self._enabled = True
            self._logger.info(
                "Initialized AIIntentAgent.",
                extra={"payload_source": "ai_intent_agent_init"},
            )
        except Exception as exc:
            self._logger.warning(
                f"AIIntentAgent disabled and will fall back to deterministic routing: {exc}",
                extra={"payload_source": "ai_intent_agent_init_failed"},
            )
            self._structured_model = None
            self._enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled and self._structured_model is not None

    def classify(
        self,
        *,
        message: str,
        snapshot: WorkflowContextSnapshot | None,
    ) -> AIIntentClassification | None:
        model = self._structured_model
        if not self._enabled or model is None:
            return None

        logger = bind_logger(
            self._logger,
            thread_id=snapshot.thread_id if snapshot else "-",
            target_name=str(snapshot.selected_target if snapshot else "-"),
            payload_source="ai_intent_agent_classify",
        )
        logger.info("Classifying natural-language intent with LLM.")

        try:
            system_prompt = self._build_system_prompt(snapshot)
            human_prompt = self._build_human_prompt(
                message=message,
                snapshot=snapshot,
            )

            raw_result: object = model.invoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=human_prompt),
                ]
            )

            result = self._coerce_result(raw_result)

            logger.info(
                f"AI intent classified as {result.intent} with confidence={result.confidence:.2f}.",
            )
            return result

        except Exception as exc:
            logger.warning(
                f"AI intent classification failed. Falling back to deterministic router: {exc}",
                extra={"payload_source": "ai_intent_agent_classify_failed"},
            )
            return None

    def _coerce_result(self, raw_result: object) -> AIIntentClassification:
        if isinstance(raw_result, AIIntentClassification):
            return raw_result

        if isinstance(raw_result, dict):
            return AIIntentClassification.model_validate(raw_result)

        if isinstance(raw_result, BaseModel):
            dumped = cast(dict[str, object], raw_result.model_dump())
            return AIIntentClassification.model_validate(dumped)

        raise TypeError(f"Unsupported structured output type: {type(raw_result)!r}")

    def _build_system_prompt(
        self,
        snapshot: WorkflowContextSnapshot | None,
    ) -> str:
        phase = snapshot.phase.value if snapshot else "idle"
        allowed_intents = ", ".join(
            self._allowed_intents_for_phase(snapshot.phase if snapshot else None)
        )

        return (
            "You are an intent classifier for a stateful REST API testing assistant.\n"
            "Return exactly one intent in structured form.\n"
            "Prefer the user's actual meaning, not surface keywords only.\n"
            "Do not invent new intents.\n"
            "Always fill followup_reference and scope_followup_kind.\n"
            "Use followup_reference='latest_scope_recommendation' when the user refers to a previous recommendation such as "
            "'do that', 'apply that suggestion', 'follow your recommendation', or equivalent.\n"
            "Use scope_followup_kind='accept_recommendation' when the user wants to apply a previous recommendation.\n"
            "Use scope_followup_kind='reject_recommendation' when the user wants to avoid or discard a previous recommendation.\n"
            "Use scope_followup_kind='refine_recommendation' when the user wants to tweak a previous recommendation.\n"
            "Use scope_followup_kind='apply_previous_selection' when the user refers to a previously agreed scope selection.\n"
            f"Current phase: {phase}\n"
            f"Allowed intents in this phase: {allowed_intents}\n\n"
            "Intent semantics:\n"
            "- show_scope_catalog: user asks what groups/functions/operations are available during scope confirmation.\n"
            "- show_scope_group_details: user asks to inspect one function group in more detail.\n"
            "- show_scope_operation_details: user asks to inspect one specific operation/endpoint in more detail.\n"
            "- ask_scope_recommendation: user asks which groups/functions should be tested first or should not be tested first.\n"
            "- apply_scope_recommendation: user wants to apply a previous recommendation or says to follow the suggestion.\n"
            "- resume_scope_confirmation: user refines scope, chooses all/subset/group/range, excludes part of the scope, or says fuzzy things like 'just the basic ones'.\n"
            "- show_review_scope: user asks what functions/scope/operations are currently available during pending_review.\n"
            "- resume_review: user wants to revise or continue testcase drafting during pending_review.\n"
            "- continue_report_interaction: user asks about report, wants rewrite/summary/share/explanation after report exists.\n"
            "- start_new_workflow: user clearly wants a new unrelated test task.\n"
            "- help: asks what the system can do.\n"
            "- status: asks current phase/status/progress.\n"
            "- clarify: user message is too ambiguous.\n\n"
            "Important:\n"
            "- Hard commands like numbers, local/staging/prod, approve/cancel/done are already handled before you.\n"
            "- In pending_scope_confirmation, prefer scope-related intents over start_new_workflow unless the user clearly changes topic.\n"
            "- If the user asks what capabilities/functions/groups the current target has during scope confirmation, choose show_scope_catalog.\n"
            "- If the user asks about one group such as 'show me the Coins group', choose show_scope_group_details.\n"
            "- If the user asks about one endpoint such as 'what does GET /coins/{id} do', choose show_scope_operation_details.\n"
            "- If the user asks which groups should be tested first, choose ask_scope_recommendation.\n"
            "- If the user says things like 'apply that recommendation', 'do what you suggested', 'follow your suggestion', "
            "or 'thực hiện theo gợi ý đi', choose apply_scope_recommendation.\n"
            "- If the user says fuzzy scope selections like 'just the basic ones', 'skip NFT', or 'coin market only', choose resume_scope_confirmation.\n"
            "- If the user is in report_interaction and starts a clearly new test topic, choose start_new_workflow.\n"
        )

    def _build_human_prompt(
        self,
        *,
        message: str,
        snapshot: WorkflowContextSnapshot | None,
    ) -> str:
        if snapshot is None:
            return f"User message: {message}"

        preview = (snapshot.current_markdown or "").strip()
        if len(preview) > 1200:
            preview = preview[:1200] + "\n...[truncated]"

        scope_groups = [
            {
                "group_id": item.group_id,
                "title": item.title,
                "description": item.description,
                "operation_ids": list(item.operation_ids),
            }
            for item in snapshot.scope_catalog_groups[:12]
        ]
        scope_operations = [
            {
                "operation_id": item.operation_id,
                "method": item.method,
                "path": item.path,
                "group_title": item.group_title,
                "summary": item.summary,
                "description": item.description,
            }
            for item in snapshot.scope_catalog_operations[:20]
        ]

        latest_scope_recommendation = {
            "mode": snapshot.latest_scope_recommendation.mode.value
            if snapshot.latest_scope_recommendation.mode is not None
            else None,
            "group_ids": list(snapshot.latest_scope_recommendation.group_ids),
            "operation_ids": list(snapshot.latest_scope_recommendation.operation_ids),
            "rationale": snapshot.latest_scope_recommendation.rationale,
            "follow_up_question": snapshot.latest_scope_recommendation.follow_up_question,
            "source_user_message": snapshot.latest_scope_recommendation.source_user_message,
            "rendered_message": snapshot.latest_scope_recommendation.rendered_message,
        }

        applied_scope_recommendation = {
            "mode": snapshot.applied_scope_recommendation.mode.value
            if snapshot.applied_scope_recommendation.mode is not None
            else None,
            "group_ids": list(snapshot.applied_scope_recommendation.group_ids),
            "operation_ids": list(snapshot.applied_scope_recommendation.operation_ids),
            "rationale": snapshot.applied_scope_recommendation.rationale,
            "follow_up_question": snapshot.applied_scope_recommendation.follow_up_question,
            "source_user_message": snapshot.applied_scope_recommendation.source_user_message,
            "rendered_message": snapshot.applied_scope_recommendation.rendered_message,
        }

        return (
            f"User message: {message}\n"
            f"Preferred language: {snapshot.preferred_language}\n"
            f"Current phase: {snapshot.phase.value}\n"
            f"Selected target: {snapshot.selected_target or '-'}\n"
            f"Canonical command: {snapshot.canonical_command or '-'}\n"
            f"Understanding: {snapshot.understanding_explanation or '-'}\n"
            f"Scope confirmation question: {snapshot.scope_confirmation_question or '-'}\n"
            f"Scope confirmation summary: {snapshot.scope_confirmation_summary or '-'}\n"
            f"Selected scope groups: {snapshot.selected_scope_group_ids}\n"
            f"Selected scope operations: {snapshot.selected_scope_operation_ids}\n"
            f"Excluded scope groups: {snapshot.excluded_scope_group_ids}\n"
            f"Excluded scope operations: {snapshot.excluded_scope_operation_ids}\n"
            f"Scope confirmation history: {snapshot.scope_confirmation_history}\n"
            f"Latest scope recommendation: {latest_scope_recommendation}\n"
            f"Applied scope recommendation: {applied_scope_recommendation}\n"
            f"Latest scope selection source: {snapshot.latest_scope_selection_source or '-'}\n"
            f"Latest scope agent action: {snapshot.latest_scope_agent_action or '-'}\n"
            f"Latest scope agent reason: {snapshot.latest_scope_agent_reason or '-'}\n"
            f"Last scope user message: {snapshot.last_scope_user_message or '-'}\n"
            f"Review feedback history: {snapshot.review_feedback_history}\n"
            f"Available scope groups: {scope_groups}\n"
            f"Available scope operations: {scope_operations}\n"
            f"Current preview/report excerpt:\n{preview or '-'}"
        )

    def _allowed_intents_for_phase(
        self,
        phase: WorkflowPhase | None,
    ) -> Iterable[str]:
        if phase == WorkflowPhase.PENDING_SCOPE_CONFIRMATION:
            return [
                "show_scope_catalog",
                "show_scope_group_details",
                "show_scope_operation_details",
                "ask_scope_recommendation",
                "apply_scope_recommendation",
                "resume_scope_confirmation",
                "start_new_workflow",
                "help",
                "status",
                "clarify",
            ]

        if phase == WorkflowPhase.PENDING_REVIEW:
            return [
                "show_review_scope",
                "resume_review",
                "start_new_workflow",
                "help",
                "status",
                "clarify",
            ]

        if phase in {
            WorkflowPhase.REPORT_INTERACTION,
            WorkflowPhase.FINAL_REPORT_STAGED,
            WorkflowPhase.RERUN_REQUESTED,
        }:
            return [
                "continue_report_interaction",
                "start_new_workflow",
                "help",
                "status",
                "clarify",
            ]

        return [
            "help",
            "status",
            "clarify",
        ]