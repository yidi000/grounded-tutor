import pytest

from grounded_tutor.adapters.fakes import FakeFastGPT, FakeGeneration
from grounded_tutor.adapters.fastgpt import RetrievedChunk, SearchRequest
from grounded_tutor.adapters.generation import GenerationRequest
from grounded_tutor.domain.answers import GeneratedAnswer, GeneratedBlock


@pytest.mark.asyncio
async def test_fake_fastgpt_retains_collections_data_forbid_and_deletes_dataset() -> None:
    fake = FakeFastGPT()
    dataset = await fake.create_dataset("Statistics")
    collection = await fake.create_text_collection(
        dataset.dataset_id, "means", "Mean is an average.", {"chunkSize": 256}
    )

    chunks = await fake.list_collection_data(collection.collection_id)
    results = await fake.search(SearchRequest(dataset.dataset_id, "mean"))
    await fake.set_collection_forbidden(collection.collection_id, True)
    assert fake.collections[collection.collection_id].forbidden is True
    await fake.delete_dataset(dataset.dataset_id)

    assert dataset.dataset_id == "dataset-1"
    assert collection.collection_id == "collection-1"
    assert chunks[0].q == "Mean is an average."
    assert results[0].collection_id == collection.collection_id
    assert dataset.dataset_id not in fake.datasets
    assert collection.collection_id not in fake.collections


@pytest.mark.asyncio
async def test_fake_generation_records_calls_and_returns_configured_answer() -> None:
    answer = GeneratedAnswer(
        blocks=(
            GeneratedBlock(
                id="block-1",
                kind="answer",
                text="The mean is an average.",
                chunk_ids=("chunk-1",),
            ),
        )
    )
    fake = FakeGeneration(answer)
    source = FakeFastGPT()
    dataset = await source.create_dataset("Statistics")
    await source.create_text_collection(dataset.dataset_id, "means", "mean", {})
    chunks = await source.search(SearchRequest(dataset.dataset_id, "mean"))

    request = GenerationRequest("ASK", "What is the mean?", tuple(chunks))
    result = await fake.generate_content(request)

    assert result == answer
    assert isinstance(result.blocks, tuple)
    assert isinstance(result.blocks[0].chunk_ids, tuple)
    assert fake.calls == [request]


@pytest.mark.asyncio
async def test_fake_search_ignores_missing_datasets_and_forbidden_collections() -> None:
    fake = FakeFastGPT()
    dataset = await fake.create_dataset("Statistics")
    collection = await fake.create_text_collection(dataset.dataset_id, "means", "mean", {})
    await fake.create_text_collection(dataset.dataset_id, "medians", "median", {})

    assert await fake.search(SearchRequest("missing-dataset", "mean")) == []
    assert len(await fake.search(SearchRequest(dataset.dataset_id, "mean", limit=1))) == 2
    await fake.set_collection_forbidden(collection.collection_id, True)
    assert [
        item.collection_id for item in await fake.search(SearchRequest(dataset.dataset_id, "mean"))
    ] == ["collection-2"]


@pytest.mark.asyncio
async def test_fake_search_results_override_returns_explicit_raw_external_results() -> None:
    fake = FakeFastGPT()
    fake.search_results_override = (
        RetrievedChunk("remote-1", "remote-collection", "remote", "q", "a", 0.9),
    )

    results = await fake.search(SearchRequest("missing-dataset", "question"))

    assert results[0].chunk_id == "remote-1"


@pytest.mark.asyncio
async def test_fake_collection_creation_rejects_unknown_dataset_without_mutating_state() -> None:
    fake = FakeFastGPT()

    with pytest.raises(ValueError, match="dataset"):
        await fake.create_file_collection("missing", "notes.pdf", b"content", {})
    with pytest.raises(ValueError, match="dataset"):
        await fake.create_text_collection("missing", "notes", "content", {})

    assert fake.datasets == {}
    assert fake.collections == {}
    dataset = await fake.create_dataset("Statistics")
    collection = await fake.create_text_collection(dataset.dataset_id, "notes", "content", {})
    assert collection.collection_id == "collection-1"
