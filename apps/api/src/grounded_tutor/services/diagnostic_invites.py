"""Optional diagnostic invitations, independent of question generation (Task 3)."""

import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import literal_column, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from grounded_tutor.domain.answers import SimpleSuggestedAction, SuggestedAction
from grounded_tutor.domain.models import (
    ActivityState,
    Conversation,
    LearnerProfile,
    Message,
    Workspace,
)
from grounded_tutor.services.routing import ClassifierObservation, RoutePolicy

EXPLICIT_LEARNING = re.compile(
    r"我是新手|我不理解|我不懂|怎么学|如何学|学习路径|学习计划|测验|测测我|测试一下|"
    r"\bi['’]?m new\b|\bi am new\b|\bi (?:don['’]?t|do not) understand\b|"
    r"how (?:should|can|do) i learn|learning (?:plan|path)|\b(?:quiz|test) me\b",
    re.IGNORECASE,
)
FOUNDATION = re.compile(r"什么是|是什么意思|解释|\bwhat (?:is|are)\b|\bexplain\b", re.IGNORECASE)
DECLINE = re.compile(r"不要.*(?:测验|诊断)|不是新手|\bdon['’]?t.*(?:quiz|test)\b", re.IGNORECASE)
INVITE_ACTIONS = (SimpleSuggestedAction(type="start_diagnostic"),)


class DiagnosticInvitation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    message_id: UUID
    status: Literal["offered", "dismissed", "accepted"] = "offered"
    accept_label: Literal["开始诊断"] = "开始诊断"
    dismiss_label: Literal["继续提问"] = "继续提问"


