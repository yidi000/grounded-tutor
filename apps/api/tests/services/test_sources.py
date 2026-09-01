from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from grounded_tutor.adapters.fakes import FakeCollection, FakeFastGPT
from grounded_tutor.adapters.fastgpt import DatasetRef, ExternalServiceError
from grounded_tutor.config import Settings
from grounded_tutor.db import create_database_engine
from grounded_tutor.domain.ingestion import ChunkSettings
from grounded_tutor.domain.models import Base, Source, SourceStatus, SourceType, Workspace
from grounded_tutor.repositories.sources import SourceRepository
from grounded_tutor.services.source_locks import WorkspaceIngestionBusyError, WorkspaceLockRegistry
from grounded_tutor.services.sources import (
    ExternalSourceServiceError,
    SourceService,
    source_marker,
)


@pytest.fixture
def source_engine(tmp_path: Path):
    engine = create_database_engine(Settings(database_url=f"sqlite:///{tmp_path / 'sources.db'}"))
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def source_context(source_engine) -> tuple[Callable[[], Session], FakeFastGPT, Workspace, SourceService]:
    def session_factory() -> Session:
        return Session(source_engine, expire_on_commit=False)

    with session_factory() as session:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        session.add(workspace)
        session.commit()
        session.refresh(workspace)

    fake = FakeFastGPT()
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    session = session_factory()
    service = SourceService(
        SourceRepository(session),
        fake,
        WorkspaceLockRegistry(),
        max_upload_bytes=20_000_000,
        max_text_bytes=20_000_000,
    )
    try:
        yield session_factory, fake, workspace, service
    finally:
        session.close()


@pytest.mark.asyncio
async def test_new_collection_is_disabled_until_acceptance(source_context) -> None:
    _, fake, workspace, service = source_context

    result = await service.ingest_text(
        workspace_id=workspace.id,
        name="week-1",
        text="Mean is an average.",
        settings=ChunkSettings(),
    )

    assert result.source.status is SourceStatus.REVIEW
    assert result.source.source_type is SourceType.TEXT
    assert fake.set_collection_forbidden_calls == [("collection-1", True)]
    assert fake.list_collection_data_calls == [("collection-1", 30)]
    assert result.processed_preview.items[0].q == "Mean is an average."
    assert result.processed_preview.authority == "actual"
    marker = source_marker(result.source.id)
    assert fake.call_history == [
        ("create_text_collection", "dataset-statistics", f"{marker}--week-1"),
        ("set_collection_forbidden", "collection-1", True),
        ("list_collections", "dataset-statistics", 0, 30, marker),
        ("list_collection_data", "collection-1", 30),
    ]


@pytest.mark.asyncio
async def test_file_ingestion_forwards_original_bytes_and_canonical_config(source_context) -> None:
    _, fake, workspace, service = source_context
    content = b"%PDF-binary-original"
    settings = ChunkSettings.model_validate(
        {
            "trainingType": "qa",
            "indexPrefixTitle": False,
            "customPdfParse": True,
            "chunkSettingMode": "custom",
            "chunkSplitMode": "size",
            "chunkSize": 600,
            "indexSize": 120,
            "chunkSplitter": "",
            "qaPrompt": "Generate grounded pairs.",
        }
    )

    result = await service.ingest_file(
        workspace_id=workspace.id,
        filename="course.pdf",
        content=content,
        settings=settings,
    )

    dataset_id, filename, sent_content, config = fake.create_file_collection_calls[0]
    marker = source_marker(result.source.id)
    assert (dataset_id, filename, sent_content) == (
        "dataset-statistics",
        f"{marker}--course.pdf",
        content,
    )
    assert config == {**settings.model_dump(by_alias=True), "tags": [marker]}
    assert "datasetId" not in config
    assert "collectionId" not in config
    assert result.source.ingestion_config == settings.model_dump(by_alias=True)
    assert result.source.name == "course.pdf"


