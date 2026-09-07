from uuid import uuid4

from grounded_tutor.domain.models import ActivityState
from grounded_tutor.services.diagnostic_invites import DiagnosticInvitation


def test_invitation_read_dismiss_and_workspace_scope(client, seeded_workspace, api_session_factory):
    card = DiagnosticInvitation(conversation_id=uuid4(), message_id=uuid4())
    with api_session_factory() as session:
        session.add(
            ActivityState(
                workspace_id=seeded_workspace.id, diagnostic_invitation=card.model_dump(mode="json")
            )
        )
        session.commit()
    url = f"/api/workspaces/{seeded_workspace.id}/diagnostics/invitation"
    assert client.get(url).json() == card.model_dump(mode="json")
    assert client.post(f"{url}/{uuid4()}/dismiss").status_code == 409
    assert client.post(f"{url}/{card.id}/dismiss").json()["status"] == "dismissed"
    assert client.post(f"{url}/{card.id}/dismiss").status_code == 200
    assert client.get(url).json()["status"] == "dismissed"
    assert client.get(f"/api/workspaces/{uuid4()}/diagnostics/invitation").status_code == 404
