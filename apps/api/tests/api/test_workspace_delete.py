import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy import select

from grounded_tutor.domain import models as m


def seed_graph(session, title):
    workspace = m.Workspace(title=title, dataset_id=f'dataset-{title}')
    session.add(workspace)
    session.flush()
    wid = workspace.id
    def add(model, **kwargs):
        row = model(**kwargs)
        session.add(row)
        session.flush()
        return row
    source = add(m.Source, workspace_id=wid, name='old', source_type=m.SourceType.TEXT)
    add(m.Source, workspace_id=wid, name='new', source_type=m.SourceType.TEXT,
        replaces_source_id=source.id, version=2)
    conversation = add(m.Conversation, workspace_id=wid)
    add(m.Message, conversation_id=conversation.id, role='user', mode='ASK', content='Hi')
    add(m.RequestRecord, workspace_id=wid, idempotency_key='key', request_hash='hash', state='completed')
    trace = add(m.ExecutionTrace, workspace_id=wid, request_id='req', route='ASK')
    add(m.BadCase, trace_id=trace.id, category='test')
    plan = add(m.LearningPlan, workspace_id=wid, goal='Learn')
    concept = add(m.Concept, workspace_id=wid, plan_id=plan.id, order=1, title='First', objective='Learn')
    add(m.ActivityState, workspace_id=wid, active_concept_id=concept.id)
    add(m.LearnerProfile, workspace_id=wid)
    assessment = add(m.Assessment, workspace_id=wid, concept_id=concept.id,
                     kind='single_choice', prompt='Question', answer_key=['a'])
    attempt = add(m.Attempt, assessment_id=assessment.id, status='not_assessed')
    diagnostic = add(m.Diagnostic, workspace_id=wid, goal='Learn')
    add(m.DiagnosticQuestion, workspace_id=wid, diagnostic_id=diagnostic.id,
        assessment_id=assessment.id, attempt_id=attempt.id, order=1, concept_label='First')
    add(m.PlanOrigin, workspace_id=wid, plan_id=plan.id, diagnostic_id=diagnostic.id)
    lesson = add(m.Lesson, workspace_id=wid, concept_id=concept.id, depth='standard', content_blocks=[], citations=[])
    add(m.ImmediateCheck, workspace_id=wid, assessment_id=assessment.id, lesson_id=lesson.id, attempt_id=attempt.id)
    session.commit()
    return wid


def test_delete_removes_complete_graph_and_preserves_other_workspace(client, api_session_factory, fake_fastgpt):
    with api_session_factory() as session:
        other = seed_graph(session, 'other')
        expected = {table.name: session.execute(select(table)).all() for table in m.Base.metadata.sorted_tables}
        target = seed_graph(session, 'target')
    response = client.delete(f'/api/workspaces/{target}')
    assert response.status_code == 204
    assert response.content == b''
    assert fake_fastgpt.delete_dataset_calls == ['dataset-target']
    with api_session_factory() as session:
        assert session.get(m.Workspace, target) is None
        assert session.get(m.Workspace, other) is not None
        for table in m.Base.metadata.sorted_tables:
            rows = session.execute(select(table)).all()
            assert rows == expected[table.name], table.name
    assert client.delete(f'/api/workspaces/{target}').status_code == 204
    assert fake_fastgpt.delete_dataset_calls == ['dataset-target']


def test_remote_failure_keeps_local_graph_for_retry(client, api_session_factory, fake_fastgpt):
    with api_session_factory() as session:
        target = seed_graph(session, 'target')
    original = fake_fastgpt.delete_dataset
    fake_fastgpt.delete_dataset = AsyncMock(side_effect=RuntimeError('private credentials'))
    response = client.delete(f'/api/workspaces/{target}')
    assert response.status_code == 502
    assert response.json() == {'detail': {'code': 'external_service_error'}}
    with api_session_factory() as session:
        assert session.get(m.Workspace, target) is not None
        assert len(session.scalars(select(m.Source)).all()) == 2
    fake_fastgpt.delete_dataset = original
    assert client.delete(f'/api/workspaces/{target}').status_code == 204


