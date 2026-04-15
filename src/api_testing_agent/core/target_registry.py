from __future__ import annotations

import json
from pathlib import Path

from api_testing_agent.core.models import ApiTarget


class TargetRegistryError(ValueError):
    pass


class TargetRegistry:
    def __init__(self, targets: dict[str, ApiTarget]) -> None:
        self._targets = targets

    @classmethod
    def from_json_file(cls, path: str) -> "TargetRegistry":
        p = Path(path)
        if not p.exists():
            raise TargetRegistryError(f"Target registry file not found: {path}")

        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise TargetRegistryError("Target registry must be a JSON array.")

        targets: dict[str, ApiTarget] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue

            target = ApiTarget(
                name=str(item["name"]),
                base_url=str(item["base_url"]).rstrip("/"),
                openapi_spec_path=item.get("openapi_spec_path"),
                openapi_spec_url=item.get("openapi_spec_url"),
                auth_bearer_token=item.get("auth_bearer_token"),
                enabled=bool(item.get("enabled", True)),
            )
            targets[target.name] = target

        if not targets:
            raise TargetRegistryError("No targets found in registry.")

        return cls(targets)

    def get(self, name: str) -> ApiTarget:
        target = self._targets.get(name)
        if target is None:
            raise TargetRegistryError(f"Target '{name}' does not exist.")
        if not target.enabled:
            raise TargetRegistryError(f"Target '{name}' is disabled.")
        return target

    def default(self) -> ApiTarget:
        for target in self._targets.values():
            if target.enabled:
                return target
        raise TargetRegistryError("No enabled target available.")

    def list_names(self) -> list[str]:
        return [name for name, target in self._targets.items() if target.enabled]