from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from grounded_tutor.domain.models import Source, SourceStatus, SourceType, Workspace


class SourcePersistenceOutcome(str, Enum):
    DEFINITELY_UNCOMMITTED = "definitely_uncommitted"
    UNKNOWN_OR_COMMITTED = "unknown_or_committed"


class SourcePersistenceError(RuntimeError):
    """A redacted local persistence failure with an explicit commit outcome."""

    def __init__(
        self,
        message: str = "Source persistence failed.",
        *,
        outcome: SourcePersistenceOutcome,
    ) -> None:
        self.outcome = outcome
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class SourceSummary:
    id: UUID
    workspace_id: UUID
    name: str
    source_type: SourceType
    origin_uri: str | None
    status: SourceStatus
    version: int
    lineage_id: UUID
    replaces_source_id: UUID | None
    superseded_at: datetime | None
    deleted_at: datetime | None
    ingestion_config: dict[str, Any]
    error_message: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SourceExternalRef:
    summary: SourceSummary
    collection_id: str | None


class SourceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_workspace_dataset_id(self, workspace_id: UUID) -> str | None:
        try:
            return self._session.scalar(
                select(Workspace.dataset_id).where(Workspace.id == workspace_id)
            )
        except SQLAlchemyError as error:
            self._rollback()
            raise SourcePersistenceError(
                outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
            ) from error

    def create_indexing(
        self,
        *,
        source_id: UUID,
        workspace_id: UUID,
        name: str,
        source_type: SourceType,
        origin_uri: str | None,
        ingestion_config: dict[str, Any],
        lineage_id: UUID | None = None,
        replaces_source_id: UUID | None = None,
        version: int = 1,
    ) -> SourceSummary:
        source = Source(
            id=source_id,
            workspace_id=workspace_id,
            name=name,
            source_type=source_type,
            origin_uri=origin_uri,
            status=SourceStatus.INDEXING,
            version=version,
            lineage_id=lineage_id or source_id,
            replaces_source_id=replaces_source_id,
            ingestion_config=dict(ingestion_config),
            error_message=None,
        )
        return self._persist_new(source)

    def set_collection_id(self, source_id: UUID, *, collection_id: str) -> SourceSummary:
        return self._update(
            source_id,
            collection_id=collection_id,
            error_message=None,
        )

    def transition_review(self, source_id: UUID) -> SourceSummary:
        return self._update(
            source_id,
            status=SourceStatus.REVIEW,
            error_message=None,
        )

    def transition_failed(
        self,
        source_id: UUID,
        *,
        collection_id: str | None,
        safe_error_message: str,
    ) -> SourceSummary | None:
        values: dict[str, object] = {
            "status": SourceStatus.FAILED,
            "error_message": safe_error_message,
            "collection_id": collection_id,
        }
        return self._update_record(source_id, **values)

    def mark_ready(
        self, source_id: UUID, *, superseded_source_id: UUID | None = None
    ) -> SourceSummary:
        try:
            source = self._session.get(Source, source_id)
            if source is None:
                raise SourcePersistenceError(
                    outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
                )
            source.status = SourceStatus.READY
            source.error_message = None
            if superseded_source_id is not None:
                superseded = self._session.get(Source, superseded_source_id)
                if superseded is None:
                    raise SourcePersistenceError(
                        outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
                    )
                superseded.superseded_at = datetime.now(UTC)
            self._session.flush()
            summary = _summary(source)
        except SourcePersistenceError:
            self._rollback()
            raise
        except SQLAlchemyError as error:
            self._rollback()
            raise SourcePersistenceError(
                outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
            ) from error
        self._commit()
        return summary

    def mark_superseded(self, source_id: UUID) -> SourceSummary:
        return self._update(source_id, superseded_at=datetime.now(UTC))

    def mark_deleted(self, source_id: UUID) -> SourceSummary:
        return self._update(source_id, deleted_at=datetime.now(UTC))

    def ready_collection_ids(self, workspace_id: UUID) -> dict[str, SourceSummary]:
        try:
            sources = self._session.scalars(
                select(Source).where(
                    Source.workspace_id == workspace_id,
                    Source.status == SourceStatus.READY,
                    Source.superseded_at.is_(None),
                    Source.deleted_at.is_(None),
                    Source.collection_id.is_not(None),
                )
            )
            return {
                source.collection_id: _summary(source)
                for source in sources
                if source.collection_id is not None
            }
        except SQLAlchemyError as error:
            self._rollback()
            raise SourcePersistenceError(
                outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
            ) from error

    def has_pending_review(self, workspace_id: UUID, lineage_id: UUID) -> bool:
        try:
            return (
                self._session.scalar(
                    select(Source.id).where(
                        Source.workspace_id == workspace_id,
                        Source.lineage_id == lineage_id,
                        Source.status == SourceStatus.REVIEW,
                        Source.replaces_source_id.is_not(None),
                        Source.superseded_at.is_(None),
                        Source.deleted_at.is_(None),
                    )
                )
                is not None
            )
        except SQLAlchemyError as error:
            self._rollback()
            raise SourcePersistenceError(
                outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
            ) from error

    def list_for_workspace(self, workspace_id: UUID) -> tuple[bool, list[SourceSummary]]:
        try:
            sources = list(
                self._session.scalars(
                    select(Source)
                    .where(
                        Source.workspace_id == workspace_id,
                        Source.superseded_at.is_(None),
                        Source.deleted_at.is_(None),
                    )
                    .order_by(Source.created_at.desc(), Source.id.desc())
                )
            )
            if sources:
                return True, [_summary(source) for source in sources]
            exists = self._session.scalar(
                select(Workspace.id).where(Workspace.id == workspace_id)
            )
            return exists is not None, []
        except SQLAlchemyError as error:
            self._rollback()
            raise SourcePersistenceError(
                outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
            ) from error

    def get_for_workspace(
        self, workspace_id: UUID, source_id: UUID
    ) -> SourceExternalRef | None:
        try:
            source = self._session.scalar(
                select(Source).where(
                    Source.id == source_id,
                    Source.workspace_id == workspace_id,
                    Source.superseded_at.is_(None),
                    Source.deleted_at.is_(None),
                )
            )
            if source is None:
                return None
            return SourceExternalRef(_summary(source), source.collection_id)
        except SQLAlchemyError as error:
            self._rollback()
            raise SourcePersistenceError(
                outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
            ) from error

    def get_historical_for_workspace(
        self, workspace_id: UUID, source_id: UUID
    ) -> SourceExternalRef | None:
        """Explicit citation-history lookup, including hidden source versions."""
        try:
            source = self._session.scalar(
                select(Source).where(
                    Source.id == source_id,
                    Source.workspace_id == workspace_id,
                )
            )
            if source is None:
                return None
            return SourceExternalRef(_summary(source), source.collection_id)
        except SQLAlchemyError as error:
            self._rollback()
            raise SourcePersistenceError(
                outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
            ) from error

    def _persist_new(self, source: Source) -> SourceSummary:
        try:
            self._session.add(source)
            self._session.flush()
            summary = _summary(source)
        except SQLAlchemyError as error:
            self._rollback()
            raise SourcePersistenceError(
                outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
            ) from error
        self._commit()
        return summary

    def _update(self, source_id: UUID, **values: object) -> SourceSummary:
        source = self._update_record(source_id, **values)
        if source is None:
            raise SourcePersistenceError(
                outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
            )
        return source

    def _update_record(self, source_id: UUID, **values: object) -> SourceSummary | None:
        try:
            source = self._session.get(Source, source_id)
            if source is None:
                return None
            for field, value in values.items():
                setattr(source, field, value)
            self._session.flush()
            summary = _summary(source)
        except SQLAlchemyError as error:
            self._rollback()
            raise SourcePersistenceError(
                outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
            ) from error
        self._commit()
        return summary

    def _commit(self) -> None:
        try:
            self._session.commit()
        except SQLAlchemyError as error:
            self._rollback()
            raise SourcePersistenceError(
                outcome=SourcePersistenceOutcome.UNKNOWN_OR_COMMITTED
            ) from error

    def _rollback(self) -> None:
        try:
            self._session.rollback()
        except SQLAlchemyError:
            # An exception raised after the database commit can leave the
            # Session's transaction object unusable even though the row is
            # durable. Closing resets the Session so conservative follow-up
            # state can still be written without guessing the commit outcome.
            self._session.close()


def _summary(source: Source) -> SourceSummary:
    return SourceSummary(
        id=source.id,
        workspace_id=source.workspace_id,
        name=source.name,
        source_type=source.source_type,
        origin_uri=source.origin_uri,
        status=source.status,
        version=source.version,
        lineage_id=source.lineage_id,
        replaces_source_id=source.replaces_source_id,
        superseded_at=source.superseded_at,
        deleted_at=source.deleted_at,
        ingestion_config=dict(source.ingestion_config),
        error_message=source.error_message,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )
