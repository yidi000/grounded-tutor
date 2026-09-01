"""Generation-service contract used by the tutor workflow."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from grounded_tutor.adapters.fastgpt import RetrievedChunk


@dataclass(frozen=True, slots=True)
class GeneratedClaim:
    text: str
    chunk_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "chunk_ids", tuple(self.chunk_ids))


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    answer: str
    claims: tuple[GeneratedClaim, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "claims", tuple(self.claims))


class GenerationPort(Protocol):
    async def generate_answer(
        self, question: str, chunks: Sequence[RetrievedChunk]
    ) -> GeneratedAnswer: ...
