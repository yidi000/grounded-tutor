# Diagnostic invitation backend

Learning Task 2 adds pure route decisions and optional invitation suggestions to ASK.
It does not yet generate diagnostic questions or add the card UI. The existing
`start_diagnostic` suggested action is returned with a grounded answer and restored
in history while its invitation is offered. Task 3 will expose diagnostic consent
and generation; Task 7 will render the card and its two choices.

Explicit UI events outrank the active activity. Text alone stays in ASK until an
explicit action authorizes another mode. Conservative Chinese/English phrase rules
recognize beginner/confusion, how-to-learn and test requests. Otherwise, invitation
eligibility requires two different foundation questions in the same conversation
with overlapping grounded chunk IDs. This is a deterministic heuristic, not a claim
of semantic understanding. No additional model or network call is made.

`ClassifierObservation` accepts only bounded observation fields. Its unrelated-topic
result can produce a bounded Workspace suggestion; it does not create/switch a
Workspace, rebuild a plan or start CHECK. Explicit learning text takes precedence.
Observations only update `LearnerProfile.inferred_fields`; the separate
`confirm_profile` operation saves explicit goal/background values in confirmed fields.

One invitation is stored in ActivityState with its conversation/message anchor.
`dismiss` or continuing to ask after the offer starts a 24-hour Workspace cooldown.
The latest Workspace message controls changes; replaying an older conversation
cannot dismiss or re-create a newer invitation. Accepted/dismissed cards disappear
from current ASK actions and history. Acceptance requires `consent is True` and
returns the same stable invitation ID on retry. It records consent only: Task 3 must
use this ID to create/replay one diagnostic, including failure recovery, rather than
starting generation unconditionally for every accepted response.

Invitation updates use a short SQLite write transaction after the primary ASK
transaction settles. Provider calls are outside that lock. Failures leave the answer
and message IDs intact; retries can repair a missing optional invitation. Suggested
actions reflect current invitation state, while answer content and citations remain
idempotent. Active lessons/checks and suspended activities suppress new invitations.

Migration `0008_diagnostic_invitation` adds a nullable JSON field and preserves
existing checkpoints. Invitation operations expect a settled Session; future
orchestration must not pass a session with unrelated pending changes.
