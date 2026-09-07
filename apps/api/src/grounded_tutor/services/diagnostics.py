"""Consent-gated, grounded diagnostic lifecycle for the single-worker P0."""

import hashlib
import json
import unicodedata
from uuid import uuid5

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from grounded_tutor.adapters.fastgpt import SearchRequest
from grounded_tutor.adapters.generation import InvalidGenerationOutput
from grounded_tutor.domain.answers import GeneratedAnswer, GeneratedBlock
from grounded_tutor.domain.diagnostics import (
    DiagnosticAnswerResult,
    DiagnosticConceptResult,
    DiagnosticQuestionView,
    DiagnosticSummary,
    DiagnosticView,
    GeneratedDiagnostic,
)
from grounded_tutor.domain.models import (
    ActivityState,
    Assessment,
    Attempt,
    Diagnostic,
    DiagnosticQuestion,
    LearnerProfile,
    RequestRecord,
    Workspace,
)
from grounded_tutor.repositories.chat import ChatPersistenceError, ChatRepository
from grounded_tutor.repositories.sources import SourceRepository
from grounded_tutor.services.grounding import ReadyChunk, ground_generated_answer


class DiagnosticNotFoundError(RuntimeError):
    pass


class DiagnosticConflictError(RuntimeError):
    pass


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


