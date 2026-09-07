import { z } from "zod";
import { apiFetch } from "./client";
import { CitationSchema, GroundedContentBlockSchema } from "./types";

const id = z.string().uuid();
const result = z.enum(["understood", "needs_review", "not_assessed"]);
const conceptStatus = z.enum(["not_started", "active", "completed", "needs_review", "not_assessed"]);
const depth = z.enum(["standard", "simpler", "more_examples", "deeper"]);
const citations = z.array(CitationSchema);
const blocks = z.array(GroundedContentBlockSchema);
export const InvitationSchema = z.object({ id, conversation_id: id, message_id: id, status: z.enum(["offered", "dismissed", "accepted"]), accept_label: z.string(), dismiss_label: z.string() });
const QuestionSchema = z.object({ question_id: id, kind: z.enum(["single_choice", "structured_short"]), prompt: z.string(), options: z.array(z.string()), concept_label: z.string(), citations });
export const DiagnosticSchema = z.object({ status: z.enum(["active", "completed", "insufficient_material"]), diagnostic_id: id.nullable(), questions: z.array(QuestionSchema), next_question_id: id.nullable() });
export const DiagnosticResultSchema = z.object({ attempt_id: id, result, feedback_blocks: blocks, citations, next_question_id: id.nullable(), completed: z.boolean() });
export const PlanSchema = z.object({ plan_id: id.nullable(), diagnostic_id: id.nullable(), goal: z.string().nullable(), status: z.enum(["not_started", "active", "completed", "superseded", "insufficient_material"]), concepts: z.array(z.object({ id, title: z.string(), objective: z.string(), order: z.number(), status: conceptStatus, evidence_refs: citations })) });
export const LessonSchema = z.object({ status: z.enum(["ok", "insufficient_material"]), concept_id: id, lesson_id: id.nullable(), depth, content_blocks: blocks, citations, available_depths: z.array(depth) });
export const CheckSchema = z.object({ status: z.enum(["ok", "insufficient_material"]), concept_id: id, assessment_id: id.nullable(), kind: z.enum(["single_choice", "structured_short"]).nullable(), prompt: z.string().nullable(), options: z.array(z.string()), citations });
export const CheckResultSchema = z.object({ attempt_id: id, result, correct: z.boolean().nullable(), next_action: z.enum(["next_concept", "review_concept", "confirm_continue", "completed"]), active_concept_id: id.nullable(), explanation_blocks: blocks, citations });
export const ActivitySchema = z.object({
  snapshot: z.object({ active_mode: z.enum(["ASK", "PLAN", "LEARN", "CHECK"]), active_concept_id: z.string().nullable(), checkpoint: z.string().nullable(), suspended_activity: z.object({ mode: z.string(), active_concept_id: z.string().nullable(), checkpoint: z.string().nullable() }).nullable() }),
  check_feedback: z.object({ attempt_id: id, concept_id: id, concept_title: z.string(), result, explanation_blocks: blocks, citations }).nullable().optional(),
  checkpoint: z.string().nullable(), kind: z.enum(["idle", "plan", "diagnostic", "lesson", "concept", "check", "check_skip"]),
  resume_action: z.object({ type: z.literal("resume_activity"), label: z.string(), checkpoint: z.string() }).nullable(),
  concept: z.object({ id, plan_id: id, title: z.string(), objective: z.string(), status: conceptStatus }).nullable(),
  plan: PlanSchema.nullable(), diagnostic: DiagnosticSchema.nullable(), lesson: LessonSchema.nullable(), check: CheckSchema.nullable(),
});
export type Activity = z.infer<typeof ActivitySchema>;
export type Invitation = z.infer<typeof InvitationSchema>;
export type Diagnostic = z.infer<typeof DiagnosticSchema>;
export type Plan = z.infer<typeof PlanSchema>;
export type Lesson = z.infer<typeof LessonSchema>;
export type Check = z.infer<typeof CheckSchema>;
export type Depth = z.infer<typeof depth>;
export const learningGet = <T>(workspace: string, path: string, schema: z.ZodType<T>, signal?: AbortSignal) => apiFetch(schema, `/api/workspaces/${workspace}/${path}`, { signal });
export const learningPost = <T>(workspace: string, path: string, schema: z.ZodType<T>, body: object) => apiFetch(schema, `/api/workspaces/${workspace}/${path}`, { method: "POST", body: JSON.stringify(body) });
