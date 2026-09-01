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
from grounded_tutor.adapters.generation import GeneratedAnswer, GeneratedClaim, GenerationPort

__all__ = [
    "CollectionRef",
    "DatasetRef",
    "ExternalServiceError",
    "FastGPTClient",
    "FastGPTPort",
    "GeneratedAnswer",
    "GeneratedClaim",
    "GenerationPort",
    "ProcessedChunk",
    "RetrievedChunk",
    "SearchRequest",
]
