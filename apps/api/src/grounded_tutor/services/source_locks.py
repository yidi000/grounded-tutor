from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID


class WorkspaceIngestionBusyError(RuntimeError):
    """Another ingestion is already active for this Workspace."""


@dataclass(slots=True)
class _LockEntry:
    lock: asyncio.Lock


class WorkspaceLockRegistry:
    """App-scoped, non-waiting ingestion exclusion keyed by Workspace.

    This is intentionally a single-process P0 primitive. The supported P0 run
    command uses one Uvicorn worker. Multi-worker deployment requires a shared
    distributed lease and an idempotency record before public release.
    """

    def __init__(self) -> None:
        self._entries: dict[UUID, _LockEntry] = {}

    @property
    def active_count(self) -> int:
        return len(self._entries)

    @asynccontextmanager
    async def acquire(self, workspace_id: UUID) -> AsyncIterator[None]:
        # No await occurs between registry inspection and reservation. Requests
        # sharing the app event loop therefore cannot both reserve this key.
        if workspace_id in self._entries:
            raise WorkspaceIngestionBusyError
        entry = _LockEntry(asyncio.Lock())
        self._entries[workspace_id] = entry
        acquired = False
        try:
            await entry.lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                entry.lock.release()
            if self._entries.get(workspace_id) is entry:
                del self._entries[workspace_id]
