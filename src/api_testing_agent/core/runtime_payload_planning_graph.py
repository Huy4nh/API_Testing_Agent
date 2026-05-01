from __future__ import annotations

import copy
from typing import Any, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from api_testing_agent.core.ai_payload_planner_service import (
    AIPayloadPlannerService,
    PayloadPlannerServiceProtocol,
)
from api_testing_agent.core.payload_plan_models import PayloadPlan
from api_testing_agent.core.runtime_payload_mutator import RuntimePayloadMutator
from api_testing_agent.core.schema_faker import SchemaFaker
from api_testing_agent.logging_config import bind_logger, get_logger


class RuntimePayloadPlanningState(TypedDict):
    operation_context: dict[str, Any]
    case: dict[str, Any]
    explicit_json_body: Any

    payload_plan: NotRequired[dict[str, Any]]
    base_payload: NotRequired[Any]
    final_payload: NotRequired[Any]
    planner_reason: NotRequired[str]
    planner_confidence: NotRequired[float | None]


class RuntimePayloadPlanningGraph:
    def __init__(
        self,
        *,
        planner_service: PayloadPlannerServiceProtocol | None = None,
        schema_faker: SchemaFaker | None = None,
        payload_mutator: RuntimePayloadMutator | None = None,
    ) -> None:
        self._planner_service: PayloadPlannerServiceProtocol = planner_service or AIPayloadPlannerService()
        self._schema_faker = schema_faker or SchemaFaker()
        self._payload_mutator = payload_mutator or RuntimePayloadMutator()
        self._logger = get_logger(__name__)
        self._graph = self._compile_graph()

        self._logger.info(
            "Initialized RuntimePayloadPlanningGraph.",
            extra={"payload_source": "runtime_payload_planning_graph_init"},
        )

    def invoke(
        self,
        *,
        operation_context: dict[str, Any],
        case: dict[str, Any],
        explicit_json_body: Any,
    ) -> dict[str, Any]:
        operation_id = str(operation_context.get("operation_id", "-"))
        logger = bind_logger(
            self._logger,
            operation_id=operation_id,
            payload_source="runtime_payload_planning_invoke",
        )
        logger.info("Invoking runtime payload planning graph.")

        result = self._graph.invoke(
            {
                "operation_context": operation_context,
                "case": case,
                "explicit_json_body": explicit_json_body,
            }
        )

        logger.info("Runtime payload planning graph invocation completed.")
        return result

    def _compile_graph(self):
        builder = StateGraph(RuntimePayloadPlanningState)

        builder.add_node("plan_payload", self._plan_payload_node)
        builder.add_node("build_base_payload", self._build_base_payload_node)
        builder.add_node("apply_payload_plan", self._apply_payload_plan_node)

        builder.add_edge(START, "plan_payload")
        builder.add_edge("plan_payload", "build_base_payload")
        builder.add_edge("build_base_payload", "apply_payload_plan")
        builder.add_edge("apply_payload_plan", END)

        self._logger.info(
            "Compiled RuntimePayloadPlanningGraph.",
            extra={"payload_source": "runtime_payload_planning_compile"},
        )

        return builder.compile()

    def _plan_payload_node(self, state: RuntimePayloadPlanningState) -> dict[str, Any]:
        operation_id = str(state["operation_context"].get("operation_id", "-"))
        logger = bind_logger(
            self._logger,
            operation_id=operation_id,
            payload_source="runtime_payload_plan_node",
        )
        logger.info("Planning payload node started.")

        plan = self._planner_service.plan(
            operation_context=state["operation_context"],
            case=state["case"],
            explicit_json_body=state["explicit_json_body"],
        )

        logger.info(
            f"Payload plan generated. mutation_kind={plan.mutation_kind}, target_field={plan.target_field}, confidence={plan.confidence}"
        )

        return {
            "payload_plan": plan.model_dump(),
            "planner_reason": plan.reason,
            "planner_confidence": plan.confidence,
        }

    def _build_base_payload_node(self, state: RuntimePayloadPlanningState) -> dict[str, Any]:
        operation_context = state["operation_context"]
        explicit_json_body = state["explicit_json_body"]
        operation_id = str(operation_context.get("operation_id", "-"))
        logger = bind_logger(
            self._logger,
            operation_id=operation_id,
            payload_source="runtime_payload_build_base_node",
        )
        logger.info("Building base payload node started.")

        payload_plan_data = state.get("payload_plan")
        if not isinstance(payload_plan_data, dict):
            logger.error("payload_plan is missing before build_base_payload")
            raise ValueError("payload_plan is missing before build_base_payload")

        payload_plan = PayloadPlan.model_validate(payload_plan_data)
        schema = self._extract_schema(operation_context)

        if (
            payload_plan.base_payload_strategy == "use_explicit"
            and payload_plan.trust_explicit_payload
            and explicit_json_body is not None
        ):
            logger.info("Using explicit_json_body as base payload.")
            return {
                "base_payload": copy.deepcopy(explicit_json_body),
            }

        base_payload = self._schema_faker.example_for_schema(schema)
        logger.info("Synthesized base payload from schema.")
        return {
            "base_payload": base_payload,
        }

    def _apply_payload_plan_node(self, state: RuntimePayloadPlanningState) -> dict[str, Any]:
        operation_context = state["operation_context"]
        operation_id = str(operation_context.get("operation_id", "-"))
        logger = bind_logger(
            self._logger,
            operation_id=operation_id,
            payload_source="runtime_payload_apply_plan_node",
        )
        logger.info("Applying payload plan node started.")

        payload_plan_data = state.get("payload_plan")
        if not isinstance(payload_plan_data, dict):
            logger.error("payload_plan is missing before apply_payload_plan")
            raise ValueError("payload_plan is missing before apply_payload_plan")

        if "base_payload" not in state:
            logger.error("base_payload is missing before apply_payload_plan")
            raise ValueError("base_payload is missing before apply_payload_plan")

        payload_plan = PayloadPlan.model_validate(payload_plan_data)
        base_payload = state["base_payload"]
        explicit_json_body = state["explicit_json_body"]
        schema = self._extract_schema(operation_context)

        if (
            payload_plan.trust_explicit_payload
            and explicit_json_body is not None
            and not self._is_empty_object(explicit_json_body)
        ):
            working_payload = copy.deepcopy(explicit_json_body)
            logger.info("Using trusted explicit payload as working payload.")
        else:
            working_payload = copy.deepcopy(base_payload)
            logger.info("Using synthesized base payload as working payload.")

        remove_fields = list(payload_plan.fields_to_remove)

        if (
            not remove_fields
            and payload_plan.mutation_kind == "remove_required_field"
            and payload_plan.target_field
        ):
            remove_fields = [payload_plan.target_field]

        if remove_fields:
            logger.info(f"Removing fields from working payload. remove_count={len(remove_fields)}")
            working_payload = self._payload_mutator.remove_fields(
                base_payload=working_payload,
                fields_to_remove=remove_fields,
            )

        field_overrides = dict(payload_plan.field_overrides)

        if (
            not field_overrides
            and payload_plan.mutation_kind == "invalid_type_or_format"
            and payload_plan.target_field
        ):
            logger.info("Applying fallback invalid field mutation.")
            working_payload = self._payload_mutator.mutate_invalid_field(
                base_payload=working_payload,
                target_field=payload_plan.target_field,
                invalid_value_strategy=payload_plan.invalid_value_strategy,
                schema=schema,
            )
        else:
            if field_overrides:
                logger.info(f"Applying semantic field overrides. override_count={len(field_overrides)}")
                working_payload = self._payload_mutator.apply_field_overrides(
                    base_payload=working_payload,
                    field_overrides=field_overrides,
                )

        logger.info("Payload plan application completed.")
        return {
            "final_payload": working_payload,
        }

    def _extract_schema(self, operation_context: dict[str, Any]) -> dict[str, Any]:
        request_body = operation_context.get("request_body")
        if not isinstance(request_body, dict):
            return {}

        schema = request_body.get("schema")
        return schema if isinstance(schema, dict) else {}

    def _is_empty_object(self, value: Any) -> bool:
        return isinstance(value, dict) and len(value) == 0