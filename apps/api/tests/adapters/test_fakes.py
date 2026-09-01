import pytest

from grounded_tutor.adapters.fakes import FakeFastGPT, FakeGeneration
from grounded_tutor.adapters.fastgpt import SearchRequest
from grounded_tutor.adapters.generation import GeneratedAnswer, GeneratedClaim


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
    answer = GeneratedAnswer("The mean is an average.", [GeneratedClaim("mean", ["chunk-1"])])
    fake = FakeGeneration(answer)
    source = FakeFastGPT()
    dataset = await source.create_dataset("Statistics")
    await source.create_text_collection(dataset.dataset_id, "means", "mean", {})
    chunks = await source.search(SearchRequest(dataset.dataset_id, "mean"))

    result = await fake.generate_answer("What is the mean?", chunks)

    assert result == answer
    assert fake.calls == [("What is the mean?", chunks)]
