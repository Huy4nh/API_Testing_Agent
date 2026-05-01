from __future__ import annotations

import json
from pathlib import Path

from api_testing_agent.core.models import ApiTarget
from api_testing_agent.logging_config import bind_logger, get_logger


class TargetRegistryError(ValueError):
    pass


class TargetRegistry:
    def __init__(self, targets: dict[str, ApiTarget]) -> None:
        self._targets = targets
        self._logger = get_logger(__name__)

        self._logger.info(
            f"Initialized TargetRegistry with target_count={len(self._targets)}.",
            extra={"payload_source": "target_registry_init"},
        )

    @classmethod
    def from_json_file(cls, path: str) -> "TargetRegistry":
        logger = bind_logger(
            get_logger(__name__),
            payload_source="target_registry_from_file",
        )
        logger.info(f"Loading target registry from path={path}")

        p = Path(path)
        if not p.exists():
            logger.error("Target registry file not found.")
            raise TargetRegistryError(f"Target registry file not found: {path}")

        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            logger.error("Target registry root is not a JSON array.")
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
            logger.error("No targets found in registry.")
            raise TargetRegistryError("No targets found in registry.")

        logger.info(f"Loaded target registry successfully. target_count={len(targets)}")
        return cls(targets)

    def get(self, name: str) -> ApiTarget:
        logger = bind_logger(
            self._logger,
            target_name=name,
            payload_source="target_registry_get",
        )
        logger.info("Resolving target from registry.")

        target = self._targets.get(name)
        if target is None:
            logger.error("Target does not exist in registry.")
            raise TargetRegistryError(f"Target '{name}' does not exist.")
        if not target.enabled:
            logger.warning("Target exists but is disabled.")
            raise TargetRegistryError(f"Target '{name}' is disabled.")

        logger.info("Resolved enabled target successfully.")
        return target

    def default(self) -> ApiTarget:
        logger = bind_logger(
            self._logger,
            payload_source="target_registry_default",
        )
        logger.info("Resolving default target.")

        for target in self._targets.values():
            if target.enabled:
                logger.info(f"Resolved default enabled target={target.name}")
                return target

        logger.error("No enabled target available for default().")
        raise TargetRegistryError("No enabled target available.")

    def list_names(self) -> list[str]:
        enabled_names = [name for name, target in self._targets.items() if target.enabled]

        self._logger.info(
            f"Listing enabled target names. enabled_count={len(enabled_names)}",
            extra={"payload_source": "target_registry_list_names"},
        )

        return enabled_names