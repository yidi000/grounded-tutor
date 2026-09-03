from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from grounded_tutor.adapters.fastgpt import CollectionListItem, FastGPTPort, ProcessedChunk
from grounded_tutor.domain.ingestion import ChunkSettings
from grounded_tutor.domain.models import SourceStatus, SourceType
from grounded_tutor.domain.schemas import (
    ProcessedPreviewItemResponse,
    ProcessedPreviewResponse,
)
from grounded_tutor.repositories.sources import (
    SourceExternalRef,
    SourcePersistenceError,
    SourcePersistenceOutcome,
    SourceRepository,
    SourceSummary,
)
from grounded_tutor.services.previews import SUPPORTED_EXTENSIONS, PreviewError
from grounded_tutor.services.source_locks import WorkspaceLockRegistry

SAFE_INGESTION_ERROR = "Source ingestion failed."
SAFE_DISABLE_UNCONFIRMED_ERROR = (
    "Source ingestion failed; remote disable could not be confirmed."
)
SAFE_RECONCILIATION_INCOMPLETE_ERROR = (
    "Source ingestion failed; remote reconciliation could not be completed."
)
SAFE_MULTIPLE_REMOTE_MATCHES_ERROR = (
    "Source ingestion failed; multiple remote matches require review."
)
PROCESSED_PREVIEW_LIMIT = 30
RECONCILIATION_PAGE_SIZE = 30
MAX_RECONCILIATION_PAGES = 4
RECONCILIATION_TIMEOUT_SECONDS = 5.0
REMOTE_NAME_MAX_LENGTH = 255
REMOTE_MARKER_PREFIX = "gt-src-"
REMOTE_NAME_SEPARATOR = "--"
MAX_PUBLIC_PROCESSED_FIELD_CHARS = 4_000


class SourceWorkspaceNotFoundError(LookupError):
    pass


class SourceNotFoundError(LookupError):
    pass


class SourcePreviewUnavailableError(RuntimeError):
    pass


class ExternalSourceServiceError(RuntimeError):
    pass


class SourceLifecycleConflictError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SourceIngestionResult:
    source: SourceSummary
    processed_preview: ProcessedPreviewResponse


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    collection_id: str | None
    safe_error_message: str


