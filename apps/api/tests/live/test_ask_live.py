import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from test_source_formats_live import FIXTURES

from grounded_tutor.adapters.fastgpt import FastGPTClient, RetrievedChunk
from grounded_tutor.adapters.generation import GenerationRequest, OpenAICompatibleGenerationClient
from grounded_tutor.config import Settings
from grounded_tutor.db import create_database_engine
from grounded_tutor.domain.ingestion import ChunkSettings
from grounded_tutor.domain.models import Base, Message, Source, Workspace
from grounded_tutor.repositories.chat import ChatRepository
from grounded_tutor.repositories.sources import SourceRepository
from grounded_tutor.services.chat import ChatService
from grounded_tutor.services.source_locks import WorkspaceLockRegistry
from grounded_tutor.services.sources import SourceService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_INTEGRATION") != "1",
    reason="set RUN_LIVE_INTEGRATION=1 with local credentials",
)


@pytest.mark.asyncio
async def test_live_generator_uses_only_supplied_evidence() -> None:
    settings = Settings()
    assert settings.llm_api_key.get_secret_value(), "LLM_API_KEY is required"
    async with OpenAICompatibleGenerationClient(
        settings.llm_base_url, settings.llm_api_key.get_secret_value(), settings.llm_model
    ) as generation:
        chunks = (RetrievedChunk("probe-1", "probe", "probe", "均值", "均值是总和除以个数。", 1),)
        supported = await generation.generate_content(
            GenerationRequest("ASK", "什么是均值？", chunks)
        )
        assert supported.blocks
        assert all(
            block.kind == "answer" and block.chunk_ids == ("probe-1",) for block in supported.blocks
        )
        unsupported = await generation.generate_content(
            GenerationRequest("ASK", "月球的质量是多少？", chunks)
        )
        assert unsupported.blocks == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "question", "expected"),
    [
        ("slides.pptx", "According to the slides, what do citations connect?", "evidence"),
        ("workbook.xlsx", "What is the score for Mean in the workbook?", "90"),
    ],
)
async def test_live_office_review_to_persisted_cited_ask(
    tmp_path, filename, question, expected
) -> None:
    settings = Settings()
    assert settings.fastgpt_api_key.get_secret_value(), "FASTGPT_API_KEY is required"
    assert settings.llm_api_key.get_secret_value(), "LLM_API_KEY is required"
    engine = create_database_engine(Settings(database_url=f"sqlite:///{tmp_path / 'ask.db'}"))
    Base.metadata.create_all(engine)
    dataset = None
    async with (
        FastGPTClient(
            settings.fastgpt_base_url, settings.fastgpt_api_key.get_secret_value()
        ) as fastgpt,
        OpenAICompatibleGenerationClient(
            settings.llm_base_url, settings.llm_api_key.get_secret_value(), settings.llm_model
        ) as generation,
    ):
        try:
            dataset = await fastgpt.create_dataset(f"Grounded Tutor ASK probe {uuid4()}")
            with Session(engine, expire_on_commit=False) as session:
                workspace = Workspace(title="Live ASK probe", dataset_id=dataset.dataset_id)
                session.add(workspace)
                session.commit()
                sources = SourceRepository(session)
                service = SourceService(
                    sources, fastgpt, WorkspaceLockRegistry(), supports_image_files=False
                )
                chat = ChatService(sources, ChatRepository(session), fastgpt, generation)
                ingested = await service.ingest_file(
                    workspace_id=workspace.id,
                    filename=filename,
                    content=(FIXTURES / filename).read_bytes(),
                    settings=ChunkSettings(),
                )
                before_accept = await chat.ask(workspace.id, question, None, str(uuid4()))
                assert before_accept.answer.status == "insufficient_material"
                assert before_accept.answer.citations == ()
                preview = ingested.processed_preview
                for _ in range(30):
                    if any(item.q.strip() or item.a.strip() for item in preview.items):
                        break
                    await asyncio.sleep(2)
                    preview = await service.processed_preview(workspace.id, ingested.source.id)
                assert any(item.q.strip() or item.a.strip() for item in preview.items)
                await service.accept(workspace.id, ingested.source.id)
                source = session.get(Source, ingested.source.id)
                assert source is not None and source.collection_id is not None
                chunks = await fastgpt.list_collection_data(source.collection_id)
                result = await chat.ask(workspace.id, question, None, str(uuid4()))
                answer = result.answer
                assert answer.status == "ok"
                assert expected in " ".join(block.text for block in answer.answer_blocks).lower()
                assert answer.citations
                citation_ids = {citation.id for citation in answer.citations}
                assert all(
                    set(block.citation_ids) <= citation_ids for block in answer.answer_blocks
                )
                for citation in answer.citations:
                    assert citation.source_id == ingested.source.id
                    assert citation.source_name == filename
                    assert citation.chunk_id in {chunk.chunk_id for chunk in chunks}
                    assert citation.excerpt.strip()
                    # Cloud may merge both slides; ambiguous page markers safely
                    # fall back to a chunk locator instead of claiming one page.
                    allowed_locators = {"pptx", "chunk"} if filename.endswith(".pptx") else {"xlsx"}
                    assert citation.locator.kind in allowed_locators
                    assert "GT_LOCATOR" not in citation.excerpt
                session.expire_all()
                persisted = session.get(Message, result.message_id)
                assert persisted is not None
                assert persisted.citations == [
                    citation.model_dump(mode="json") for citation in answer.citations
                ]
                assert persisted.content_blocks == [
                    block.model_dump(mode="json") for block in answer.answer_blocks
                ]
        finally:
            try:
                if dataset is not None:
                    await fastgpt.delete_dataset(dataset.dataset_id)
            finally:
                engine.dispose()
