"""Generation-service contract used by the tutor workflow."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from grounded_tutor.adapters.fastgpt import RetrievedChunk


@dataclass(frozen=True, slots=True)
class GeneratedClaim:
    text: str
    chunk_ids: list[str]


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    answer: str
    claims: list[GeneratedClaim]


class GenerationPort(Protocol):
    async def generate_answer(
        self, question: str, chunks: Sequence[RetrievedChunk]
    ) -> GeneratedAnswer: ...