class SourceService:
    def __init__(
        self,
        repository: SourceRepository,
        fastgpt: FastGPTPort,
        locks: WorkspaceLockRegistry,
        *,
        max_upload_bytes: int = 20_000_000,
        max_text_bytes: int = 20_000_000,
    ) -> None:
        self._repository = repository
        self._fastgpt = fastgpt
        self._locks = locks
        self.max_upload_bytes = max_upload_bytes
        self.max_text_bytes = max_text_bytes

    async def ingest_text(
        self,
        *,
        workspace_id: UUID,
        name: str,
        text: str,
        settings: ChunkSettings,
    ) -> SourceIngestionResult:
        _validate_text(name, text, self.max_text_bytes)
        return await self._ingest(
            workspace_id=workspace_id,
            name=name,
            source_type=SourceType.TEXT,
            settings=settings,
            create_collection=lambda dataset_id, remote_name, config: (
                self._fastgpt.create_text_collection(
                    dataset_id, remote_name, text, config
                )
            ),
        )

    async def ingest_file(
        self,
        *,
        workspace_id: UUID,
        filename: str,
        content: bytes,
        settings: ChunkSettings,
    ) -> SourceIngestionResult:
        safe_name = _validate_file(filename, content, self.max_upload_bytes)
        return await self._ingest(
            workspace_id=workspace_id,
            name=safe_name,
            source_type=SourceType.FILE,
            settings=settings,
            create_collection=lambda dataset_id, remote_name, config: (
                self._fastgpt.create_file_collection(
                    dataset_id, remote_name, content, config
                )
            ),
        )

    async def reprocess_text(
        self,
        *,
        workspace_id: UUID,
        source_id: UUID,
        name: str,
        text: str,
        settings: ChunkSettings,
    ) -> SourceIngestionResult:
        _validate_text(name, text, self.max_text_bytes)
        return await self._ingest(
            workspace_id=workspace_id,
            name=name,
            source_type=SourceType.TEXT,
            settings=settings,
            replaces_source_id=source_id,
            create_collection=lambda dataset_id, remote_name, config: (
                self._fastgpt.create_text_collection(
                    dataset_id, remote_name, text, config
                )
            ),
        )

    async def reprocess_file(
        self,
        *,
        workspace_id: UUID,
        source_id: UUID,
        filename: str,
        content: bytes,
        settings: ChunkSettings,
    ) -> SourceIngestionResult:
        safe_name = _validate_file(filename, content, self.max_upload_bytes)
        return await self._ingest(
            workspace_id=workspace_id,
            name=safe_name,
            source_type=SourceType.FILE,
            settings=settings,
            replaces_source_id=source_id,
            create_collection=lambda dataset_id, remote_name, config: (
                self._fastgpt.create_file_collection(
                    dataset_id, remote_name, content, config
                )
            ),
        )

    async def _ingest(
        self,
        *,
        workspace_id: UUID,
        name: str,
        source_type: SourceType,
        settings: ChunkSettings,
        create_collection: Callable[[str, str, dict[str, object]], Awaitable[object]],
        replaces_source_id: UUID | None = None,
    ) -> SourceIngestionResult:
        config = settings.model_dump(by_alias=True)
        source_id = uuid4()
        marker = source_marker(source_id)
        remote_name = _remote_collection_name(name, source_type, marker)
        remote_config = {**config, "tags": [marker]}
        async with self._locks.acquire(workspace_id):
            dataset_id = self._repository.get_workspace_dataset_id(workspace_id)
            if dataset_id is None:
                raise SourceWorkspaceNotFoundError
            lineage_id: UUID | None = None
            version = 1
            if replaces_source_id is not None:
                replaced = self._repository.get_for_workspace(
                    workspace_id, replaces_source_id
                )
                if replaced is None:
                    raise SourceNotFoundError
                if replaced.summary.status is not SourceStatus.READY:
                    raise SourceLifecycleConflictError("invalid_source_status")
                if self._repository.has_pending_review(
                    workspace_id, replaced.summary.lineage_id
                ):
                    raise SourceLifecycleConflictError("invalid_source_status")
                lineage_id = replaced.summary.lineage_id
                version = replaced.summary.version + 1
            collection_id: str | None = None
            remote_create_started = False
            try:
                source = self._repository.create_indexing(
                    source_id=source_id,
                    workspace_id=workspace_id,
                    name=name,
                    source_type=source_type,
                    origin_uri=None,
                    ingestion_config=config,
                    lineage_id=lineage_id,
                    replaces_source_id=replaces_source_id,
                    version=version,
                )
                remote_create_started = True
                collection = await create_collection(dataset_id, remote_name, remote_config)
                collection_id = _collection_id(collection)
                await self._set_collection_forbidden_confirmed(
                    dataset_id=dataset_id,
                    source_id=source_id,
                    collection_id=collection_id,
                    forbidden=True,
                )
                self._repository.set_collection_id(source.id, collection_id=collection_id)
                chunks = await self._fastgpt.list_collection_data(
                    collection_id, page_size=PROCESSED_PREVIEW_LIMIT
                )
                source = self._repository.transition_review(source.id)
            except asyncio.CancelledError:
                reconciliation = await self._reconcile_if_needed(
                    dataset_id=dataset_id,
                    marker=marker,
                    known_collection_id=collection_id,
                    remote_create_started=remote_create_started,
                )
                self._persist_failed_ingestion(
                    source_id, reconciliation, strict=False
                )
                raise
            except SourcePersistenceError:
                reconciliation = await self._reconcile_if_needed(
                    dataset_id=dataset_id,
                    marker=marker,
                    known_collection_id=collection_id,
                    remote_create_started=remote_create_started,
                )
                self._persist_failed_ingestion(
                    source_id, reconciliation, strict=False
                )
                raise
            except Exception as error:
                reconciliation = await self._reconcile_if_needed(
                    dataset_id=dataset_id,
                    marker=marker,
                    known_collection_id=collection_id,
                    remote_create_started=remote_create_started,
                )
                self._persist_failed_ingestion(source_id, reconciliation, strict=True)
                raise ExternalSourceServiceError("Source ingestion failed.") from error
            return SourceIngestionResult(
                source=source,
                processed_preview=_processed_preview(source, chunks),
            )

    async def _set_collection_forbidden_confirmed(
        self,
        *,
        dataset_id: str,
        source_id: UUID,
        collection_id: str,
        forbidden: bool,
    ) -> None:
        marker = source_marker(source_id)
        for _ in range(2):
            with suppress(Exception):
                await self._fastgpt.set_collection_forbidden(
                    collection_id, forbidden
                )
            try:
                matches, complete = await self._find_marker_matches(
                    dataset_id, marker
                )
            except Exception:  # noqa: BLE001 - retry covers transient provider failure.
                matches, complete = [], False
            if (
                complete
                and len(matches) == 1
                and matches[0].collection_id == collection_id
                and matches[0].forbidden is forbidden
            ):
                return
        raise ExternalSourceServiceError("Remote collection state could not be confirmed.")

    async def _run_reconciliation_to_completion(
        self, reconciliation: Awaitable[None]
    ) -> None:
        task = asyncio.create_task(reconciliation)
        cancelled: asyncio.CancelledError | None = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as error:
                if task.cancelled():
                    break
                cancelled = cancelled or error
            except BaseException:
                if not task.done():
                    raise
        try:
            task.result()
        except BaseException as error:
            if cancelled is not None:
                raise cancelled from error
            raise
        if cancelled is not None:
            raise cancelled

    async def _reconcile_if_needed(
        self,
        *,
        dataset_id: str,
        marker: str,
        known_collection_id: str | None,
        remote_create_started: bool,
    ) -> ReconciliationResult:
        if not remote_create_started:
            return ReconciliationResult(None, SAFE_INGESTION_ERROR)
        task = asyncio.create_task(
            asyncio.wait_for(
                self._reconcile_remote_collections(
                    dataset_id=dataset_id,
                    marker=marker,
                    known_collection_id=known_collection_id,
                ),
                timeout=RECONCILIATION_TIMEOUT_SECONDS,
            )
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                return await task
            except Exception:  # noqa: BLE001 - reconciliation is best effort.
                return ReconciliationResult(
                    known_collection_id, SAFE_RECONCILIATION_INCOMPLETE_ERROR
                )
        except Exception:  # noqa: BLE001 - reconciliation never exposes provider details.
            return ReconciliationResult(
                known_collection_id, SAFE_RECONCILIATION_INCOMPLETE_ERROR
            )

    async def _reconcile_remote_collections(
        self,
        *,
        dataset_id: str,
        marker: str,
        known_collection_id: str | None,
    ) -> ReconciliationResult:
        listing_succeeded = True
        listing_complete = False
        matches: list[CollectionListItem] = []
        try:
            matches, listing_complete = await self._find_marker_matches(
                dataset_id, marker
            )
        except Exception:  # noqa: BLE001 - update known IDs even if listing is unavailable.
            listing_succeeded = False

        candidates: dict[str, bool] = {
            match.collection_id: match.forbidden for match in matches
        }
        if known_collection_id is not None:
            candidates.setdefault(known_collection_id, False)

        async def forbid(collection_id: str) -> tuple[str, bool]:
            try:
                await self._fastgpt.set_collection_forbidden(collection_id, True)
                return collection_id, True
            except Exception:  # noqa: BLE001 - every candidate remains isolated locally.
                return collection_id, candidates[collection_id]

        results = await asyncio.gather(*(forbid(item) for item in candidates))
        confirmed = {collection_id for collection_id, success in results if success}
        recovered_id = next(iter(candidates)) if len(candidates) == 1 else None
        if len(candidates) > 1:
            safe_message = SAFE_MULTIPLE_REMOTE_MATCHES_ERROR
        elif not listing_succeeded or not listing_complete:
            safe_message = SAFE_RECONCILIATION_INCOMPLETE_ERROR
        elif candidates and len(confirmed) != len(candidates):
            safe_message = SAFE_DISABLE_UNCONFIRMED_ERROR
        else:
            safe_message = SAFE_INGESTION_ERROR
        return ReconciliationResult(recovered_id, safe_message)

    async def _find_marker_matches(
        self, dataset_id: str, marker: str
    ) -> tuple[list[CollectionListItem], bool]:
        matches: dict[str, CollectionListItem] = {}
        offset = 0
        for _ in range(MAX_RECONCILIATION_PAGES):
            page = await self._fastgpt.list_collections(
                dataset_id,
                offset=offset,
                page_size=RECONCILIATION_PAGE_SIZE,
                search_text=marker,
            )
            for item in page.items:
                if _has_exact_marker(item, marker):
                    matches[item.collection_id] = item
            offset += len(page.items)
            if offset >= page.total:
                return list(matches.values()), True
            if not page.items:
                return list(matches.values()), False
        return list(matches.values()), False

    def _persist_failed_ingestion(
        self,
        source_id: UUID,
        reconciliation: ReconciliationResult,
        *,
        strict: bool,
    ) -> None:
        try:
            failed = self._repository.transition_failed(
                source_id,
                collection_id=reconciliation.collection_id,
                safe_error_message=reconciliation.safe_error_message,
            )
            if failed is None and strict:
                raise SourcePersistenceError(
                    outcome=SourcePersistenceOutcome.DEFINITELY_UNCOMMITTED
                )
        except SourcePersistenceError:
            if strict:
                raise

    def list(self, workspace_id: UUID) -> list[SourceSummary]:
        exists, sources = self._repository.list_for_workspace(workspace_id)
        if not exists:
            raise SourceWorkspaceNotFoundError
        return sources

    async def accept(self, workspace_id: UUID, source_id: UUID) -> SourceSummary:
        async with self._locks.acquire(workspace_id):
            dataset_id = self._repository.get_workspace_dataset_id(workspace_id)
            if dataset_id is None:
                raise SourceNotFoundError
            source = self._repository.get_for_workspace(workspace_id, source_id)
            if source is None:
                raise SourceNotFoundError
            if source.summary.status is not SourceStatus.REVIEW:
                raise SourceLifecycleConflictError("invalid_source_status")
            if source.collection_id is None:
                raise SourceLifecycleConflictError("empty_processed_source")
            try:
                chunks = await self._fastgpt.list_collection_data(
                    source.collection_id, page_size=1
                )
            except Exception as error:
                raise ExternalSourceServiceError("Source acceptance failed.") from error
            if not chunks:
                raise SourceLifecycleConflictError("empty_processed_source")

            replaced = None
            if source.summary.replaces_source_id is not None:
                replaced = self._repository.get_for_workspace(
                    workspace_id, source.summary.replaces_source_id
                )
                if replaced is None or replaced.summary.status is not SourceStatus.READY:
                    raise SourceLifecycleConflictError("invalid_source_status")

            try:
                await self._set_collection_forbidden_confirmed(
                    dataset_id=dataset_id,
                    source_id=source.summary.id,
                    collection_id=source.collection_id,
                    forbidden=False,
                )
                if replaced is not None and replaced.collection_id is not None:
                    await self._set_collection_forbidden_confirmed(
                        dataset_id=dataset_id,
                        source_id=replaced.summary.id,
                        collection_id=replaced.collection_id,
                        forbidden=True,
                    )
            except asyncio.CancelledError:
                await self._run_reconciliation_to_completion(
                    self._align_accept_remote(
                        dataset_id=dataset_id,
                        source=source,
                        replaced=replaced,
                        accepted=False,
                    )
                )
                raise
            except Exception as error:
                try:
                    await self._run_reconciliation_to_completion(
                        self._align_accept_remote(
                            dataset_id=dataset_id,
                            source=source,
                            replaced=replaced,
                            accepted=False,
                        )
                    )
                except Exception as reconciliation_error:
                    raise ExternalSourceServiceError(
                        "Source acceptance reconciliation failed."
                    ) from reconciliation_error
                raise ExternalSourceServiceError("Source acceptance failed.") from error
            try:
                return self._repository.mark_ready(
                    source_id,
                    superseded_source_id=(
                        replaced.summary.id if replaced is not None else None
                    ),
                )
            except SourcePersistenceError as error:
                durable = await self._reconcile_accept_persistence(
                    workspace_id=workspace_id,
                    dataset_id=dataset_id,
                    source=source,
                    replaced=replaced,
                    outcome=error.outcome,
                )
                if durable is not None:
                    return durable
                raise

    async def _reconcile_accept_persistence(
        self,
        *,
        workspace_id: UUID,
        dataset_id: str,
        source: SourceExternalRef,
        replaced: SourceExternalRef | None,
        outcome: SourcePersistenceOutcome,
    ) -> SourceSummary | None:
        durable: SourceExternalRef | None = None
        accepted = False
        if outcome is SourcePersistenceOutcome.UNKNOWN_OR_COMMITTED:
            try:
                durable = self._repository.get_historical_for_workspace(
                    workspace_id, source.summary.id
                )
                durable_replaced = (
                    self._repository.get_historical_for_workspace(
                        workspace_id, replaced.summary.id
                    )
                    if replaced is not None
                    else None
                )
            except SourcePersistenceError:
                try:
                    await self._run_reconciliation_to_completion(
                        self._align_accept_remote(
                            dataset_id=dataset_id,
                            source=source,
                            replaced=replaced,
                            accepted=False,
                        )
                    )
                except Exception as reconciliation_error:
                    raise ExternalSourceServiceError(
                        "Source acceptance reconciliation failed."
                    ) from reconciliation_error
                raise
            accepted = durable is not None and durable.summary.status is SourceStatus.READY
            if replaced is not None:
                accepted = (
                    accepted
                    and durable_replaced is not None
                    and durable_replaced.summary.superseded_at is not None
                )
        await self._run_reconciliation_to_completion(
            self._align_accept_remote(
                dataset_id=dataset_id,
                source=source,
                replaced=replaced,
                accepted=accepted,
            )
        )
        return durable.summary if accepted and durable is not None else None

    async def _align_accept_remote(
        self,
        *,
        dataset_id: str,
        source: SourceExternalRef,
        replaced: SourceExternalRef | None,
        accepted: bool,
    ) -> None:
        if accepted and replaced is not None and replaced.collection_id is not None:
            await self._set_collection_forbidden_confirmed(
                dataset_id=dataset_id,
                source_id=replaced.summary.id,
                collection_id=replaced.collection_id,
                forbidden=True,
            )
        if source.collection_id is not None:
            await self._set_collection_forbidden_confirmed(
                dataset_id=dataset_id,
                source_id=source.summary.id,
                collection_id=source.collection_id,
                forbidden=not accepted,
            )
        if not accepted and replaced is not None and replaced.collection_id is not None:
            await self._set_collection_forbidden_confirmed(
                dataset_id=dataset_id,
                source_id=replaced.summary.id,
                collection_id=replaced.collection_id,
                forbidden=False,
            )

    async def delete(self, workspace_id: UUID, source_id: UUID) -> None:
        async with self._locks.acquire(workspace_id):
            dataset_id = self._repository.get_workspace_dataset_id(workspace_id)
            if dataset_id is None:
                raise SourceNotFoundError
            source = self._repository.get_for_workspace(workspace_id, source_id)
            if source is None:
                raise SourceNotFoundError
            if source.summary.status is SourceStatus.READY and self._repository.has_pending_review(
                workspace_id, source.summary.lineage_id
            ):
                raise SourceLifecycleConflictError("invalid_source_status")
            if source.collection_id is not None:
                try:
                    await self._set_collection_forbidden_confirmed(
                        dataset_id=dataset_id,
                        source_id=source.summary.id,
                        collection_id=source.collection_id,
                        forbidden=True,
                    )
                except asyncio.CancelledError:
                    await self._run_reconciliation_to_completion(
                        self._align_deleted_remote(
                            dataset_id=dataset_id,
                            source=source,
                            deleted=False,
                        )
                    )
                    raise
                except Exception as error:
                    try:
                        await self._align_deleted_remote(
                            dataset_id=dataset_id,
                            source=source,
                            deleted=False,
                        )
                    except Exception as reconciliation_error:
                        raise ExternalSourceServiceError(
                            "Source deletion reconciliation failed."
                        ) from reconciliation_error
                    raise ExternalSourceServiceError("Source deletion failed.") from error
            try:
                self._repository.mark_deleted(source_id)
            except SourcePersistenceError as error:
                deleted = False
                if error.outcome is SourcePersistenceOutcome.UNKNOWN_OR_COMMITTED:
                    durable = self._repository.get_historical_for_workspace(
                        workspace_id, source_id
                    )
                    deleted = (
                        durable is not None and durable.summary.deleted_at is not None
                    )
                await self._align_deleted_remote(
                    dataset_id=dataset_id,
                    source=source,
                    deleted=deleted,
                )
                if deleted:
                    return
                raise

    async def _align_deleted_remote(
        self,
        *,
        dataset_id: str,
        source: SourceExternalRef,
        deleted: bool,
    ) -> None:
        if source.collection_id is None:
            return
        await self._set_collection_forbidden_confirmed(
            dataset_id=dataset_id,
            source_id=source.summary.id,
            collection_id=source.collection_id,
            forbidden=deleted or source.summary.status is not SourceStatus.READY,
        )

    async def processed_preview(
        self, workspace_id: UUID, source_id: UUID
    ) -> ProcessedPreviewResponse:
        source = self._repository.get_for_workspace(workspace_id, source_id)
        if source is None:
            raise SourceNotFoundError
        if source.collection_id is None:
            raise SourcePreviewUnavailableError
        try:
            chunks = await self._fastgpt.list_collection_data(
                source.collection_id, page_size=PROCESSED_PREVIEW_LIMIT
            )
        except Exception as error:
            raise ExternalSourceServiceError("Processed preview failed.") from error
        return _processed_preview(source.summary, chunks)


def _collection_id(collection: object) -> str:
    collection_id = getattr(collection, "collection_id", None)
    if not isinstance(collection_id, str) or not collection_id:
        raise ExternalSourceServiceError("Source ingestion failed.")
    return collection_id


def source_marker(source_id: UUID) -> str:
    digest = hashlib.sha256(b"grounded-tutor-source-v1:" + source_id.bytes).hexdigest()[:32]
    return f"{REMOTE_MARKER_PREFIX}{digest}"


def _remote_collection_name(name: str, source_type: SourceType, marker: str) -> str:
    prefix = f"{marker}{REMOTE_NAME_SEPARATOR}"
    if source_type is SourceType.FILE:
        path = Path(name)
        suffix = path.suffix.lower()
        available = REMOTE_NAME_MAX_LENGTH - len(prefix) - len(suffix)
        return f"{prefix}{path.stem[:available]}{suffix}"
    return f"{prefix}{name[: REMOTE_NAME_MAX_LENGTH - len(prefix)]}"


def _has_exact_marker(item: CollectionListItem, marker: str) -> bool:
    return marker in item.tags or item.name.startswith(
        f"{marker}{REMOTE_NAME_SEPARATOR}"
    )


def _processed_preview(
    source: SourceSummary, chunks: list[ProcessedChunk]
) -> ProcessedPreviewResponse:
    return ProcessedPreviewResponse(
        source_id=source.id,
        source_name=source.name,
        items=[
            _processed_preview_item(index, chunk)
            for index, chunk in enumerate(chunks[:PROCESSED_PREVIEW_LIMIT], start=1)
        ],
        limit=PROCESSED_PREVIEW_LIMIT,
    )


def _processed_preview_item(
    position: int, chunk: ProcessedChunk
) -> ProcessedPreviewItemResponse:
    q, q_truncated = _public_preview_text(chunk.q)
    a, a_truncated = _public_preview_text(chunk.a)
    return ProcessedPreviewItemResponse(
        position=position,
        q=q,
        a=a,
        q_truncated=q_truncated,
        a_truncated=a_truncated,
    )


def _public_preview_text(value: str) -> tuple[str, bool]:
    sanitized = "".join(
        character
        for character in value
        if character.isprintable() or character in {"\n", "\r", "\t"}
    )
    return (
        sanitized[:MAX_PUBLIC_PROCESSED_FIELD_CHARS],
        len(sanitized) > MAX_PUBLIC_PROCESSED_FIELD_CHARS,
    )


def _validate_text(name: str, text: str, max_text_bytes: int) -> None:
    if not name or len(name) > 255:
        raise PreviewError("invalid_source_name")
    if len(text.encode("utf-8")) > max_text_bytes:
        raise PreviewError("text_too_large")
    if not text.strip():
        raise PreviewError("empty_source")


def _validate_file(filename: str, content: bytes, max_upload_bytes: int) -> str:
    if len(content) > max_upload_bytes:
        raise PreviewError("file_too_large")
    safe_name = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    if not 1 <= len(safe_name) <= 255:
        raise PreviewError("invalid_source_name")
    path = Path(safe_name)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS or not path.stem:
        raise PreviewError("unsupported_file_type")
    if not content:
        raise PreviewError("empty_source")
    return safe_name
