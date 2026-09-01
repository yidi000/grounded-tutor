from __future__ import annotations

from collections.abc import Callable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from grounded_tutor.config import Settings

PREVIEW_REQUEST_OVERHEAD_BYTES = 1_048_576
MAX_PREVIEW_REQUEST_MESSAGES = 4_096


class PreviewRequestBodyLimitMiddleware:
    """Cap preview request bodies before FastAPI parses JSON or multipart data."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings_provider: Callable[[], Settings],
    ) -> None:
        self._app = app
        self._settings_provider = settings_provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        body_limit = self._body_limit(scope)
        if body_limit is None:
            await self._app(scope, receive, send)
            return
        content_length = _content_length(scope)
        if content_length is None and _has_content_length(scope):
            await _send_too_large(scope, receive, send)
            return
        if content_length is not None and content_length > body_limit:
            await _send_too_large(scope, receive, send)
            return

        received_bytes = 0
        request_messages = 0
        messages: list[Message] = []
        while True:
            message = await receive()
            if message["type"] == "http.request":
                request_messages += 1
                if request_messages > MAX_PREVIEW_REQUEST_MESSAGES:
                    await _send_too_large(scope, receive, send)
                    return
                received_bytes += len(message.get("body", b""))
                if received_bytes > body_limit:
                    await _send_too_large(scope, receive, send)
                    return
                messages.append(message)
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                messages.append(message)
                break

        next_message = 0

        async def replay_receive() -> Message:
            nonlocal next_message
            if next_message < len(messages):
                message = messages[next_message]
                next_message += 1
                return message
            return {"type": "http.disconnect"}

        await self._app(scope, replay_receive, send)

    def _body_limit(self, scope: Scope) -> int | None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            return None
        path = scope.get("path", "")
        settings = self._settings_provider()
        if path.endswith("/source-previews/file"):
            content_limit = settings.max_upload_bytes
        elif path.endswith("/source-previews/text"):
            content_limit = settings.max_preview_text_bytes
        else:
            return None
        return content_limit + PREVIEW_REQUEST_OVERHEAD_BYTES


def _has_content_length(scope: Scope) -> bool:
    return any(name.lower() == b"content-length" for name, _ in scope.get("headers", []))


def _content_length(scope: Scope) -> int | None:
    values = [
        value
        for name, value in scope.get("headers", [])
        if name.lower() == b"content-length"
    ]
    if len(values) != 1:
        return None
    try:
        content_length = int(values[0])
    except ValueError:
        return None
    return content_length if content_length >= 0 else None


async def _send_too_large(scope: Scope, receive: Receive, send: Send) -> None:
    response = JSONResponse(
        status_code=413,
        content={"detail": {"code": "request_body_too_large"}},
    )
    await response(scope, receive, send)
