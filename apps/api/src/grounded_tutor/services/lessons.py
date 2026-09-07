"""Persist cited lesson variants before entering or changing LEARN."""

import json

from sqlalchemy import select

from grounded_tutor.adapters.generation import GenerationRequest, InvalidGenerationOutput
from grounded_tutor.domain.answers import GeneratedAnswer
from grounded_tutor.domain.models import LearningPlan, Lesson
from grounded_tutor.domain.teaching import LessonView
from grounded_tutor.services.grounding import ground_generated_answer
from grounded_tutor.services.learning_context import LearningContext, LearningNotFoundError
from grounded_tutor.services.learning_requests import LearningRequests


class LessonService:
    def __init__(self, session, fastgpt, generation, locks):
        self.session = session
        self.generation = generation
        self.context = LearningContext(session, fastgpt)
        self.writes = LearningRequests(session, locks, "lesson", LearningNotFoundError)

    def get(self, workspace_id, lesson_id):
        lesson = self.session.get(Lesson, lesson_id)
        if lesson is None or lesson.workspace_id != workspace_id:
            raise LearningNotFoundError()
        return LessonView(
            status="ok",
            lesson_id=lesson.id,
            concept_id=lesson.concept_id,
            depth=lesson.depth,
            content_blocks=lesson.content_blocks,
            citations=lesson.citations,
        )

    async def start(self, workspace_id, concept_id, request):
        async def generate():
            concept, state = self.context.require(
                workspace_id, concept_id, {"LEARN"}, from_plan=True
            )
            refused = LessonView(
                status="insufficient_material", concept_id=concept_id, depth=request.depth
            )
            lesson = self.session.scalar(
                select(Lesson).where(Lesson.concept_id == concept_id, Lesson.depth == request.depth)
            )
            if lesson:
                if not self.context.citations_current(workspace_id, lesson.citations):
                    return refused
            else:
                instruction = json.dumps(
                    {
                        "title": concept.title,
                        "objective": concept.objective,
                        "depth": request.depth,
                        "format": "Include definition, explanation, and example blocks, each with evidence.",
                    },
                    ensure_ascii=False,
                )
                ready = await self.context.retrieve(concept)
                if not ready:
                    return refused
                answer = None
                for _ in range(2):
                    try:
                        generated = await self.generation.generate_content(
                            GenerationRequest(
                                mode="LEARN",
                                instruction=instruction,
                                chunks=tuple(r.chunk for r in ready.values()),
                            )
                        )
                        generated = GeneratedAnswer.model_validate(generated.model_dump())
                        candidate = ground_generated_answer(
                            generated, ready, allowed_kinds={"definition", "explanation", "example"}
                        )
                        if len(candidate.answer_blocks) != len(generated.blocks) or {
                            b.kind for b in candidate.answer_blocks
                        } != {"definition", "explanation", "example"}:
                            raise ValueError("Incomplete or ungrounded lesson")
                        answer = candidate
                        break
                    except (InvalidGenerationOutput, ValueError):
                        continue
                if answer is None or not self.context.fresh(workspace_id, ready):
                    return refused
                concept, state = self.context.require(
                    workspace_id, concept_id, {"LEARN"}, from_plan=True
                )
                lesson = Lesson(
                    workspace_id=workspace_id,
                    concept_id=concept_id,
                    depth=request.depth,
                    content_blocks=[b.model_dump(mode="json") for b in answer.answer_blocks],
                    citations=[c.model_dump(mode="json") for c in answer.citations],
                )
                self.session.add(lesson)
                self.session.flush()
            if concept.status == "not_started":
                concept.status = "active"
            self.session.get(LearningPlan, concept.plan_id).status = "active"
            state.active_mode = "LEARN"
            state.active_concept_id = concept_id
            state.return_checkpoint = f"lesson:{lesson.id}"
            return self.get(workspace_id, lesson.id)

        return await self.writes.run(workspace_id, f"{concept_id}:", request, LessonView, generate)
