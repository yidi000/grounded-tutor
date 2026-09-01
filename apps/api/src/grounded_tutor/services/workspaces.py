from __future__ import annotations

from uuid import UUID

from grounded_tutor.adapters.fastgpt import FastGPTPort
from grounded_tutor.repositories.workspaces import (
    WorkspacePersistenceError,
    WorkspaceRepository,
    WorkspaceSummary,
)


class WorkspaceNotFoundError(LookupError):
    """A requested workspace does not exist."""


class ExternalWorkspaceServiceError(RuntimeError):
    """FastGPT could not complete a workspace operation."""


class WorkspaceService:
    def __init__(self, repository: WorkspaceRepository, fastgpt: FastGPTPort) -> None:
        self._repository = repository
        self._fastgpt = fastgpt

    async def create(
        self,
        *,
        title: str,
        vector_model: str | None,
        agent_model: str | None,
        vlm_model: str | None,
    ) -> WorkspaceSummary:
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
            return self._repository.create(title=title, dataset_id=dataset.dataset_id)
        except WorkspacePersistenceError:
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
