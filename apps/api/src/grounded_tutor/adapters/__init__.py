"""Contracts and implementations for external services."""

from grounded_tutor.adapters.fastgpt import (
    CollectionRef,
    DatasetRef,
    ExternalServiceError,
    FastGPTClient,
    FastGPTPort,
    ProcessedChunk,
    RetrievedChunk,
    SearchRequest,
)
from grounded_tutor.adapters.generation import (
    GenerationPort,
    GenerationRequest,
    InvalidGenerationOutput,
    OpenAICompatibleGenerationClient,
)
from grounded_tutor.domain.answers import GeneratedAnswer, GeneratedBlock

__all__ = [
    "CollectionRef",
    "DatasetRef",
    "ExternalServiceError",
    "FastGPTClient",
    "FastGPTPort",
    "GeneratedAnswer",
    "GeneratedBlock",
    "GenerationPort",
    "GenerationRequest",
    "InvalidGenerationOutput",
    "OpenAICompatibleGenerationClient",
    "ProcessedChunk",
    "RetrievedChunk",
    "SearchRequest",
]