@pytest.mark.asyncio
async def test_failure_before_collection_persists_retryable_failed_source(source_context) -> None:
    session_factory, fake, workspace, service = source_context
    fake.failures["create_text_collection"] = ExternalServiceError(
        service="fastgpt", category="timeout", safe_message="private remote detail"
    )
    settings = ChunkSettings(trainingType="qa", qaPrompt="retry me")

    with pytest.raises(ExternalSourceServiceError):
        await service.ingest_text(
            workspace_id=workspace.id,
            name="notes",
            text="Mean.",
            settings=settings,
        )

    with session_factory() as session:
        source = session.scalar(select(Source))
    assert source is not None
    assert source.status is SourceStatus.FAILED
    assert source.collection_id is None
    assert source.ingestion_config == settings.model_dump(by_alias=True)
    assert source.error_message == "Source ingestion failed."
    assert "private" not in source.error_message


@pytest.mark.asyncio
async def test_failure_after_collection_keeps_exact_collection_forbidden(source_context) -> None:
    session_factory, fake, workspace, service = source_context
    fake.failures["list_collection_data"] = RuntimeError("secret content and api-key")

    with pytest.raises(ExternalSourceServiceError):
        await service.ingest_text(
            workspace_id=workspace.id,
            name="notes",
            text="Mean.",
            settings=ChunkSettings(),
        )

    with session_factory() as session:
        source = session.scalar(select(Source))
    assert source is not None
    assert source.status is SourceStatus.FAILED
    assert source.collection_id == "collection-1"
    assert fake.collections["collection-1"].forbidden is True
    assert fake.set_collection_forbidden_calls == [
        ("collection-1", True),
        ("collection-1", True),
    ]
    assert "secret" not in (source.error_message or "")


