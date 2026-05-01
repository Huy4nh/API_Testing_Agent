from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api_testing_agent.logging_config import get_logger


@dataclass(frozen=True)
class FakerOptions:
    include_optional_fields: bool = True
    max_depth: int = 5
    max_array_items: int = 1


class SchemaFaker:
    def __init__(self, options: FakerOptions | None = None) -> None:
        self._opt = options or FakerOptions()
        self._logger = get_logger(__name__)

        self._logger.info(
            f"Initialized SchemaFaker. include_optional_fields={self._opt.include_optional_fields}, "
            f"max_depth={self._opt.max_depth}, max_array_items={self._opt.max_array_items}",
            extra={"payload_source": "schema_faker_init"},
        )

    def example_for_schema(self, schema: dict[str, Any], *, depth: int = 0) -> Any:
        if depth == 0:
            self._logger.debug(
                "Generating example for root schema.",
                extra={"payload_source": "schema_faker_example_root"},
            )

        if depth > self._opt.max_depth:
            self._logger.debug(
                "Schema faker exceeded max depth. Returning None.",
                extra={"payload_source": "schema_faker_max_depth"},
            )
            return None

        if "example" in schema:
            return schema["example"]

        if "default" in schema:
            return schema["default"]

        if "enum" in schema and isinstance(schema["enum"], list) and schema["enum"]:
            return schema["enum"][0]

        if "allOf" in schema and isinstance(schema["allOf"], list) and schema["allOf"]:
            merged: dict[str, Any] = {}
            for sub in schema["allOf"]:
                if isinstance(sub, dict):
                    merged = self._merge_object_schemas(merged, sub)
            return self.example_for_schema(merged, depth=depth + 1)

        if "oneOf" in schema and isinstance(schema["oneOf"], list) and schema["oneOf"]:
            first = schema["oneOf"][0]
            return self.example_for_schema(first, depth=depth + 1) if isinstance(first, dict) else None

        if "anyOf" in schema and isinstance(schema["anyOf"], list) and schema["anyOf"]:
            first = schema["anyOf"][0]
            return self.example_for_schema(first, depth=depth + 1) if isinstance(first, dict) else None

        schema_type = schema.get("type")

        if isinstance(schema_type, list):
            non_null = [item for item in schema_type if item != "null"]
            schema_type = non_null[0] if non_null else schema_type[0]

        if schema_type == "object" or (schema_type is None and "properties" in schema):
            return self._example_object(schema, depth=depth)

        if schema_type == "array":
            return self._example_array(schema, depth=depth)

        if schema_type == "string":
            return self._example_string(schema)

        if schema_type == "integer":
            return self._example_integer(schema)

        if schema_type == "number":
            return self._example_number(schema)

        if schema_type == "boolean":
            return True

        return None

    def _example_object(self, schema: dict[str, Any], *, depth: int) -> dict[str, Any]:
        raw_properties = schema.get("properties")
        properties: dict[str, Any]
        if isinstance(raw_properties, dict):
            properties = raw_properties
        else:
            properties = {}

        raw_required = schema.get("required")
        required: list[Any]
        if isinstance(raw_required, list):
            required = raw_required
        else:
            required = []

        result: dict[str, Any] = {}

        for field_name, field_schema in properties.items():
            if not isinstance(field_schema, dict):
                continue

            is_required = field_name in required
            if not is_required and not self._opt.include_optional_fields:
                continue

            result[field_name] = self.example_for_schema(field_schema, depth=depth + 1)

        return result

    def _example_array(self, schema: dict[str, Any], *, depth: int) -> list[Any]:
        raw_items = schema.get("items")
        items: dict[str, Any]
        if isinstance(raw_items, dict):
            items = raw_items
        else:
            items = {}

        if not items:
            return []

        return [
            self.example_for_schema(items, depth=depth + 1)
            for _ in range(self._opt.max_array_items)
        ]

    def _example_string(self, schema: dict[str, Any]) -> str:
        fmt = schema.get("format")

        if fmt == "email":
            return "user@example.com"
        if fmt == "uuid":
            return "00000000-0000-0000-0000-000000000000"
        if fmt in {"date-time", "datetime"}:
            return "2020-01-01T00:00:00Z"
        if fmt == "date":
            return "2020-01-01"
        if fmt == "uri":
            return "https://example.com"

        return "string"

    def _example_integer(self, schema: dict[str, Any]) -> int:
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)):
            return int(minimum)
        return 1

    def _example_number(self, schema: dict[str, Any]) -> float:
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)):
            return float(minimum)
        return 1.0

    def _merge_object_schemas(self, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        result = dict(a)

        raw_props_a = result.get("properties")
        props_a: dict[str, Any]
        if isinstance(raw_props_a, dict):
            props_a = raw_props_a
        else:
            props_a = {}

        raw_props_b = b.get("properties")
        props_b: dict[str, Any]
        if isinstance(raw_props_b, dict):
            props_b = raw_props_b
        else:
            props_b = {}

        result["properties"] = {**props_a, **props_b}

        raw_req_a = result.get("required")
        req_a: list[Any]
        if isinstance(raw_req_a, list):
            req_a = raw_req_a
        else:
            req_a = []

        raw_req_b = b.get("required")
        req_b: list[Any]
        if isinstance(raw_req_b, list):
            req_b = raw_req_b
        else:
            req_b = []

        result["required"] = sorted(set([*req_a, *req_b]))

        for key, value in b.items():
            if key in {"properties", "required", "allOf"}:
                continue
            if key not in result:
                result[key] = value

        return result