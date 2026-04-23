from __future__ import annotations

import copy
from typing import Any


class OpenApiRefResolverError(ValueError):
    pass


class OpenApiRefResolver:
    def __init__(self, spec: dict[str, Any]) -> None:
        self._spec = spec

    def resolve_parameter_obj(self, parameter_obj: dict[str, Any]) -> dict[str, Any]:
        if "$ref" not in parameter_obj:
            return copy.deepcopy(parameter_obj)

        resolved = self._resolve_ref_object(parameter_obj["$ref"])
        if not isinstance(resolved, dict):
            raise OpenApiRefResolverError(
                f"Referenced parameter is not an object: {parameter_obj['$ref']}"
            )

        merged = dict(resolved)
        for key, value in parameter_obj.items():
            if key == "$ref":
                continue
            merged[key] = value

        return merged

    def resolve_request_body_obj(self, request_body_obj: dict[str, Any]) -> dict[str, Any]:
        if "$ref" not in request_body_obj:
            return copy.deepcopy(request_body_obj)

        resolved = self._resolve_ref_object(request_body_obj["$ref"])
        if not isinstance(resolved, dict):
            raise OpenApiRefResolverError(
                f"Referenced requestBody is not an object: {request_body_obj['$ref']}"
            )

        merged = dict(resolved)
        for key, value in request_body_obj.items():
            if key == "$ref":
                continue
            merged[key] = value

        return merged

    def resolve_response_obj(self, response_obj: dict[str, Any]) -> dict[str, Any]:
        if "$ref" not in response_obj:
            return copy.deepcopy(response_obj)

        resolved = self._resolve_ref_object(response_obj["$ref"])
        if not isinstance(resolved, dict):
            raise OpenApiRefResolverError(
                f"Referenced response is not an object: {response_obj['$ref']}"
            )

        merged = dict(resolved)
        for key, value in response_obj.items():
            if key == "$ref":
                continue
            merged[key] = value

        return merged

    def resolve_schema(
        self,
        schema: dict[str, Any],
        seen_refs: set[str] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(schema, dict):
            return {}

        seen_refs = seen_refs or set()

        if "$ref" in schema:
            ref = schema["$ref"]
            if not isinstance(ref, str):
                raise OpenApiRefResolverError("Schema $ref must be a string.")

            if ref in seen_refs:
                raise OpenApiRefResolverError(f"Circular $ref detected: {ref}")

            resolved = self._resolve_ref_object(ref)
            if not isinstance(resolved, dict):
                raise OpenApiRefResolverError(f"Resolved $ref is not an object: {ref}")

            merged = copy.deepcopy(resolved)
            for key, value in schema.items():
                if key == "$ref":
                    continue
                merged[key] = value

            return self.resolve_schema(merged, seen_refs | {ref})

        resolved_schema = copy.deepcopy(schema)

        if "properties" in resolved_schema and isinstance(resolved_schema["properties"], dict):
            new_properties: dict[str, Any] = {}
            for prop_name, prop_schema in resolved_schema["properties"].items():
                if isinstance(prop_schema, dict):
                    new_properties[prop_name] = self.resolve_schema(prop_schema, seen_refs)
                else:
                    new_properties[prop_name] = prop_schema
            resolved_schema["properties"] = new_properties

        if "items" in resolved_schema and isinstance(resolved_schema["items"], dict):
            resolved_schema["items"] = self.resolve_schema(resolved_schema["items"], seen_refs)

        for combiner in ["allOf", "oneOf", "anyOf"]:
            if combiner in resolved_schema and isinstance(resolved_schema[combiner], list):
                resolved_schema[combiner] = [
                    self.resolve_schema(item, seen_refs) if isinstance(item, dict) else item
                    for item in resolved_schema[combiner]
                ]

        if (
            "additionalProperties" in resolved_schema
            and isinstance(resolved_schema["additionalProperties"], dict)
        ):
            resolved_schema["additionalProperties"] = self.resolve_schema(
                resolved_schema["additionalProperties"],
                seen_refs,
            )

        return resolved_schema

    def _resolve_ref_object(self, ref: str) -> Any:
        if not ref.startswith("#/"):
            raise OpenApiRefResolverError(f"Only internal $ref is supported right now: {ref}")

        parts = ref[2:].split("/")
        current: Any = self._spec

        for part in parts:
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(current, dict) or part not in current:
                raise OpenApiRefResolverError(f"Cannot resolve $ref: {ref}")
            current = current[part]

        return copy.deepcopy(current)