@pytest.mark.asyncio
async def test_same_workspace_ingestion_is_rejected_without_waiting(
    source_engine,
) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        setup.add(workspace)
        setup.commit()
        setup.refresh(workspace)

    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingFake(FakeFastGPT):
        async def create_text_collection(self, dataset_id, name, text, config):
            entered.set()
            await release.wait()
            return await super().create_text_collection(dataset_id, name, text, config)

    fake = BlockingFake()
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    locks = WorkspaceLockRegistry()
    first_session = Session(source_engine, expire_on_commit=False)
    second_session = Session(source_engine, expire_on_commit=False)
    first = SourceService(SourceRepository(first_session), fake, locks)
    second = SourceService(SourceRepository(second_session), fake, locks)
    try:
        active = asyncio.create_task(
            first.ingest_text(
                workspace_id=workspace.id,
                name="first",
                text="Mean.",
                settings=ChunkSettings(),
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=1)
        with pytest.raises(WorkspaceIngestionBusyError):
            await asyncio.wait_for(
                second.ingest_text(
                    workspace_id=workspace.id,
                    name="second",
                    text="Median.",
                    settings=ChunkSettings(),
                ),
                timeout=0.1,
            )
        release.set()
        await active
    finally:
        first_session.close()
        second_session.close()

    assert locks.active_count == 0
    assert len(fake.create_text_collection_calls) == 1


@pytest.mark.asyncio
async def test_different_workspaces_may_ingest_concurrently(source_engine) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspaces = [
            Workspace(title="Statistics", dataset_id="dataset-statistics"),
            Workspace(title="Calculus", dataset_id="dataset-calculus"),
        ]
        setup.add_all(workspaces)
        setup.commit()
        for workspace in workspaces:
            setup.refresh(workspace)

    both_entered = asyncio.Event()
    release = asyncio.Event()
    entered: set[str] = set()

    class BlockingFake(FakeFastGPT):
        async def create_text_collection(self, dataset_id, name, text, config):
            entered.add(dataset_id)
            if len(entered) == 2:
                both_entered.set()
            await release.wait()
            return await super().create_text_collection(dataset_id, name, text, config)

    fake = BlockingFake()
    for workspace in workspaces:
        fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    locks = WorkspaceLockRegistry()
    sessions = [Session(source_engine, expire_on_commit=False) for _ in workspaces]
    services = [SourceService(SourceRepository(session), fake, locks) for session in sessions]
    try:
        tasks = [
            asyncio.create_task(
                service.ingest_text(
                    workspace_id=workspace.id,
                    name=workspace.title,
                    text="Content.",
                    settings=ChunkSettings(),
                )
            )
            for service, workspace in zip(services, workspaces, strict=True)
        ]
        await asyncio.wait_for(both_entered.wait(), timeout=1)
        release.set()
        await asyncio.gather(*tasks)
    finally:
        for session in sessions:
            session.close()

    assert locks.active_count == 0
    assert entered == {"dataset-statistics", "dataset-calculus"}


@pytest.mark.asyncio
async def test_cancellation_releases_workspace_lock(source_engine) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        setup.add(workspace)
        setup.commit()
        setup.refresh(workspace)

    entered = asyncio.Event()

    class NeverReturnsFake(FakeFastGPT):
        async def create_text_collection(self, dataset_id, name, text, config):
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    fake = NeverReturnsFake()
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    locks = WorkspaceLockRegistry()
    session = Session(source_engine, expire_on_commit=False)
    service = SourceService(SourceRepository(session), fake, locks)
    try:
        task = asyncio.create_task(
            service.ingest_text(
                workspace_id=workspace.id,
                name="notes",
                text="Mean.",
                settings=ChunkSettings(),
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        session.close()

    assert locks.active_count == 0


@pytest.mark.asyncio
async def test_ambiguous_indexing_commit_is_conservatively_marked_failed(
    source_engine,
) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        setup.add(workspace)
        setup.commit()
        setup.refresh(workspace)

    class FirstAfterCommitFails(Session):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.failed = False
            sqlalchemy_event.listen(self, "after_commit", self._fail_once)

        def _fail_once(self, session) -> None:
            if not self.failed:
                self.failed = True
                raise SQLAlchemyError("ambiguous private database detail")

    fake = FakeFastGPT()
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    session = FirstAfterCommitFails(bind=source_engine, expire_on_commit=False)
    service = SourceService(SourceRepository(session), fake, WorkspaceLockRegistry())
    try:
        with pytest.raises(Exception) as caught:
            await service.ingest_text(
                workspace_id=workspace.id,
                name="notes",
                text="Mean.",
                settings=ChunkSettings(),
            )
    finally:
        session.close()

    assert caught.type.__name__ == "SourcePersistenceError"
    assert fake.call_history == []
    with Session(source_engine) as check:
        source = check.scalar(select(Source))
    assert source is not None
    assert source.status is SourceStatus.FAILED
    assert source.error_message == "Source ingestion failed."


@pytest.mark.asyncio
async def test_collection_id_flush_failure_leaves_remote_disabled_and_local_failed(
    source_engine,
) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        setup.add(workspace)
        setup.commit()
        setup.refresh(workspace)

    class CollectionFlushFailsOnce(Session):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.failed = False
            self.source_flush_calls = 0

        def flush(self, objects=None) -> None:
            if any(isinstance(instance, Source) for instance in self.new | self.dirty):
                self.source_flush_calls += 1
            if self.source_flush_calls == 2 and not self.failed:
                self.failed = True
                raise SQLAlchemyError("private collection write detail")
            super().flush(objects)

    fake = FakeFastGPT()
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    session = CollectionFlushFailsOnce(bind=source_engine, expire_on_commit=False)
    service = SourceService(SourceRepository(session), fake, WorkspaceLockRegistry())
    try:
        with pytest.raises(Exception) as caught:
            await service.ingest_text(
                workspace_id=workspace.id,
                name="notes",
                text="Mean.",
                settings=ChunkSettings(),
            )
    finally:
        session.close()

    assert caught.type.__name__ == "SourcePersistenceError"
    assert fake.collections["collection-1"].forbidden is True
    assert fake.set_collection_forbidden_calls == [
        ("collection-1", True),
        ("collection-1", True),
    ]
    with Session(source_engine) as check:
        source = check.scalar(select(Source))
    assert source is not None
    assert source.status is SourceStatus.FAILED
    assert source.collection_id == "collection-1"


@pytest.mark.asyncio
async def test_forbid_and_compensation_failures_return_safe_failure_state(
    source_context,
) -> None:
    session_factory, fake, workspace, service = source_context
    fake.set_collection_forbidden = AsyncMock(
        side_effect=RuntimeError("collection-1 private api-key")
    )

    with pytest.raises(ExternalSourceServiceError) as caught:
        await service.ingest_text(
            workspace_id=workspace.id,
            name="notes",
            text="Mean.",
            settings=ChunkSettings(),
        )

    assert "private" not in str(caught.value)
    with session_factory() as session:
        source = session.scalar(select(Source))
    assert source is not None
    assert source.status is SourceStatus.FAILED
    assert source.collection_id == "collection-1"
    assert fake.set_collection_forbidden.await_count == 2


@pytest.mark.asyncio
async def test_initial_source_add_failure_never_calls_fastgpt(source_engine) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        setup.add(workspace)
        setup.commit()
        setup.refresh(workspace)

    class SourceAddFails(Session):
        def add(self, instance, _warn: bool = True) -> None:
            if isinstance(instance, Source):
                raise SQLAlchemyError("private add detail")
            super().add(instance, _warn=_warn)

    fake = FakeFastGPT()
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    session = SourceAddFails(bind=source_engine, expire_on_commit=False)
    service = SourceService(SourceRepository(session), fake, WorkspaceLockRegistry())
    try:
        with pytest.raises(Exception) as caught:
            await service.ingest_text(
                workspace_id=workspace.id,
                name="notes",
                text="Mean.",
                settings=ChunkSettings(),
            )
    finally:
        session.close()

    assert caught.type.__name__ == "SourcePersistenceError"
    assert fake.call_history == []
    with Session(source_engine) as check:
        assert check.scalar(select(Source)) is None


@pytest.mark.asyncio
async def test_review_flush_failure_is_recovered_to_failed(source_engine) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        setup.add(workspace)
        setup.commit()
        setup.refresh(workspace)

    class ReviewFlushFailsOnce(Session):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.source_flush_calls = 0

        def flush(self, objects=None) -> None:
            if any(isinstance(instance, Source) for instance in self.new | self.dirty):
                self.source_flush_calls += 1
            if self.source_flush_calls == 3:
                self.source_flush_calls += 1
                raise SQLAlchemyError("private review detail")
            super().flush(objects)

    fake = FakeFastGPT()
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    session = ReviewFlushFailsOnce(bind=source_engine, expire_on_commit=False)
    service = SourceService(SourceRepository(session), fake, WorkspaceLockRegistry())
    try:
        with pytest.raises(Exception) as caught:
            await service.ingest_text(
                workspace_id=workspace.id,
                name="notes",
                text="Mean.",
                settings=ChunkSettings(),
            )
    finally:
        session.close()

    assert caught.type.__name__ == "SourcePersistenceError"
    assert fake.collections["collection-1"].forbidden is True
    with Session(source_engine) as check:
        source = check.scalar(select(Source))
    assert source is not None
    assert source.status is SourceStatus.FAILED
    assert source.collection_id == "collection-1"


@pytest.mark.asyncio
async def test_failed_transition_db_error_does_not_expose_external_error(source_engine) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        setup.add(workspace)
        setup.commit()
        setup.refresh(workspace)

    class FailedTransitionFlushFails(Session):
        def flush(self, objects=None) -> None:
            if any(
                isinstance(instance, Source) and instance.status is SourceStatus.FAILED
                for instance in self.dirty
            ):
                raise SQLAlchemyError("private failed transition detail")
            super().flush(objects)

    fake = FakeFastGPT()
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    fake.failures["create_text_collection"] = RuntimeError("external private material")
    session = FailedTransitionFlushFails(bind=source_engine, expire_on_commit=False)
    service = SourceService(SourceRepository(session), fake, WorkspaceLockRegistry())
    try:
        with pytest.raises(Exception) as caught:
            await service.ingest_text(
                workspace_id=workspace.id,
                name="notes",
                text="Mean.",
                settings=ChunkSettings(),
            )
    finally:
        session.close()

    assert caught.type.__name__ == "SourcePersistenceError"
    assert "private" not in str(caught.value)
    assert fake.collections == {}


@pytest.mark.asyncio
async def test_remote_create_then_timeout_reconciles_enabled_orphan(source_engine) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        setup.add(workspace)
        setup.commit()
        setup.refresh(workspace)

    class CommitThenTimeout(FakeFastGPT):
        async def create_text_collection(self, dataset_id, name, text, config):
            await super().create_text_collection(dataset_id, name, text, config)
            raise ExternalServiceError(
                service="fastgpt",
                category="timeout",
                safe_message="FastGPT request failed.",
            )

    fake = CommitThenTimeout()
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    session = Session(source_engine, expire_on_commit=False)
    service = SourceService(SourceRepository(session), fake, WorkspaceLockRegistry())
    try:
        with pytest.raises(ExternalSourceServiceError):
            await service.ingest_text(
                workspace_id=workspace.id,
                name="notes",
                text="Mean.",
                settings=ChunkSettings(),
            )
    finally:
        session.close()

    assert len(fake.collections) == 1
    remote = next(iter(fake.collections.values()))
    assert remote.forbidden is True
    with Session(source_engine) as check:
        source = check.scalar(select(Source))
    assert source is not None
    assert source.status is SourceStatus.FAILED
    assert source.collection_id is not None
    assert source.name == "notes"


@pytest.mark.asyncio
async def test_remote_create_then_cancellation_reconciles_enabled_orphan(source_engine) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        setup.add(workspace)
        setup.commit()
        setup.refresh(workspace)

    committed = asyncio.Event()

    class CommitThenBlock(FakeFastGPT):
        async def create_text_collection(self, dataset_id, name, text, config):
            await super().create_text_collection(dataset_id, name, text, config)
            committed.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    fake = CommitThenBlock()
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    session = Session(source_engine, expire_on_commit=False)
    service = SourceService(SourceRepository(session), fake, WorkspaceLockRegistry())
    try:
        task = asyncio.create_task(
            service.ingest_text(
                workspace_id=workspace.id,
                name="notes",
                text="Mean.",
                settings=ChunkSettings(),
            )
        )
        await asyncio.wait_for(committed.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        session.close()

    assert len(fake.collections) == 1
    assert next(iter(fake.collections.values())).forbidden is True
    with Session(source_engine) as check:
        source = check.scalar(select(Source))
    assert source is not None
    assert source.status is SourceStatus.FAILED
    assert source.collection_id is not None


@pytest.mark.asyncio
async def test_name_marker_recovers_when_collection_tags_are_omitted(source_engine) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        setup.add(workspace)
        setup.commit()
        setup.refresh(workspace)

    class CommitThenMalformed(FakeFastGPT):
        async def create_text_collection(self, dataset_id, name, text, config):
            await super().create_text_collection(dataset_id, name, text, config)
            raise ExternalServiceError(
                service="fastgpt",
                category="malformed_response",
                safe_message="FastGPT returned a malformed response.",
            )

    fake = CommitThenMalformed()
    fake.supports_tags = False
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    session = Session(source_engine, expire_on_commit=False)
    service = SourceService(SourceRepository(session), fake, WorkspaceLockRegistry())
    try:
        with pytest.raises(ExternalSourceServiceError):
            await service.ingest_text(
                workspace_id=workspace.id,
                name="notes",
                text="Mean.",
                settings=ChunkSettings(),
            )
    finally:
        session.close()

    remote = next(iter(fake.collections.values()))
    assert remote.tags == ()
    assert remote.forbidden is True
    with Session(source_engine) as check:
        source = check.scalar(select(Source))
    assert source is not None
    assert source.collection_id == "collection-1"


@pytest.mark.asyncio
async def test_reconciliation_ignores_wrong_dataset_and_near_marker_matches(
    source_engine,
) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        setup.add(workspace)
        setup.commit()
        setup.refresh(workspace)

    class AddsDecoysThenTimesOut(FakeFastGPT):
        async def create_text_collection(self, dataset_id, name, text, config):
            ref = await super().create_text_collection(dataset_id, name, text, config)
            marker = name.split("--", maxsplit=1)[0]
            self.collections["near-match"] = FakeCollection(
                dataset_id=dataset_id,
                name=f"{marker}x--near",
                content="near",
                config={},
                chunks=[],
                tags=(f"{marker}x",),
            )
            self.collections["wrong-dataset"] = FakeCollection(
                dataset_id="dataset-other",
                name=name,
                content="wrong",
                config={},
                chunks=[],
                tags=(marker,),
            )
            assert ref.collection_id == "collection-1"
            raise ExternalServiceError(
                service="fastgpt",
                category="timeout",
                safe_message="FastGPT request failed.",
            )

    fake = AddsDecoysThenTimesOut()
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    fake.datasets["dataset-other"] = DatasetRef("dataset-other")
    session = Session(source_engine, expire_on_commit=False)
    service = SourceService(SourceRepository(session), fake, WorkspaceLockRegistry())
    try:
        with pytest.raises(ExternalSourceServiceError):
            await service.ingest_text(
                workspace_id=workspace.id,
                name="notes",
                text="Mean.",
                settings=ChunkSettings(),
            )
    finally:
        session.close()

    assert fake.collections["collection-1"].forbidden is True
    assert fake.collections["near-match"].forbidden is False
    assert fake.collections["wrong-dataset"].forbidden is False
    assert all(
        call[0] == "dataset-statistics" for call in fake.list_collections_calls
    )


@pytest.mark.asyncio
async def test_multiple_exact_matches_are_all_disabled_and_local_id_is_ambiguous(
    source_engine,
) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        setup.add(workspace)
        setup.commit()
        setup.refresh(workspace)

    class DuplicatesThenTimesOut(FakeFastGPT):
        async def create_text_collection(self, dataset_id, name, text, config):
            await super().create_text_collection(dataset_id, name, text, config)
            marker = name.split("--", maxsplit=1)[0]
            self.collections["collection-duplicate"] = FakeCollection(
                dataset_id=dataset_id,
                name=f"{marker}--duplicate",
                content="duplicate",
                config=dict(config),
                chunks=[],
                tags=(marker,),
            )
            raise ExternalServiceError(
                service="fastgpt",
                category="timeout",
                safe_message="FastGPT request failed.",
            )

    fake = DuplicatesThenTimesOut()
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    session = Session(source_engine, expire_on_commit=False)
    service = SourceService(SourceRepository(session), fake, WorkspaceLockRegistry())
    try:
        with pytest.raises(ExternalSourceServiceError):
            await service.ingest_text(
                workspace_id=workspace.id,
                name="notes",
                text="Mean.",
                settings=ChunkSettings(),
            )
    finally:
        session.close()

    assert fake.collections["collection-1"].forbidden is True
    assert fake.collections["collection-duplicate"].forbidden is True
    with Session(source_engine) as check:
        source = check.scalar(select(Source))
    assert source is not None
    assert source.status is SourceStatus.FAILED
    assert source.collection_id is None
    assert source.error_message == (
        "Source ingestion failed; multiple remote matches require review."
    )


@pytest.mark.asyncio
async def test_reconciliation_paginates_to_exact_match(source_engine) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        setup.add(workspace)
        setup.commit()
        setup.refresh(workspace)

    class PaginatesThenTimesOut(FakeFastGPT):
        async def create_text_collection(self, dataset_id, name, text, config):
            marker = name.split("--", maxsplit=1)[0]
            for index in range(30):
                self.collections[f"near-{index}"] = FakeCollection(
                    dataset_id=dataset_id,
                    name=f"{marker}x--near-{index}",
                    content="near",
                    config={},
                    chunks=[],
                )
            await super().create_text_collection(dataset_id, name, text, config)
            raise ExternalServiceError(
                service="fastgpt",
                category="timeout",
                safe_message="FastGPT request failed.",
            )

    fake = PaginatesThenTimesOut()
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    session = Session(source_engine, expire_on_commit=False)
    service = SourceService(SourceRepository(session), fake, WorkspaceLockRegistry())
    try:
        with pytest.raises(ExternalSourceServiceError):
            await service.ingest_text(
                workspace_id=workspace.id,
                name="notes",
                text="Mean.",
                settings=ChunkSettings(),
            )
    finally:
        session.close()

    assert fake.list_collections_calls == [
        ("dataset-statistics", 0, 30, fake.list_collections_calls[0][3]),
        ("dataset-statistics", 30, 30, fake.list_collections_calls[0][3]),
    ]
    assert fake.collections["collection-1"].forbidden is True


@pytest.mark.asyncio
async def test_persistent_list_outage_fails_locally_without_claiming_remote_disable(
    source_engine,
) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        setup.add(workspace)
        setup.commit()
        setup.refresh(workspace)

    class CommitThenTimeoutWithListOutage(FakeFastGPT):
        async def create_text_collection(self, dataset_id, name, text, config):
            await super().create_text_collection(dataset_id, name, text, config)
            raise ExternalServiceError(
                service="fastgpt",
                category="timeout",
                safe_message="FastGPT request failed.",
            )

        async def list_collections(self, *args, **kwargs):
            raise ExternalServiceError(
                service="fastgpt",
                category="network",
                safe_message="FastGPT request failed.",
            )

    fake = CommitThenTimeoutWithListOutage()
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    session = Session(source_engine, expire_on_commit=False)
    service = SourceService(SourceRepository(session), fake, WorkspaceLockRegistry())
    try:
        with pytest.raises(ExternalSourceServiceError):
            await service.ingest_text(
                workspace_id=workspace.id,
                name="notes",
                text="Mean.",
                settings=ChunkSettings(),
            )
    finally:
        session.close()

    assert fake.collections["collection-1"].forbidden is False
    with Session(source_engine) as check:
        source = check.scalar(select(Source))
    assert source is not None
    assert source.status is SourceStatus.FAILED
    assert source.collection_id is None
    assert source.error_message == (
        "Source ingestion failed; remote reconciliation could not be completed."
    )


@pytest.mark.asyncio
async def test_persistent_forbid_failure_never_transitions_to_review(source_engine) -> None:
    with Session(source_engine, expire_on_commit=False) as setup:
        workspace = Workspace(title="Statistics", dataset_id="dataset-statistics")
        setup.add(workspace)
        setup.commit()
        setup.refresh(workspace)

    class ForbidOutage(FakeFastGPT):
        async def set_collection_forbidden(self, collection_id, forbidden):
            raise ExternalServiceError(
                service="fastgpt",
                category="network",
                safe_message="FastGPT request failed.",
            )

    fake = ForbidOutage()
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)
    session = Session(source_engine, expire_on_commit=False)
    service = SourceService(SourceRepository(session), fake, WorkspaceLockRegistry())
    try:
        with pytest.raises(ExternalSourceServiceError):
            await service.ingest_text(
                workspace_id=workspace.id,
                name="notes",
                text="Mean.",
                settings=ChunkSettings(),
            )
    finally:
        session.close()

    assert fake.collections["collection-1"].forbidden is False
    with Session(source_engine) as check:
        source = check.scalar(select(Source))
    assert source is not None
    assert source.status is SourceStatus.FAILED
    assert source.collection_id == "collection-1"
    assert source.error_message == (
        "Source ingestion failed; remote disable could not be confirmed."
    )
