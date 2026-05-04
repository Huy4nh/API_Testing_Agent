from __future__ import annotations

import copy
from typing import Protocol, runtime_checkable

from api_testing_agent.logging_config import bind_logger, get_logger
from api_testing_agent.tasks.workflow_models import WorkflowContextSnapshot


@runtime_checkable
class WorkflowStateStoreProtocol(Protocol):
    def get(self, thread_id: str) -> WorkflowContextSnapshot | None: ...
    def save(self, snapshot: WorkflowContextSnapshot) -> None: ...
    def delete(self, thread_id: str) -> None: ...
    def exists(self, thread_id: str) -> bool: ...


class InMemoryWorkflowStateStore:
    def __init__(self) -> None:
        self._items: dict[str, WorkflowContextSnapshot] = {}
        self._logger = get_logger(__name__)

    def get(self, thread_id: str) -> WorkflowContextSnapshot | None:
        snapshot = self._items.get(thread_id)
        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            payload_source="workflow_state_store_get",
        )
        logger.info(f"Loading workflow snapshot found={snapshot is not None}.")
        if snapshot is None:
            return None
        return copy.deepcopy(snapshot)

    def save(self, snapshot: WorkflowContextSnapshot) -> None:
        logger = bind_logger(
            self._logger,
            thread_id=snapshot.thread_id,
            target_name=str(snapshot.selected_target or "-"),
            payload_source="workflow_state_store_save",
        )
        logger.info(f"Saving workflow snapshot phase={snapshot.phase.value}.")
        self._items[snapshot.thread_id] = copy.deepcopy(snapshot)

    def delete(self, thread_id: str) -> None:
        logger = bind_logger(
            self._logger,
            thread_id=thread_id,
            payload_source="workflow_state_store_delete",
        )
        logger.info("Deleting workflow snapshot.")
        self._items.pop(thread_id, None)

    def exists(self, thread_id: str) -> bool:
        return thread_id in self._items