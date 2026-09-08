from __future__ import annotations

from uuid import UUID

from grounded_tutor.adapters.fastgpt import FastGPTPort
from grounded_tutor.config import Settings, capability_request_is_supported
from grounded_tutor.repositories.workspaces import (
    WorkspacePersistenceError,
    WorkspacePersistenceOutcome,
    WorkspaceRepository,
    WorkspaceSummary,
)
from grounded_tutor.services.source_locks import WorkspaceIngestionBusyError, WorkspaceLockRegistry


class WorkspaceNotFoundError(LookupError):
    """A requested workspace does not exist."""


class ExternalWorkspaceServiceError(RuntimeError):
    """FastGPT could not complete a workspace operation."""


class UnsupportedWorkspaceModelError(ValueError):
    """A requested model capability is not verified for this deployment."""


class WorkspaceService:
    def __init__(
        self,
        repository: WorkspaceRepository,
        fastgpt: FastGPTPort,
        settings: Settings | None = None,
        locks: WorkspaceLockRegistry | None = None,
    ) -> None:
        self._repository = repository
        self._fastgpt = fastgpt
        self._settings = settings or Settings()
        self._locks = locks or WorkspaceLockRegistry()

    async def create(
        self,
        *,
        title: str,
        vector_model: str | None,
        agent_model: str | None,
        vlm_model: str | None,
    ) -> WorkspaceSummary:
        if not all(
            (
                capability_request_is_supported(
                    requested=vector_model,
                    supported=self._settings.supports_vector_model,
                ),
                capability_request_is_supported(
                    requested=agent_model,
                    supported=self._settings.supports_agent_model,
                ),
                capability_request_is_supported(
                    requested=vlm_model,
                    supported=self._settings.supports_vlm_model,
                ),
            )
        ):
            raise UnsupportedWorkspaceModelError
        try:
            dataset = await self._fastgpt.create_dataset(
                title,
                vector_model=vector_model,
                agent_model=agent_model,
                vlm_model=vlm_model,
            )
        except Exception as error:
            raise ExternalWorkspaceServiceError("Dataset creation failed.") from error

        try:
            return self._repository.create(
                title=title,
                dataset_id=dataset.dataset_id,
                vector_model=vector_model,
                agent_model=agent_model,
                vlm_model=vlm_model,
            )
        except WorkspacePersistenceError as error:
            if error.outcome is WorkspacePersistenceOutcome.DEFINITELY_UNCOMMITTED:
                await self._compensate_dataset_creation(dataset.dataset_id)
            raise

    async def _compensate_dataset_creation(self, dataset_id: str) -> None:
        try:
            await self._fastgpt.delete_dataset(dataset_id)
        except Exception:  # noqa: BLE001 - compensation must remain best effort.
            return

    def list(self) -> list[WorkspaceSummary]:
        return self._repository.list()

    def get(self, workspace_id: UUID) -> WorkspaceSummary:
        workspace = self._repository.get(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError
        return workspace

    def rename(self, workspace_id: UUID, *, title: str) -> WorkspaceSummary:
        workspace = self._repository.rename(workspace_id, title=title)
        if workspace is None:
            raise WorkspaceNotFoundError
        return workspace

    async def delete(self, workspace_id: UUID) -> None:
        async with self._locks.acquire(workspace_id):
            dataset_id = self._repository.dataset_id(workspace_id)
            if dataset_id is None:
                return
            if self._repository.has_pending_request(workspace_id):
                raise WorkspaceIngestionBusyError
            try:
                await self._fastgpt.delete_dataset(dataset_id)
            except Exception as error:
                raise ExternalWorkspaceServiceError("Dataset deletion failed.") from error
            self._repository.delete(workspace_id)
