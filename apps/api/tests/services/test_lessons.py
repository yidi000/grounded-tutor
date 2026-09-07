from uuid import uuid4

import pytest
from sqlalchemy import select

from grounded_tutor.domain.models import Lesson
from grounded_tutor.domain.teaching import LessonRequest
from grounded_tutor.services.learning_context import LearningConflictError, LearningNotFoundError


@pytest.mark.asyncio
async def test_lesson_is_cited_persisted_and_depth_keeps_concept(learning_tutor):
    t = learning_tutor
    for depth in ("standard", "simpler", "more_examples", "deeper"):
        request = LessonRequest(depth=depth, idempotency_key=depth)
        lesson = await t.lessons.start(t.workspace.id, t.concepts[0].id, request)
        assert lesson.status == "ok" and lesson.concept_id == t.concepts[0].id
        assert {b.kind for b in lesson.content_blocks} == {"definition", "explanation", "example"}
        assert lesson.citations[0].source_name == "Notes"
        assert t.state.active_concept_id == t.concepts[0].id and t.state.active_mode == "LEARN"
        assert await t.lessons.start(t.workspace.id, t.concepts[0].id, request) == lesson
        assert t.lessons.get(t.workspace.id, lesson.lesson_id) == lesson
    assert len(t.generation.calls) == len(t.fastgpt.search_calls) == 4
    assert len(list(t.session.scalars(select(Lesson)))) == 4
    assert all([c.chunk_id for c in call.chunks] == ["chunk"] for call in t.generation.calls)


@pytest.mark.asyncio
async def test_missing_evidence_keeps_previous_checkpoint(learning_tutor):
    t = learning_tutor
    t.generation.responses = [t.lesson.model_copy(update={"blocks": ()})] * 2
    checkpoint = t.state.return_checkpoint
    result = await t.lessons.start(
        t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="bad")
    )
    assert result.status == "insufficient_material"
    assert not list(t.session.scalars(select(Lesson)))
    assert t.state.return_checkpoint == checkpoint and t.concepts[0].status == "not_started"


@pytest.mark.asyncio
async def test_no_foreign_or_out_of_order_lessons(learning_tutor):
    t = learning_tutor
    request = LessonRequest(idempotency_key="lesson")
    with pytest.raises(LearningNotFoundError):
        await t.lessons.start(uuid4(), t.concepts[0].id, request)
    with pytest.raises(LearningConflictError):
        await t.lessons.start(t.workspace.id, t.concepts[1].id, request)
    assert not t.generation.calls and not t.fastgpt.search_calls


@pytest.mark.asyncio
async def test_cached_depth_does_not_regenerate_but_stale_sources_are_refused(learning_tutor):
    from datetime import UTC, datetime

    t = learning_tutor
    original = await t.lessons.start(
        t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="one")
    )
    assert (
        await t.lessons.start(
            t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="two")
        )
        == original
    )
    assert len(t.generation.calls) == 1
    t.source.deleted_at = datetime.now(UTC)
    t.session.commit()
    result = await t.lessons.start(
        t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="stale")
    )
    assert result.status == "insufficient_material" and len(t.generation.calls) == 1
    assert t.lessons.get(t.workspace.id, original.lesson_id) == original


@pytest.mark.asyncio
async def test_source_change_during_lesson_generation_keeps_state(learning_tutor):
    from datetime import UTC, datetime

    t = learning_tutor
    original = t.generation.generate_content

    async def change(request):
        response = await original(request)
        t.source.deleted_at = datetime.now(UTC)
        t.session.commit()
        return response

    t.generation.generate_content = change
    result = await t.lessons.start(
        t.workspace.id, t.concepts[0].id, LessonRequest(idempotency_key="changed")
    )
    assert result.status == "insufficient_material"
    assert t.state.active_mode == "PLAN" and t.concepts[0].status == "not_started"
    assert not list(t.session.scalars(select(Lesson)))


@pytest.mark.asyncio
async def test_generation_cancellation_releases_claim_and_workspace(learning_tutor):
    import asyncio

    from grounded_tutor.domain.models import RequestRecord

    t = learning_tutor
    t.generation.responses = [asyncio.CancelledError(), t.lesson]
    request = LessonRequest(idempotency_key="cancel")
    with pytest.raises(asyncio.CancelledError):
        await t.lessons.start(t.workspace.id, t.concepts[0].id, request)
    assert not list(t.session.scalars(select(RequestRecord)))
    assert (await t.lessons.start(t.workspace.id, t.concepts[0].id, request)).status == "ok"
