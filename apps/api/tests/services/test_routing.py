import pytest
from pydantic import ValidationError

from grounded_tutor.services.routing import ClassifierObservation, RoutePolicy


@pytest.mark.parametrize(
    ("event", "activity", "expected"),
    [
        ("START_DIAGNOSTIC", None, "CHECK"),
        ("CONTINUE_CHECK", "CHECK", "CHECK"),
        ("ASK_QUESTION", "LEARN", "ASK"),
        (None, None, "ASK"),
        (None, "CHECK", "CHECK"),
        ("CONTINUE_LEARNING", "CHECK", "LEARN"),
        (None, "LEARN", "LEARN"),
    ],
)
def test_route_precedence(event, activity, expected):
    assert (
        RoutePolicy().choose(event=event, active_mode=activity, classified_intent="unrelated")
        == expected
    )


@pytest.mark.parametrize(
    "intent", ["CHECK", "START_DIAGNOSTIC", "rebuild_plan", "new_workspace", "network", "learning"]
)
def test_classifier_cannot_authorize_high_impact_actions(intent):
    assert RoutePolicy().choose(event=None, active_mode=None, classified_intent=intent) == "ASK"


def test_unrelated_topic_is_only_a_bounded_suggestion():
    policy = RoutePolicy()
    suggestion = policy.workspace_suggestion(
        ClassifierObservation(intent="unrelated", proposed_title="Linear Algebra")
    )
    assert suggestion.type == "suggest_new_workspace"
    assert suggestion.proposed_title == "Linear Algebra"
    with pytest.raises(ValidationError):
        ClassifierObservation(intent="unrelated", proposed_title="x" * 121)
    with pytest.raises(ValidationError):
        ClassifierObservation(intent="learning", execute="CHECK")