def test_missing_delete_is_idempotent(client, fake_fastgpt):
    assert client.delete(f'/api/workspaces/{uuid4()}').status_code == 204
    assert fake_fastgpt.delete_dataset_calls == []


def test_delete_respects_shared_workspace_lock(client, seeded_workspace, fake_fastgpt):
    from grounded_tutor import main

    async def request_while_locked():
        async with main.app.state.source_locks.acquire(seeded_workspace.id):
            # TestClient sends the request on its app loop; reserve on that same loop.
            return await asyncio.to_thread(
                client.delete, f'/api/workspaces/{seeded_workspace.id}'
            )

    response = client.portal.call(request_while_locked)
    assert response.status_code == 409
    assert response.json() == {'detail': {'code': 'workspace_ingestion_busy'}}
    assert fake_fastgpt.delete_dataset_calls == []
    assert client.delete(f'/api/workspaces/{seeded_workspace.id}').status_code == 204


def test_local_delete_failure_rolls_back_graph(client, api_session_factory, fake_fastgpt, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import Session

    with api_session_factory() as session:
        target = seed_graph(session, 'target')
    def fail_commit(self):
        raise SQLAlchemyError('private database failure')
    monkeypatch.setattr(Session, 'commit', fail_commit)
    response = client.delete(f'/api/workspaces/{target}')
    assert response.status_code == 500
    assert response.json() == {'detail': {'code': 'persistence_error'}}
    assert fake_fastgpt.delete_dataset_calls == ['dataset-target']
    with api_session_factory() as session:
        assert session.get(m.Workspace, target) is not None
        assert len(session.scalars(select(m.Source)).all()) == 2
        assert len(session.scalars(select(m.ImmediateCheck)).all()) == 1


def test_demo_blocks_workspace_delete(demo_client, fake_fastgpt):
    assert demo_client.delete(f'/api/workspaces/{uuid4()}').status_code == 403
    assert fake_fastgpt.delete_dataset_calls == []


def test_pending_chat_blocks_delete(client, api_session_factory, seeded_workspace, fake_fastgpt):
    with api_session_factory() as session:
        session.add(m.RequestRecord(workspace_id=seeded_workspace.id, idempotency_key='active',
                                    request_hash='hash', state='pending'))
        session.commit()
    response = client.delete(f'/api/workspaces/{seeded_workspace.id}')
    assert response.status_code == 409
    assert fake_fastgpt.delete_dataset_calls == []


def test_retry_after_remote_success_and_local_failure(client, api_session_factory, seeded_workspace, monkeypatch):
    import httpx
    import respx
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import Session

    from grounded_tutor import main
    from grounded_tutor.adapters.fastgpt import FastGPTClient
    from grounded_tutor.dependencies import get_fastgpt

    remote = FastGPTClient('https://fastgpt.test', 'secret')
    main.app.dependency_overrides[get_fastgpt] = lambda: remote
    original_commit = Session.commit
    def fail_commit(self):
        raise SQLAlchemyError('commit failed after remote deletion')
    with respx.mock:
        route = respx.delete('https://fastgpt.test/api/core/dataset/delete').mock(side_effect=[
            httpx.Response(200, json={'code': 200, 'data': None}),
            httpx.Response(500, json={'code': 501002, 'statusText': 'unExistDataset', 'data': None}),
        ])
        monkeypatch.setattr(Session, 'commit', fail_commit)
        assert client.delete(f'/api/workspaces/{seeded_workspace.id}').status_code == 500
        with api_session_factory() as session:
            assert session.get(m.Workspace, seeded_workspace.id) is not None
        monkeypatch.setattr(Session, 'commit', original_commit)
        assert client.delete(f'/api/workspaces/{seeded_workspace.id}').status_code == 204
        assert route.call_count == 2
        with api_session_factory() as session:
            assert session.get(m.Workspace, seeded_workspace.id) is None
    client.portal.call(remote.aclose)
