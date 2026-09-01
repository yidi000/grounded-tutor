from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from grounded_tutor.db import engine as application_engine
from grounded_tutor.domain.models import Base, Source, SourceStatus, SourceType, Workspace


def test_workspace_and_source_are_isolated() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        workspace = Workspace(title="Statistics", dataset_id="dataset-1")
        session.add(workspace)
        session.flush()
        session.add(
            Source(
                workspace_id=workspace.id,
                name="week-1.pdf",
                source_type=SourceType.FILE,
                status=SourceStatus.REVIEW,
                collection_id="collection-1",
                ingestion_config={"trainingType": "chunk"},
            )
        )
        session.commit()
        stored = session.scalar(select(Source).where(Source.workspace_id == workspace.id))

    assert stored is not None
    assert stored.collection_id == "collection-1"
    assert stored.status is SourceStatus.REVIEW


def test_application_sqlite_engine_enforces_foreign_keys() -> None:
    with application_engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