class InvitePersistenceError(RuntimeError):
    def __init__(self):
        super().__init__("Diagnostic invitation persistence failed.")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class DiagnosticInviteService:
    def __init__(self, session: Session):
        self._session = session

    @contextmanager
    def _transaction(self):
        if self._session.new or self._session.dirty or self._session.deleted:
            raise ValueError("Invitation operations require a settled transaction")
        failed = False
        try:
            # ponytail: P0 SQLite serializes the short read/update transaction. No
            # providers run under this lock; replace with row locking for PostgreSQL.
            self._session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            self._session.expire_all()
            yield
            self._session.commit()
        except SQLAlchemyError:
            self._rollback()
            failed = True
        except ValueError:
            self._rollback()
            raise
        if failed:
            raise InvitePersistenceError()

    def _rollback(self):
        try:
            self._session.rollback()
        except SQLAlchemyError:
            self._session.close()

    def current(self, workspace_id: UUID) -> DiagnosticInvitation | None:
        failed = False
        try:
            state = self._session.get(ActivityState, workspace_id, populate_existing=True)
            return (
                DiagnosticInvitation.model_validate(state.diagnostic_invitation)
                if (state and state.diagnostic_invitation)
                else None
            )
        except SQLAlchemyError:
            self._rollback()
            failed = True
        if failed:
            raise InvitePersistenceError()

    def suggest(
        self,
        workspace_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        *,
        observation: ClassifierObservation | None = None,
        now: datetime | None = None,
    ) -> tuple[SuggestedAction, ...]:
        with self._transaction():
            conversation = self._session.get(Conversation, conversation_id)
            if conversation is None or conversation.workspace_id != workspace_id:
                return ()
            message = self._session.get(Message, message_id)
            if (
                message is None
                or message.conversation_id != conversation_id
                or message.role != "assistant"
            ):
                return ()
            state = self._session.get(ActivityState, workspace_id)
            if state and (state.active_mode != "ASK" or state.suspended_activity):
                return ()
            messages = list(
                self._session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id, Message.mode == "ask")
                    .order_by(literal_column("messages.rowid").desc())
                    .limit(4)
                )
            )
            latest_workspace_message = self._session.scalar(
                select(Message.id)
                .join(Conversation)
                .where(
                    Conversation.workspace_id == workspace_id,
                    Message.mode == "ask",
                    Message.role == "assistant",
                )
                .order_by(literal_column("messages.rowid").desc())
                .limit(1)
            )
            is_latest = (
                len(messages) >= 2
                and messages[0].id == message_id
                and messages[1].role == "user"
                and latest_workspace_message == message_id
            )
            question = messages[1].content if is_latest else ""
            explicit = bool(EXPLICIT_LEARNING.search(question)) and not DECLINE.search(question)
            if observation and is_latest:
                self._save_observation(workspace_id, observation)
                suggestion = RoutePolicy.workspace_suggestion(observation)
                if observation.intent == "unrelated" and not explicit:
                    return (suggestion,) if suggestion else ()
            card = self.current(workspace_id)
            now = _utc(now or datetime.now(UTC))
            if card and card.status == "offered" and card.message_id != message_id and is_latest:
                state.diagnostic_invitation = card.model_copy(
                    update={"status": "dismissed"}
                ).model_dump(mode="json")
                state.nudge_cooldown_until = now + timedelta(hours=24)
                return ()
            if card and card.status in {"offered", "accepted"}:
                return (
                    INVITE_ACTIONS
                    if card.status == "offered" and card.message_id == message_id
                    else ()
                )
            if state and state.nudge_cooldown_until and _utc(state.nudge_cooldown_until) > now:
                return ()
            if not is_latest or message.content == "insufficient_material" or not message.citations:
                return ()
            if DECLINE.search(question):
                return ()
            related = False
            if (
                len(messages) == 4
                and messages[2].role == "assistant"
                and messages[3].role == "user"
            ):
                prior = messages[3].content
                current_chunks = {c.get("chunk_id") for c in message.citations}
                prior_chunks = {c.get("chunk_id") for c in messages[2].citations}
                related = bool(
                    FOUNDATION.search(question)
                    and FOUNDATION.search(prior)
                    and question.strip().casefold() != prior.strip().casefold()
                    and (current_chunks & prior_chunks) - {None}
                )
            if not (explicit or related):
                return ()
            if state is None:
                state = ActivityState(workspace_id=workspace_id)
                self._session.add(state)
            state.diagnostic_invitation = DiagnosticInvitation(
                conversation_id=conversation_id, message_id=message_id
            ).model_dump(mode="json")
            return INVITE_ACTIONS

    def dismiss(self, workspace_id: UUID, invitation_id: UUID, *, now: datetime | None = None):
        with self._transaction():
            card = self._require_card(workspace_id, invitation_id)
            if card.status == "accepted":
                raise ValueError("Accepted invitation cannot be dismissed")
            if card.status == "dismissed":
                return card
            card = card.model_copy(update={"status": "dismissed"})
            state = self._session.get(ActivityState, workspace_id)
            state.diagnostic_invitation = card.model_dump(mode="json")
            state.nudge_cooldown_until = _utc(now or datetime.now(UTC)) + timedelta(hours=24)
            return card

    def accept(self, workspace_id: UUID, invitation_id: UUID, *, consent: bool):
        if consent is not True:
            raise ValueError("Explicit consent is required")
        with self._transaction():
            card = self._require_card(workspace_id, invitation_id)
            if card.status == "dismissed":
                raise ValueError("Dismissed invitation cannot be accepted")
            card = card.model_copy(update={"status": "accepted"})
            self._session.get(ActivityState, workspace_id).diagnostic_invitation = card.model_dump(
                mode="json"
            )
            # Task 3 uses this stable consent ID to create/replay one diagnostic.
            return card

    def _require_card(self, workspace_id, invitation_id):
        card = self.current(workspace_id)
        if card is None or card.id != invitation_id:
            raise ValueError("Invitation not found")
        return card

    def _profile(self, workspace_id):
        if self._session.get(Workspace, workspace_id) is None:
            raise ValueError("Workspace not found")
        profile = self._session.get(LearnerProfile, workspace_id)
        if profile is None:
            profile = LearnerProfile(
                workspace_id=workspace_id, inferred_fields={}, confirmed_fields={}
            )
            self._session.add(profile)
        return profile

    def _save_observation(self, workspace_id, observation):
        profile = self._profile(workspace_id)
        profile.inferred_fields = {
            **profile.inferred_fields,
            **observation.model_dump(exclude_none=True),
        }

    def record_observation(self, workspace_id: UUID, observation: ClassifierObservation):
        with self._transaction():
            self._save_observation(workspace_id, observation)

    def confirm_profile(self, workspace_id: UUID, *, goal: str, background: str | None = None):
        if (
            not goal.strip()
            or len(goal) > 2000
            or (background is not None and len(background) > 2000)
        ):
            raise ValueError("Invalid confirmed profile")
        with self._transaction():
            profile = self._profile(workspace_id)
            values = {"goal": goal.strip()}
            if background is not None:
                values["background"] = background.strip()
            profile.confirmed_fields = {**profile.confirmed_fields, **values}
