"""Grounded immediate checks with atomic, deterministic progress decisions."""

from uuid import UUID

from grounded_tutor.adapters.generation import InvalidGenerationOutput
from grounded_tutor.domain.answers import GeneratedAnswer, GeneratedBlock
from grounded_tutor.domain.models import Assessment, Attempt, ImmediateCheck, Lesson
from grounded_tutor.domain.teaching import CheckResult, CheckView, GeneratedCheck
from grounded_tutor.services.assessment_scoring import is_correct, normalize
from grounded_tutor.services.grounding import ground_generated_answer
from grounded_tutor.services.learning_context import (
    LearningConflictError,
    LearningContext,
    LearningNotFoundError,
)
from grounded_tutor.services.learning_requests import LearningRequests


def checkpoint_id(checkpoint, prefix):
    if not checkpoint or not checkpoint.startswith(prefix + ":"):
        raise LearningConflictError()
    try:
        return UUID(checkpoint[len(prefix) + 1 :])
    except ValueError:
        raise LearningConflictError() from None


class CheckService:
    def __init__(self, session, fastgpt, generation, locks):
        self.session = session
        self.generation = generation
        self.context = LearningContext(session, fastgpt)
        self.writes = LearningRequests(session, locks, "check", LearningNotFoundError)

    def _record(self, workspace_id, assessment_id):
        link = self.session.get(ImmediateCheck, assessment_id)
        if link is None or link.workspace_id != workspace_id:
            raise LearningNotFoundError()
        assessment = self.session.get(Assessment, assessment_id)
        if assessment.purpose != "immediate_check":
            raise LearningNotFoundError()
        return assessment, link

    def get(self, workspace_id, assessment_id):
        assessment, _ = self._record(workspace_id, assessment_id)
        return CheckView(
            status="ok",
            concept_id=assessment.concept_id,
            assessment_id=assessment.id,
            kind=assessment.kind,
            prompt=assessment.prompt,
            options=assessment.options,
            citations=assessment.citations,
        )

    async def start(self, workspace_id, concept_id, request):
        async def generate():
            concept, state = self.context.require(workspace_id, concept_id, {"LEARN", "CHECK"})
            if state.active_mode == "CHECK":
                assessment, link = self._record(
                    workspace_id, checkpoint_id(state.return_checkpoint, "check")
                )
                if assessment.concept_id != concept_id or link.attempt_id:
                    raise LearningConflictError()
                if not self.context.citations_current(workspace_id, assessment.citations):
                    return CheckView(status="insufficient_material", concept_id=concept_id)
                return self.get(workspace_id, assessment.id)
            lesson_id = checkpoint_id(state.return_checkpoint, "lesson")
            lesson = self.session.get(Lesson, lesson_id)
            if not lesson or lesson.concept_id != concept_id:
                raise LearningConflictError()
            objective, kind = concept.objective, concept.check_kind
            refused = CheckView(status="insufficient_material", concept_id=concept_id)
            ready = await self.context.retrieve(concept)
            if not ready:
                return refused
            question, answer = None, None
            for _ in range(2):
                try:
                    generated = await self.generation.generate_check(
                        objective, kind, tuple(r.chunk for r in ready.values())
                    )
                    candidate = GeneratedCheck.model_validate(generated.model_dump()).question
                    if candidate.kind != kind:
                        raise ValueError("Wrong check kind")
                    grounded = ground_generated_answer(
                        GeneratedAnswer(
                            blocks=(
                                GeneratedBlock(
                                    id=candidate.id,
                                    kind="explanation",
                                    text=candidate.explanation,
                                    chunk_ids=candidate.chunk_ids,
                                ),
                            )
                        ),
                        ready,
                        allowed_kinds={"explanation"},
                    )
                    evidence = normalize(" ".join(c.excerpt for c in grounded.citations))
                    if grounded.status != "ok" or any(
                        normalize(key) not in evidence for key in candidate.answer_key
                    ):
                        raise ValueError("Unsupported check key")
                    question, answer = candidate, grounded
                    break
                except (InvalidGenerationOutput, ValueError):
                    continue
            if question is None or not self.context.fresh(workspace_id, ready):
                return refused
            concept, state = self.context.require(workspace_id, concept_id, {"LEARN"})
            if state.return_checkpoint != f"lesson:{lesson_id}":
                raise LearningConflictError()
            assessment = Assessment(
                workspace_id=workspace_id,
                concept_id=concept_id,
                purpose="immediate_check",
                kind=question.kind,
                prompt=question.prompt,
                options=list(question.options),
                answer_key=list(question.answer_key),
                evidence_refs=[
                    {
                        "source_id": str(c.source_id),
                        "source_version": c.source_version,
                        "chunk_id": c.chunk_id,
                    }
                    for c in answer.citations
                ],
                feedback_blocks=[b.model_dump(mode="json") for b in answer.answer_blocks],
                citations=[c.model_dump(mode="json") for c in answer.citations],
            )
            self.session.add(assessment)
            self.session.flush()
            self.session.add(
                ImmediateCheck(
                    assessment_id=assessment.id, workspace_id=workspace_id, lesson_id=lesson_id
                )
            )
            state.active_mode = "CHECK"
            state.return_checkpoint = f"check:{assessment.id}"
            self.session.flush()
            return self.get(workspace_id, assessment.id)

        return await self.writes.run(
            workspace_id, f"start:{concept_id}:", request, CheckView, generate
        )

    async def submit(self, workspace_id, assessment_id, request):
        async def grade():
            assessment, link = self._record(workspace_id, assessment_id)
            concept, state = self.context.require(workspace_id, assessment.concept_id, {"CHECK"})
            if link.attempt_id or state.return_checkpoint != f"check:{assessment_id}":
                raise LearningConflictError()
            if (
                not request.skip
                and assessment.kind == "single_choice"
                and request.response not in assessment.options
            ):
                raise LearningConflictError()
            if not self.context.citations_current(workspace_id, assessment.citations):
                raise LearningConflictError()
            correct = (
                None
                if request.skip
                else is_correct(assessment.kind, request.response, assessment.answer_key)
            )
            result = (
                "not_assessed" if request.skip else ("understood" if correct else "needs_review")
            )
            attempt = Attempt(
                assessment_id=assessment.id,
                response=request.response,
                result=None if request.skip else result,
                status="not_assessed" if request.skip else "completed",
            )
            self.session.add(attempt)
            self.session.flush()
            link.attempt_id = attempt.id
            if request.skip:
                concept.status = "not_assessed"
                state.return_checkpoint = f"check:{assessment.id}:skipped"
                next_action = "confirm_continue"
            elif correct:
                concept.status = "completed"
                next_action = self.context.advance(concept, state)
            else:
                concept.status = "needs_review"
                state.active_mode = "LEARN"
                state.return_checkpoint = f"lesson:{link.lesson_id}"
                next_action = "review_concept"
            return CheckResult(
                attempt_id=attempt.id,
                result=result,
                correct=correct,
                next_action=next_action,
                active_concept_id=state.active_concept_id,
                explanation_blocks=() if request.skip else assessment.feedback_blocks,
                citations=() if request.skip else assessment.citations,
            )

        return await self.writes.run(
            workspace_id, f"answer:{assessment_id}:", request, CheckResult, grade
        )

    async def continue_after_skip(self, workspace_id, assessment_id, request):
        async def advance():
            assessment, link = self._record(workspace_id, assessment_id)
            concept, state = self.context.require(
                workspace_id, assessment.concept_id, {"CHECK"}, skipped=True
            )
            attempt = self.session.get(Attempt, link.attempt_id) if link.attempt_id else None
            if (
                not attempt
                or attempt.status != "not_assessed"
                or concept.status != "not_assessed"
                or state.return_checkpoint != f"check:{assessment.id}:skipped"
            ):
                raise LearningConflictError()
            if not self.context.citations_current(workspace_id, assessment.citations):
                raise LearningConflictError()
            next_action = self.context.advance(concept, state)
            return CheckResult(
                attempt_id=attempt.id,
                result="not_assessed",
                correct=None,
                next_action=next_action,
                active_concept_id=state.active_concept_id,
            )

        return await self.writes.run(
            workspace_id, f"continue:{assessment_id}:", request, CheckResult, advance
        )
