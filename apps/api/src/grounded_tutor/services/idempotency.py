"""Canonical request identity; persistence lives with the chat transaction."""

import hashlib
import json
from uuid import UUID


class IdempotencyKeyReused(RuntimeError):
    pass


# ponytail: pending claims never expire automatically; add fenced leases before
# automatic crash recovery, so a slow original request cannot commit after takeover.
class IdempotencyInProgress(RuntimeError):
    pass


def request_hash(message: str, conversation_id: UUID | None) -> str:
    payload = {
        "mode": "ask",
        "message": message,
        "conversation_id": str(conversation_id) if conversation_id else None,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
