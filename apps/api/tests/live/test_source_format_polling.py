from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import test_source_formats_live as live


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["immediate", "delayed", "empty", "error"])
async def test_format_probe_waits_for_data_without_reingesting(
    tmp_path, monkeypatch, outcome
) -> None:
    monkeypatch.setenv("FASTGPT_API_KEY", "test-key")
    empty = SimpleNamespace(items=[])
    ready = SimpleNamespace(items=[SimpleNamespace(q="Slide content", a="")])
    client = AsyncMock()
    client.create_dataset.return_value = SimpleNamespace(dataset_id="dataset-test")
    service = AsyncMock()
    source_id = uuid4()
    service.ingest_file.return_value = SimpleNamespace(
        source=SimpleNamespace(id=source_id),
        processed_preview=ready if outcome == "immediate" else empty,
    )
    service.processed_preview.return_value = empty
    if outcome == "delayed":
        service.processed_preview.side_effect = [empty, ready]
    elif outcome == "error":
        service.processed_preview.side_effect = RuntimeError("preview unavailable")
    monkeypatch.setattr(live, "FastGPTClient", lambda *args: client)
    monkeypatch.setattr(live, "SourceService", lambda *args, **kwargs: service)
    sleep = AsyncMock()
    monkeypatch.setattr("asyncio.sleep", sleep)

    async def probe():
        await live._probe_formats(
            tmp_path, [("slides.pptx", "slides.pptx")], supports_image_files=False
        )

    if outcome == "empty":
        with pytest.raises(AssertionError, match="slides.pptx"):
            await probe()
        assert service.processed_preview.await_count == 30
    elif outcome == "error":
        with pytest.raises(RuntimeError, match="preview unavailable"):
            await probe()
        assert service.processed_preview.await_count == 1
    else:
        await probe()
        assert service.processed_preview.await_count == (2 if outcome == "delayed" else 0)
    service.ingest_file.assert_awaited_once()
    client.create_dataset.assert_awaited_once()
    client.delete_dataset.assert_awaited_once_with("dataset-test")
    client.aclose.assert_awaited_once()
    assert sleep.await_count == service.processed_preview.await_count
