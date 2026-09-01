from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from grounded_tutor.domain.models import Source, SourceStatus, Workspace


class WorkspacePersistenceError(RuntimeError):
    """A local persistence failure whose implementation details are private."""

    def __init__(self, message: str = "Workspace persistence failed.", *, committed: bool = False) -> None:
        self.committed = committed
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class WorkspaceSummary:
    id: UUID
    title: str
    source_count: int
    ready_source_count: int
    created_at: datetime
    updated_at: datetime


class WorkspaceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, title: str, dataset_id: str) -> WorkspaceSummary:
        workspace = Workspace(title=title, dataset_id=dataset_id)
        committed = False
        try:
            self._session.add(workspace)
            self._session.flush()
            summary = _summary(workspace, source_count=0, ready_source_count=0)
            self._session.commit()
            committed = True
            return summary
        except SQLAlchemyError as error:
            if not committed:
                self._rollback()
            raise WorkspacePersistenceError(committed=committed) from error

    def list(self) -> list[WorkspaceSummary]:
        try:
            rows = self._session.execute(_summary_query()).mappings()
            return [_summary_from_row(row) for row in rows]
        except SQLAlchemyError as error:
            self._rollback()
            raise WorkspacePersistenceError(committed=False) from error

    def get(self, workspace_id: UUID) -> WorkspaceSummary | None:
        try:
            row = self._session.execute(
                _summary_query().where(Workspace.id == workspace_id)
            ).mappings().one_or_none()
            return _summary_from_row(row) if row is not None else None
        except SQLAlchemyError as error:
            self._rollback()
            raise WorkspacePersistenceError(committed=False) from error

    def rename(self, workspace_id: UUID, *, title: str) -> WorkspaceSummary | None:
        committed = False
        try:
            workspace = self._session.get(Workspace, workspace_id)
            if workspace is None:
                return None
            workspace.title = title
            self._session.flush()
            summary = self._get_summary(workspace_id)
            self._session.commit()
            committed = True
            return summary
        except SQLAlchemyError as error:
            if not committed:
                self._rollback()
            raise WorkspacePersistenceError(committed=committed) from error

    def _get_summary(self, workspace_id: UUID) -> WorkspaceSummary | None:
        row = self._session.execute(
            _summary_query().where(Workspace.id == workspace_id)
        ).mappings().one_or_none()
        return _summary_from_row(row) if row is not None else None

    def _rollback(self) -> None:
        try:
            self._session.rollback()
        except SQLAlchemyError:
            return


def _summary_query():
    source_count = func.count(Source.id).label("source_count")
    ready_source_count = func.coalesce(
        func.sum(case((Source.status == SourceStatus.READY, 1), else_=0)), 0
    ).label("ready_source_count")
    return (
        select(
            Workspace.id,
            Workspace.title,
            source_count,
            ready_source_count,
            Workspace.created_at,
            Workspace.updated_at,
        )
        .outerjoin(Source, Source.workspace_id == Workspace.id)
        .group_by(Workspace.id, Workspace.title, Workspace.created_at, Workspace.updated_at)
        .order_by(Workspace.created_at.desc(), Workspace.id.desc())
    )


def _summary(
    workspace: Workspace, *, source_count: int, ready_source_count: int
) -> WorkspaceSummary:
    return WorkspaceSummary(
        id=workspace.id,
        title=workspace.title,
        source_count=source_count,
        ready_source_count=ready_source_count,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


def _summary_from_row(row: Mapping[str, object]) -> WorkspaceSummary:
    return WorkspaceSummary(
        id=row["id"],  # type: ignore[arg-type]
        title=row["title"],  # type: ignore[arg-type]
        source_count=row["source_count"],  # type: ignore[arg-type]
        ready_source_count=row["ready_source_count"],  # type: ignore[arg-type]
        created_at=row["created_at"],  # type: ignore[arg-type]
        updated_at=row["updated_at"],  # type: ignore[arg-type]
    )
