from __future__ import annotations

import copy
from typing import Any

from api_testing_agent.logging_config import bind_logger, get_logger


class RuntimePayloadMutator:
    """
    Chỉ làm việc deterministic:
    - remove field
    - override field
    - fallback mutate invalid theo strategy nếu plan chưa có concrete override
    """

    def __init__(self) -> None:
        self._logger = get_logger(__name__)

        self._logger.info(
            "Initialized RuntimePayloadMutator.",
            extra={"payload_source": "runtime_payload_mutator_init"},
        )

    def remove_fields(
        self,
        *,
        base_payload: Any,
        fields_to_remove: list[str],
    ) -> Any:
        logger = bind_logger(
            self._logger,
            payload_source="runtime_payload_remove_fields",
        )
        logger.info(f"Removing fields from payload. remove_count={len(fields_to_remove)}")

        if not isinstance(base_payload, dict):
            logger.info("Base payload is not a dict. Returning original payload.")
            return base_payload

        mutated = copy.deepcopy(base_payload)

        for field_name in fields_to_remove:
            if field_name in mutated:
                mutated.pop(field_name, None)

        logger.info("Field removal completed.")
        return mutated

    def apply_field_overrides(
        self,
        *,
        base_payload: Any,
        field_overrides: dict[str, Any],
    ) -> Any:
        logger = bind_logger(
            self._logger,
            payload_source="runtime_payload_apply_overrides",
        )
        logger.info(f"Applying field overrides. override_count={len(field_overrides)}")

        if not isinstance(base_payload, dict):
            logger.info("Base payload is not a dict. Returning original payload.")
            return base_payload

        mutated = copy.deepcopy(base_payload)

        for field_name, value in field_overrides.items():
            mutated[field_name] = value

        logger.info("Field override application completed.")
        return mutated

    def mutate_invalid_field(
        self,
        *,
        base_payload: Any,
        target_field: str | None,
        invalid_value_strategy: str | None,
        schema: dict[str, Any],
    ) -> Any:
        logger = bind_logger(
            self._logger,
            payload_source="runtime_payload_mutate_invalid_field",
        )
        logger.info(
            f"Mutating invalid field. target_field={target_field}, invalid_value_strategy={invalid_value_strategy}"
        )

        if not isinstance(base_payload, dict):
            logger.info("Base payload is not a dict. Returning original payload.")
            return base_payload

        properties = schema.get("properties") or {}
        if not isinstance(properties, dict):
            logger.info("Schema properties is not a dict. Returning original payload.")
            return base_payload

        mutated = copy.deepcopy(base_payload)

        ordered_fields: list[str] = []
        if target_field and target_field in properties:
            ordered_fields.append(target_field)

        for field_name in properties.keys():
            if field_name not in ordered_fields:
                ordered_fields.append(field_name)

        for field_name in ordered_fields:
            if field_name not in mutated:
                continue

            field_schema = properties.get(field_name)
            if not isinstance(field_schema, dict):
                continue

            field_type = self._extract_type_from_schema(field_schema)
            bad_value = self._build_invalid_value(
                field_type=field_type,
                invalid_value_strategy=invalid_value_strategy,
            )

            if bad_value is not None:
                mutated[field_name] = bad_value
                logger.info(f"Mutated invalid field successfully. mutated_field={field_name}")
                return mutated

        logger.info("No field could be mutated invalidly. Returning original payload clone.")
        return mutated

    def _build_invalid_value(
        self,
        *,
        field_type: str | None,
        invalid_value_strategy: str | None,
    ) -> Any:
        strategy = invalid_value_strategy or "infer_from_schema"

        if strategy == "string_for_integer":
            return "invalid_integer"
        if strategy == "string_for_number":
            return "invalid_number"
        if strategy == "string_for_boolean":
            return "invalid_boolean"
        if strategy == "string_for_array":
            return "not_an_array"
        if strategy == "string_for_object":
            return "not_an_object"
        if strategy == "number_for_string":
            return 12345

        if strategy == "infer_from_schema":
            if field_type == "string":
                return 12345
            if field_type == "integer":
                return "invalid_integer"
            if field_type == "number":
                return "invalid_number"
            if field_type == "boolean":
                return "invalid_boolean"
            if field_type == "array":
                return "not_an_array"
            if field_type == "object":
                return "not_an_object"

        return None

    def _extract_type_from_schema(self, schema: dict[str, Any]) -> str | None:
        direct_type = schema.get("type")

        if isinstance(direct_type, list):
            non_null = [item for item in direct_type if item != "null"]
            return non_null[0] if non_null else direct_type[0]

        if isinstance(direct_type, str):
            return direct_type

        for composite_key in ("anyOf", "oneOf", "allOf"):
            composite_value = schema.get(composite_key)
            if not isinstance(composite_value, list):
                continue

            for item in composite_value:
                if not isinstance(item, dict):
                    continue

                nested_type = item.get("type")
                if isinstance(nested_type, list):
                    non_null = [x for x in nested_type if x != "null"]
                    return non_null[0] if non_null else nested_type[0]

                if isinstance(nested_type, str):
                    return nested_type

        return None