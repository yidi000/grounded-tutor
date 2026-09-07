from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from grounded_tutor.adapters.fastgpt import FastGPTClient
from grounded_tutor.config import Settings
from grounded_tutor.db import create_database_engine
from grounded_tutor.domain.ingestion import ChunkSettings
from grounded_tutor.domain.models import Base, Workspace
from grounded_tutor.repositories.sources import SourceRepository
from grounded_tutor.services.source_locks import WorkspaceLockRegistry
from grounded_tutor.services.sources import SourceService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_INTEGRATION") != "1",
    reason="set RUN_LIVE_INTEGRATION=1 with local credentials",
)

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.mark.asyncio
async def test_live_office_formats_have_processed_data(tmp_path: Path) -> None:
    await _probe_formats(
        tmp_path,
        [("slides.pptx", "slides.pptx"), ("workbook.xlsx", "workbook.xlsx")],
        supports_image_files=False,
    )


@pytest.mark.asyncio
async def test_live_enabled_image_format_has_processed_data(tmp_path: Path) -> None:
    settings = Settings()
    if not settings.supports_image_files:
        pytest.skip("deployment image-file support is not enabled")
    await _probe_formats(
        tmp_path,
        [("diagram.png", "diagram.png")],
        supports_image_files=True,
    )


async def _probe_formats(
    tmp_path: Path,
    formats: list[tuple[str, str]],
    *,
    supports_image_files: bool,
) -> None:
    settings = Settings()
    api_key = settings.fastgpt_api_key.get_secret_value()
    if not api_key:
        pytest.fail("FASTGPT_API_KEY is required for opted-in live tests")
    client = FastGPTClient(settings.fastgpt_base_url, api_key)
    dataset = None
    engine = create_database_engine(
        Settings(database_url=f"sqlite:///{tmp_path / 'source-formats.db'}")
    )
    Base.metadata.create_all(engine)
    try:
        dataset = await client.create_dataset(f"Grounded Tutor format probe {uuid4()}")
        with Session(engine, expire_on_commit=False) as session:
            workspace = Workspace(
                title="Format compatibility probe",
                dataset_id=dataset.dataset_id,
            )
            session.add(workspace)
            session.commit()
            service = SourceService(
                SourceRepository(session),
                client,
                WorkspaceLockRegistry(),
                max_upload_bytes=settings.max_upload_bytes,
                max_text_bytes=settings.max_preview_text_bytes,
                max_extracted_characters=settings.max_extracted_characters,
                supports_image_files=supports_image_files,
            )
            for filename, fixture in formats:
                result = await service.ingest_file(
                    workspace_id=workspace.id,
                    filename=filename,
                    content=(FIXTURES / fixture).read_bytes(),
                    settings=ChunkSettings(),
                )
                preview = result.processed_preview
                # Collection creation can return before processed data is readable.
                for _ in range(30):
                    if any(item.q.strip() or item.a.strip() for item in preview.items):
                        break
                    await asyncio.sleep(2)
                    preview = await service.processed_preview(workspace.id, result.source.id)
                assert any(item.q.strip() or item.a.strip() for item in preview.items), (
                    f"{filename}: no nonblank processed data after 30 preview refreshes"
                )
    finally:
        try:
            if dataset is not None:
                await client.delete_dataset(dataset.dataset_id)
        finally:
            await client.aclose()
            engine.dispose()
