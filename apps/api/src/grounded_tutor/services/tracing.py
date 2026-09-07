from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from grounded_tutor.domain.models import BadCase, ExecutionTrace

_SENSITIVE_KEYS = (
    "authorization",
    "api_key",
    "token",
    "secret",
    "cookie",
    "header",
    "exception",
    "traceback",
    "error_message",
    "raw_response",
)
_CATEGORIES = {
    "external_failure": "external_failure",
    "external_service_error": "external_failure",
    "citation_failure": "citation_failure",
    "citation_validation_failed": "citation_failure",
    "wrong_route": "wrong_route",
    "unexpected_exception": "unexpected_exception",
}


class TracePersistenceError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Trace persistence failed.")


class TraceRecorder:
    """Record after the application transaction has settled, never in its middle."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        workspace_id: UUID,
        request_id: str,
        route: str,
        retrieval: dict | None = None,
        generation: dict | None = None,
        validation: dict | None = None,
        timing: dict | None = None,
        category: str | None = None,
    ) -> ExecutionTrace:
        validation = validation or {}
        if category is None:
            category = next(
                (
                    _CATEGORIES[value]
                    for key in ("outcome", "error_code")
                    if isinstance(value := validation.get(key), str) and value in _CATEGORIES
                ),
                None,
            )
        trace = ExecutionTrace(
            workspace_id=workspace_id,
            request_id=request_id,
            route=route,
            retrieval_json=_redact(retrieval or {}),
            generation_json=_redact(generation or {}),
            validation_json=_redact(validation),
            timing_json=_redact(timing or {}),
        )
        failed = False
        try:
            self._session.add(trace)
            self._session.flush()
            if category is not None:
                self._session.add(BadCase(trace_id=trace.id, category=category))
            self._session.commit()
            self._session.refresh(trace)
        except SQLAlchemyError:
            try:
                self._session.rollback()
            except SQLAlchemyError:
                self._session.close()
            failed = True
        if failed:
            raise TracePersistenceError()
        return trace


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact(item)
            for key, item in value.items()
            if isinstance(key, str) and not any(part in key.lower() for part in _SENSITIVE_KEYS)
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    # Never stringify exception or response objects into durable diagnostics.
    return "[REDACTED]"
