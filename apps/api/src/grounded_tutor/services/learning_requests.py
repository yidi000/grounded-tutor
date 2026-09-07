"""Atomic replay records and Workspace exclusion shared by learning writes."""

import hashlib
import json

from sqlalchemy.exc import SQLAlchemyError

from grounded_tutor.domain.models import RequestRecord, Workspace
from grounded_tutor.repositories.chat import ChatPersistenceError, ChatRepository


class LearningRequests:
    def __init__(self, session, locks, namespace, not_found):
        self.session = session
        self.locks = locks
        self.namespace = namespace
        self.not_found = not_found
        self.requests = ChatRepository(session)

    async def run(self, workspace_id, operation, payload, result_type, action):
        async with self.locks.acquire(workspace_id):
            if self.session.get(Workspace, workspace_id) is None:
                raise self.not_found()
            key = (
                self.namespace
                + ":"
                + hashlib.sha256((operation + payload.idempotency_key).encode()).hexdigest()
            )
            digest = hashlib.sha256(
                json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode()
            ).hexdigest()
            replay = self.requests.claim_request(workspace_id, key, digest)
            if replay is not None:
                return result_type.model_validate(replay)
            try:
                result = await action()
                record = self.session.get(RequestRecord, (workspace_id, key))
                record.state = "completed"
                record.response_json = result.model_dump(mode="json")
                self.session.commit()
                return result
            except BaseException as error:
                # Completed records survive a lost commit acknowledgement.
                self.requests.release_request(workspace_id, key)
                if isinstance(error, SQLAlchemyError):
                    raise ChatPersistenceError() from None
                raise
