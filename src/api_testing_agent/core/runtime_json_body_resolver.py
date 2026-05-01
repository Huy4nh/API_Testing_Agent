from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from api_testing_agent.core.runtime_payload_planning_graph import RuntimePayloadPlanningGraph
from api_testing_agent.logging_config import bind_logger, get_logger


@dataclass(frozen=True)
class ResolvedJsonBody:
    value: Any | None
    source: str
    planner_reason: str | None = None
    planner_confidence: float | None = None


class RuntimeJsonBodyResolver:
    def __init__(
        self,
        *,
        planning_graph: RuntimePayloadPlanningGraph | None = None,
    ) -> None:
        self._planning_graph = planning_graph or RuntimePayloadPlanningGraph()
        self._logger = get_logger(__name__)

        self._logger.info(
            "Initialized RuntimeJsonBodyResolver.",
            extra={"payload_source": "runtime_json_body_resolver_init"},
        )

    def resolve(
        self,
        *,
        operation_context: dict[str, Any],
        case: dict[str, Any],
        explicit_json_body: Any,
    ) -> ResolvedJsonBody:
        operation_id = str(operation_context.get("operation_id", "-"))
        logger = bind_logger(
            self._logger,
            operation_id=operation_id,
            payload_source="runtime_json_body_resolve",
        )
        logger.info("Starting JSON body resolution.")

        request_body = operation_context.get("request_body")
        if not isinstance(request_body, dict):
            logger.info("No request_body schema found. Returning explicit payload clone.")
            return ResolvedJsonBody(
                value=self._clone_if_needed(explicit_json_body),
                source="no_request_body_schema",
            )

        content_type = str(request_body.get("content_type", ""))
        if content_type != "application/json":
            logger.info(f"Non-JSON request body detected. content_type={content_type}")
            return ResolvedJsonBody(
                value=self._clone_if_needed(explicit_json_body),
                source="non_json_request_body",
            )

        schema = request_body.get("schema")
        if not isinstance(schema, dict) or not schema:
            logger.info("Missing or empty JSON schema. Returning explicit payload clone.")
            return ResolvedJsonBody(
                value=self._clone_if_needed(explicit_json_body),
                source="missing_json_schema",
            )

        graph_result = self._planning_graph.invoke(
            operation_context=operation_context,
            case=case,
            explicit_json_body=explicit_json_body,
        )

        source = self._build_source_label(graph_result)
        logger.info(
            f"JSON body resolution completed. source={source}, planner_confidence={graph_result.get('planner_confidence')}"
        )

        return ResolvedJsonBody(
            value=graph_result.get("final_payload"),
            source=source,
            planner_reason=graph_result.get("planner_reason"),
            planner_confidence=graph_result.get("planner_confidence"),
        )

    def _build_source_label(self, graph_result: dict[str, Any]) -> str:
        payload_plan = graph_result.get("payload_plan") or {}
        if not isinstance(payload_plan, dict):
            return "unknown"

        mutation_kind = str(payload_plan.get("mutation_kind", "none"))
        trust_explicit = bool(payload_plan.get("trust_explicit_payload", False))
        base_strategy = str(payload_plan.get("base_payload_strategy", "synthesize_from_schema"))
        fields_to_remove = payload_plan.get("fields_to_remove") or []
        field_overrides = payload_plan.get("field_overrides") or {}

        if trust_explicit and base_strategy == "use_explicit":
            return "explicit_payload_final"

        if mutation_kind == "invalid_type_or_format":
            return "mutated_invalid_type_or_format"

        if mutation_kind == "remove_required_field" or fields_to_remove:
            return "mutated_missing_required"

        if mutation_kind == "semantic_positive" or field_overrides:
            return "synthesized_with_semantic_overrides"

        return "synthesized_valid_payload"

    def _clone_if_needed(self, value: Any) -> Any:
        if value is None:
            return None
        return copy.deepcopy(value)