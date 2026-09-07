import { useState } from "react";
import { useMutation, useQuery, useQueryClient, useIsMutating } from "@tanstack/react-query";
import { z } from "zod";
import { ActivitySchema, CheckResultSchema, CheckSchema, DiagnosticResultSchema, DiagnosticSchema, InvitationSchema, LessonSchema, PlanSchema, learningGet, learningPost, type Depth } from "../../api/learning";
import type { Citation, GroundedContentBlock } from "../../api/types";
import { DiagnosticInvite, Evidence, LearningPlan, Question, type CitationSelection } from "./learning-panels";

const depthLabels = { standard: "标准讲解", simpler: "讲得更简单", more_examples: "多举些例子", deeper: "讲得更深入" };
type Feedback = { text: string; blocks: GroundedContentBlock[]; citations: Citation[] };
export function LearningWorkspace({ workspaceId, title, chatPending, retries, onSelectCitation }: { workspaceId: string; title: string; chatPending: boolean; retries: Map<string, string>; onSelectCitation: CitationSelection }) {
  const client = useQueryClient();
  const writing = useIsMutating({ mutationKey: ["learning-write", workspaceId] }) > 0;
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const activity = useQuery({ queryKey: ["learning", workspaceId, "activity"], queryFn: ({ signal }) => learningGet(workspaceId, "learning/activity", ActivitySchema, signal), refetchOnWindowFocus: false });
  const invitation = useQuery({ queryKey: ["learning", workspaceId, "invitation"], queryFn: ({ signal }) => learningGet(workspaceId, "diagnostics/invitation", InvitationSchema.nullable(), signal), refetchOnWindowFocus: false });
  const plans = useQuery({ queryKey: ["learning", workspaceId, "plans"], queryFn: ({ signal }) => learningGet(workspaceId, "plans", z.object({ plans: z.array(PlanSchema) }), signal), refetchOnWindowFocus: false });
  const state = activity.data;
  const completedId = state?.kind === "idle" ? /^diagnostic:([a-f0-9-]+):completed$/.exec(state.checkpoint ?? "")?.[1] : undefined;
  const completed = useQuery({ queryKey: ["learning", workspaceId, "diagnostic", completedId], queryFn: ({ signal }) => learningGet(workspaceId, `diagnostics/${completedId}`, DiagnosticSchema, signal), enabled: Boolean(completedId), refetchOnWindowFocus: false });
  async function refresh() { await Promise.all([client.invalidateQueries({ queryKey: ["learning", workspaceId] }), client.invalidateQueries({ queryKey: ["chat-history", workspaceId] })]); }
  const mutation = useMutation({ mutationKey: ["learning-write", workspaceId], mutationFn: async (operation: () => Promise<void>) => operation() });
  function run<T>(path: string, schema: z.ZodType<T>, payload: object, after?: (value: T) => void) {
    if (writing || chatPending) return;
    const identity = JSON.stringify([workspaceId, state?.checkpoint, path, payload]);
    const key = retries.get(identity) ?? crypto.randomUUID();
    retries.set(identity, key);
    mutation.mutate(async () => {
      const value = await learningPost(workspaceId, path, schema, { ...payload, idempotency_key: key });
      retries.delete(identity);
      setFeedback(null);
      after?.(value);
      await refresh();
    });
  }
  function insufficient(value: { status: string }) { if (value.status === "insufficient_material") setFeedback({ text: "当前资料不足以生成这一步，请补充或复核资料后再试。", blocks: [], citations: [] }); }
  function lesson(conceptId: string, depth: Depth = "standard") { run(`learning/concepts/${conceptId}/lessons`, LessonSchema, { depth }, insufficient); }
  function pause() { if (state?.checkpoint) run("learning/activity/pause", ActivitySchema, { checkpoint: state.checkpoint }, () => document.getElementById("study-question")?.focus()); }
  function answerCheck(response: string | null, skip: boolean) {
    if (!state?.check?.assessment_id) return;
    run(`learning/checks/${state.check.assessment_id}/answers`, CheckResultSchema, { response, skip });
  }
  const disabled = writing || chatPending || activity.isFetching || !activity.isSuccess;
  const diagnostic = state?.diagnostic;
  const question = diagnostic?.questions.find((q) => q.question_id === diagnostic.next_question_id);
  const savedPlan = state?.plan ?? plans.data?.plans.find((p) => p.status !== "superseded");
  const showInvite = state?.kind === "idle" && !completedId && invitation.data?.status === "offered";
  const readError = invitation.isError || plans.isError || completed.isError;
  const hasContent = state?.check_feedback || readError || showInvite || state?.kind !== "idle" || completedId || savedPlan || feedback || activity.isError;
  if (!hasContent) return null;
  return <section className="learning-card" aria-label="学习活动" aria-busy={mutation.isPending}>
    {readError && <div role="alert"><p>暂时无法读取学习信息，请重新加载。</p><button type="button" onClick={() => void refresh()}>重新加载学习信息</button></div>}
    {activity.isError && <div role="alert"><p>暂时无法恢复学习进度，请重新加载。</p><button type="button" onClick={() => void refresh()}>重新加载学习进度</button></div>}
    {mutation.isError && <div role="alert"><p>这一步暂时未能确认完成。可以重试原操作，或重新加载已保存的进度。</p><button type="button" onClick={() => { mutation.reset(); void refresh(); }}>重新加载学习进度</button></div>}
    {mutation.isPending && <p role="status">正在保存或生成，请稍候…</p>}
    {state?.check_feedback && <div className="learning-feedback" role="status"><h3>最近一次检查 · {state.check_feedback.concept_title}</h3><p>{state.check_feedback.result === "understood" ? "已通过。" : state.check_feedback.result === "needs_review" ? "需要复习，再看一次讲解。" : "已跳过，本题未评估。"}</p><Evidence blocks={state.check_feedback.explanation_blocks} citations={state.check_feedback.citations} onSelect={onSelectCitation} prefix={state.check_feedback.attempt_id} /></div>}
    {feedback && <div className="learning-feedback" role="status"><p>{feedback.text}</p><Evidence blocks={feedback.blocks} citations={feedback.citations} onSelect={onSelectCitation} prefix="feedback" /></div>}
    <fieldset className="learning-controls" disabled={disabled}>
      {state?.resume_action ? <section aria-label="恢复学习"><h2>刚才的学习已暂停</h2><p>已保存完成的进度。未提交的答案不会计入结果。</p><button type="button" className="primary-button" onClick={() => run("learning/activity/resume", ActivitySchema, { checkpoint: state.resume_action!.checkpoint })}>{state.resume_action.label}</button></section> : <>
        {showInvite && <DiagnosticInvite key={invitation.data!.id} initialGoal={title} onStart={(goal, background) => run("diagnostics", DiagnosticSchema, { consent: true, invitation_id: invitation.data!.id, goal, background: background || null }, insufficient)} onDismiss={() => {
          mutation.mutate(async () => { await learningPost(workspaceId, `diagnostics/invitation/${invitation.data!.id}/dismiss`, InvitationSchema, {}); await refresh(); document.getElementById("study-question")?.focus(); });
        }} />}
        {question && diagnostic && <section><h2>小诊断</h2><p>第 {diagnostic.questions.findIndex((q) => q.question_id === question.question_id) + 1} / {diagnostic.questions.length} 题</p><Question key={question.question_id} prompt={question.prompt} options={question.options} name="诊断题目" onSubmit={(response) => run(`diagnostics/${diagnostic.diagnostic_id}/answers`, DiagnosticResultSchema, { question_id: question.question_id, response, skip: false }, (v) => setFeedback({ text: v.result === "understood" ? "这一题已理解。" : "这一题需要复习。", blocks: v.feedback_blocks, citations: v.citations }))} onSkip={() => run(`diagnostics/${diagnostic.diagnostic_id}/answers`, DiagnosticResultSchema, { question_id: question.question_id, response: null, skip: true })} /><button type="button" onClick={pause}>退出诊断，继续提问</button></section>}
        {completed.data?.status === "completed" && <section><h2>诊断已完成</h2><p>用已保存的诊断结果生成 3–5 个概念的学习路径，跳过的题目不会算作掌握。</p><button type="button" className="primary-button" onClick={() => run("plans", PlanSchema, { diagnostic_id: completedId }, insufficient)}>生成学习路径</button></section>}
        {(state?.kind === "plan" || state?.kind === "idle" && !completedId) && savedPlan && <LearningPlan plan={savedPlan} onStart={(id) => lesson(id)} onSkip={(id) => run(`plans/${savedPlan.plan_id}/concepts/${id}/skip`, PlanSchema, {})} />}
        {state?.kind === "concept" && state.concept && <section><h2>{state.concept.title}</h2><p>{state.concept.objective}</p><button type="button" className="primary-button" onClick={() => lesson(state.concept!.id)}>开始学习下一个概念</button></section>}
        {state?.kind === "lesson" && state.lesson && <section><h2>{state.concept?.title ?? "概念讲解"}</h2><div className="inline-actions" aria-label="讲解深度">{state.lesson.available_depths.map((d) => <button type="button" key={d} aria-pressed={d === state.lesson!.depth} onClick={() => lesson(state.lesson!.concept_id, d)}>{depthLabels[d]}</button>)}</div><Evidence blocks={state.lesson.content_blocks} citations={state.lesson.citations} onSelect={onSelectCitation} prefix={state.lesson.lesson_id!} /><button type="button" className="primary-button" onClick={() => run(`learning/concepts/${state.lesson!.concept_id}/checks`, CheckSchema, {}, insufficient)}>检查理解</button></section>}
        {state?.kind === "check" && state.check && <section><h2>检查理解</h2><Question key={state.check.assessment_id} prompt={state.check.prompt!} options={state.check.options} name="检查题目" onSubmit={(response) => answerCheck(response, false)} onSkip={() => answerCheck(null, true)} /></section>}
        {state?.kind === "check_skip" && state.check && <section><h2>此题已跳过，尚未评估</h2><p>继续后进入下一概念，不会将此概念标记为已掌握。</p><button type="button" onClick={() => run(`learning/checks/${state.check!.assessment_id}/continue`, CheckResultSchema, { confirm_continue: true })}>确认继续下一步</button></section>}
        {state && state.kind !== "idle" && state.kind !== "diagnostic" && <button type="button" className="learning-detour" onClick={pause}>先问一个问题</button>}
      </>}
    </fieldset>
  </section>;
}
