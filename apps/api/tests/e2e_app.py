"""Explicit test-only server: deterministic learning content from the test notes."""

from contextlib import asynccontextmanager

from grounded_tutor.adapters.fakes import FakeGeneration
from grounded_tutor.domain.answers import GeneratedAnswer, GeneratedBlock
from grounded_tutor.domain.diagnostics import GeneratedDiagnostic, GeneratedDiagnosticQuestion
from grounded_tutor.domain.plans import GeneratedLearningPlan, GeneratedPlanConcept
from grounded_tutor.domain.teaching import GeneratedCheck
from grounded_tutor.main import app, lifespan


class LearningGeneration(FakeGeneration):
    def question(self, chunk_id, index=1):
        return GeneratedDiagnosticQuestion(
            id=f"q-{index}",
            kind="single_choice",
            prompt=f"Mean numerator? ({index})",
            options=("sum", "product"),
            answer_key=("sum",),
            explanation="Mean uses sum divided by count.",
            concept_label=f"Mean {index}",
            chunk_ids=(chunk_id,),
        )

    async def generate_diagnostic(self, goal, background, chunks):
        return GeneratedDiagnostic(
            questions=tuple(self.question(chunks[0].chunk_id, i) for i in range(1, 4))
        )

    async def generate_plan(self, goal, diagnostic_summary, chunks):
        return GeneratedLearningPlan(
            concepts=tuple(
                GeneratedPlanConcept(
                    title=f"Mean {i}",
                    objective="Explain sum divided by count",
                    chunk_ids=(chunks[0].chunk_id,),
                    check_kind="single_choice",
                )
                for i in range(1, 4)
            )
        )

    async def generate_content(self, request):
        if request.mode == "ASK":
            return await super().generate_content(request)
        return GeneratedAnswer(
            blocks=tuple(
                GeneratedBlock(
                    id=kind,
                    kind=kind,
                    text="Mean uses sum divided by count.",
                    chunk_ids=(request.chunks[0].chunk_id,),
                )
                for kind in ("definition", "explanation", "example")
            )
        )

    async def generate_check(self, objective, kind, chunks):
        return GeneratedCheck(question=self.question(chunks[0].chunk_id))


@asynccontextmanager
async def test_lifespan(application):
    async with lifespan(application):
        application.state.generation = LearningGeneration()
        yield


app.router.lifespan_context = test_lifespan
