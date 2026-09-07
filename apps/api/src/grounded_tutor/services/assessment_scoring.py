"""Deterministic grading shared by diagnostics and immediate checks."""

import unicodedata


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def is_correct(kind: str, response: str, keys: list[str]) -> bool:
    if kind == "single_choice":
        return response in keys
    # ponytail: exact short alternatives; semantic paraphrase grading is deferred.
    return normalize(response) in {normalize(key) for key in keys}