class DiagnosticService:
    def __init__(self, session, fastgpt, generation, locks):
        self.session = session
        self.fastgpt = fastgpt
        self.generation = generation
        self.locks = locks
        self.sources = SourceRepository(session)
        self.requests = ChatRepository(session)

    async def _write(self, workspace_id, operation, payload, result_type, action):
        async with self.locks.acquire(workspace_id):
            if self.session.get(Workspace, workspace_id) is None:
                raise DiagnosticNotFoundError()
            key = (
                "diagnostic:"
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

    async def start(self, workspace_id, request):
        async def create():
            diagnostic_id = request.invitation_id or uuid5(workspace_id, request.idempotency_key)
            existing = self.session.get(Diagnostic, diagnostic_id)
            if existing is not None:
                if (existing.workspace_id, existing.goal, existing.background) != (
                    workspace_id,
                    request.goal,
                    request.background,
                ):
                    raise DiagnosticConflictError()
                return self.get(workspace_id, diagnostic_id)
            state = self.session.get(ActivityState, workspace_id)
            if state and (state.active_mode != "ASK" or state.suspended_activity):
                raise DiagnosticConflictError()
            if request.invitation_id:
                invitation = state.diagnostic_invitation if state else None
                if (
                    not invitation
                    or invitation["id"] != str(request.invitation_id)
                    or invitation["status"] == "dismissed"
                ):
                    raise DiagnosticConflictError()
            sources = self.sources.ready_collection_ids(workspace_id)
            if not sources:
                return DiagnosticView(status="insufficient_material")
            dataset = self.session.get(Workspace, workspace_id).dataset_id
            self.session.rollback()  # No SQLite transaction during provider I/O.
            chunks = await self.fastgpt.search(SearchRequest(dataset, request.goal))
            ready = {}
            for position, chunk in enumerate(chunks, 1):
                if chunk.collection_id in sources and chunk.chunk_id not in ready:
                    ready[chunk.chunk_id] = ReadyChunk(
                        chunk, sources[chunk.collection_id], position
                    )
            if not ready:
                return DiagnosticView(status="insufficient_material")
            generated = None
            grounded = []
            for _ in range(2):
                try:
                    candidate = await self.generation.generate_diagnostic(
                        request.goal, request.background, tuple(r.chunk for r in ready.values())
                    )
                    candidate = GeneratedDiagnostic.model_validate(candidate.model_dump())
                    grounded = []
                    for question in candidate.questions:
                        answer = ground_generated_answer(
                            GeneratedAnswer(
                                blocks=(
                                    GeneratedBlock(
                                        id=question.id,
                                        kind="explanation",
                                        text=question.explanation,
                                        chunk_ids=question.chunk_ids,
                                    ),
                                )
                            ),
                            ready,
                            allowed_kinds={"explanation"},
                        )
                        evidence = normalize(" ".join(c.excerpt for c in answer.citations))
                        if answer.status != "ok" or any(
                            normalize(key) not in evidence for key in question.answer_key
                        ):
                            raise ValueError("Ungrounded key")
                        grounded.append(answer)
                    generated = candidate
                    break
                except (InvalidGenerationOutput, ValueError):
                    continue
            if generated is None:
                return DiagnosticView(status="insufficient_material")
            self.session.expire_all()
            current = self.sources.ready_collection_ids(workspace_id)
            if any(current.get(r.chunk.collection_id) != r.source for r in ready.values()):
                return DiagnosticView(status="insufficient_material")
            state = self.session.get(ActivityState, workspace_id)
            if state and (state.active_mode != "ASK" or state.suspended_activity):
                raise DiagnosticConflictError()
            if request.invitation_id and (
                not state
                or not state.diagnostic_invitation
                or state.diagnostic_invitation["id"] != str(request.invitation_id)
                or state.diagnostic_invitation["status"] == "dismissed"
            ):
                raise DiagnosticConflictError()
            diagnostic = Diagnostic(
                id=diagnostic_id,
                workspace_id=workspace_id,
                goal=request.goal,
                background=request.background,
            )
            self.session.add(diagnostic)
            self.session.flush()
            for order, (question, answer) in enumerate(zip(generated.questions, grounded), 1):
                assessment = Assessment(
                    workspace_id=workspace_id,
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
                    DiagnosticQuestion(
                        assessment_id=assessment.id,
                        diagnostic_id=diagnostic_id,
                        workspace_id=workspace_id,
                        order=order,
                        concept_label=question.concept_label,
                    )
                )
            if state is None:
                state = ActivityState(workspace_id=workspace_id)
                self.session.add(state)
            state.active_mode = "CHECK"
            state.active_concept_id = None
            state.return_checkpoint = f"diagnostic:{diagnostic_id}:question:1"
            if request.invitation_id:
                state.diagnostic_invitation = {**state.diagnostic_invitation, "status": "accepted"}
            profile = self.session.get(LearnerProfile, workspace_id)
            if profile is None:
                profile = LearnerProfile(workspace_id=workspace_id, confirmed_fields={})
                self.session.add(profile)
            profile.confirmed_fields = {
                **profile.confirmed_fields,
                "goal": request.goal,
                **({"background": request.background} if request.background is not None else {}),
            }
            self.session.flush()
            return self.get(workspace_id, diagnostic_id)

        return await self._write(workspace_id, "start:", request, DiagnosticView, create)

    def _record(self, workspace_id, diagnostic_id):
        diagnostic = self.session.get(Diagnostic, diagnostic_id)
        if diagnostic is None or diagnostic.workspace_id != workspace_id:
            raise DiagnosticNotFoundError()
        return diagnostic

    def _questions(self, diagnostic_id):
        return list(
            self.session.scalars(
                select(DiagnosticQuestion)
                .where(DiagnosticQuestion.diagnostic_id == diagnostic_id)
                .order_by(DiagnosticQuestion.order)
            )
        )

    def get(self, workspace_id, diagnostic_id):
        diagnostic = self._record(workspace_id, diagnostic_id)
        links = self._questions(diagnostic_id)
        questions = []
        for link in links:
            assessment = self.session.get(Assessment, link.assessment_id)
            questions.append(
                DiagnosticQuestionView(
                    question_id=assessment.id,
                    kind=assessment.kind,
                    prompt=assessment.prompt,
                    options=assessment.options,
                    concept_label=link.concept_label,
                    evidence_refs=assessment.evidence_refs,
                    citations=assessment.citations,
                )
            )
        return DiagnosticView(
            status=diagnostic.status,
            diagnostic_id=diagnostic.id,
            questions=tuple(questions),
            next_question_id=next((q.assessment_id for q in links if q.attempt_id is None), None),
        )

    async def answer(self, workspace_id, diagnostic_id, request):
        async def record():
            diagnostic = self._record(workspace_id, diagnostic_id)
            links = self._questions(diagnostic_id)
            link = next((q for q in links if q.attempt_id is None), None)
            state = self.session.get(ActivityState, workspace_id)
            if (
                link is None
                or link.assessment_id != request.question_id
                or not state
                or state.active_mode != "CHECK"
                or state.return_checkpoint != f"diagnostic:{diagnostic_id}:question:{link.order}"
            ):
                raise DiagnosticConflictError()
            assessment = self.session.get(Assessment, link.assessment_id)
            if (
                not request.skip
                and assessment.kind == "single_choice"
                and request.response not in assessment.options
            ):
                raise DiagnosticConflictError()
            # ponytail: exact normalized short-answer alternatives; semantic grading is deferred.
            correct = not request.skip and (
                request.response in assessment.answer_key
                if assessment.kind == "single_choice"
                else normalize(request.response) in {normalize(k) for k in assessment.answer_key}
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
            next_link = next((q for q in links if q.attempt_id is None), None)
            if next_link:
                state.return_checkpoint = f"diagnostic:{diagnostic_id}:question:{next_link.order}"
            else:
                diagnostic.status = "completed"
                state.active_mode = "ASK"
                state.return_checkpoint = f"diagnostic:{diagnostic_id}:completed"
            return DiagnosticAnswerResult(
                attempt_id=attempt.id,
                result=result,
                completed=next_link is None,
                next_question_id=next_link.assessment_id if next_link else None,
                feedback_blocks=() if request.skip else assessment.feedback_blocks,
                citations=() if request.skip else assessment.citations,
            )

        return await self._write(
            workspace_id, f"answer:{diagnostic_id}:", request, DiagnosticAnswerResult, record
        )

    def summary(self, workspace_id, diagnostic_id):
        diagnostic = self._record(workspace_id, diagnostic_id)
        concepts = {}
        for link in self._questions(diagnostic_id):
            attempt = self.session.get(Attempt, link.attempt_id) if link.attempt_id else None
            result = attempt.result if attempt and attempt.result else "not_assessed"
            old = concepts.get(link.concept_label)
            # A concept is understood only when all its questions were answered correctly.
            priority = {"understood": 0, "not_assessed": 1, "needs_review": 2}
            if old is None or priority[result] > priority[old]:
                concepts[link.concept_label] = result
        return DiagnosticSummary(
            status=diagnostic.status,
            concepts=tuple(
                DiagnosticConceptResult(concept_label=label, result=result)
                for label, result in concepts.items()
            ),
        )
