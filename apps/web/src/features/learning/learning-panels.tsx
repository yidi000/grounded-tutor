import { useState } from "react";
import type { Citation, GroundedContentBlock } from "../../api/types";
import type { Plan } from "../../api/learning";
import { AnswerBlock } from "../chat/answer-block";

export type CitationSelection = (citation: Citation, blockId: string, anchor: HTMLButtonElement) => void;
export function Evidence({ blocks, citations, onSelect, prefix }: { blocks: GroundedContentBlock[]; citations: Citation[]; onSelect: CitationSelection; prefix: string }) {
  const byId = new Map(citations.map((c) => [c.id, c]));
  const numbers = new Map([...new Set(blocks.flatMap((b) => b.citation_ids))].map((id, i) => [id, i + 1]));
  return <>{blocks.map((block) => <AnswerBlock key={block.id} block={block} citationById={byId} citationNumbers={numbers} selected={false} onSelectCitation={(c, id, anchor) => onSelect(c, `${prefix}:${id}`, anchor)} />)}</>;
}

export function DiagnosticInvite({ initialGoal, onStart, onDismiss }: { initialGoal: string; onStart: (goal: string, background: string) => void; onDismiss: () => void }) {
  const [goal, setGoal] = useState(initialGoal);
  const [background, setBackground] = useState("");
  return <section aria-label="诊断邀请"><h2>要先做一个 3–5 题的小诊断吗？</h2><p>可以跳过任何题目，也可以随时继续提问。点击开始后才会生成题目。</p><label>学习目标<input maxLength={2000} value={goal} onChange={(e) => setGoal(e.target.value)} /></label><label>已有基础（选填）<input maxLength={2000} value={background} onChange={(e) => setBackground(e.target.value)} /></label><div className="inline-actions"><button type="button" className="primary-button" disabled={!goal.trim()} onClick={() => onStart(goal.trim(), background.trim())}>开始诊断</button><button type="button" onClick={onDismiss}>继续提问</button></div></section>;
}

export function Question({ prompt, options, name, onSubmit, onSkip }: { prompt: string; options: string[]; name: string; onSubmit: (answer: string) => void; onSkip: () => void }) {
  const [answer, setAnswer] = useState("");
  return <form onSubmit={(e) => { e.preventDefault(); if (answer.trim()) onSubmit(answer.trim()); }}><fieldset aria-label={name}><legend>{prompt}</legend>{options.length ? options.map((option) => <label className="learning-option" key={option}><input type="radio" name={name} value={option} checked={answer === option} onChange={() => setAnswer(option)} />{option}</label>) : <label>你的答案<textarea maxLength={2000} value={answer} onChange={(e) => setAnswer(e.target.value)} /></label>}</fieldset><div className="inline-actions"><button className="primary-button" type="submit" disabled={!answer.trim()}>提交答案</button><button type="button" onClick={onSkip}>跳过此题</button></div></form>;
}

const statuses = { not_started: "未开始", active: "学习中", completed: "已完成", needs_review: "需要复习", not_assessed: "未评估" };
export function LearningPlan({ plan, onStart, onSkip }: { plan: Plan; onStart: (id: string) => void; onSkip: (id: string) => void }) {
  const next = plan.concepts.find((c) => !["completed", "not_assessed"].includes(c.status));
  return <section><h2>学习路径</h2><p>{plan.goal}</p><ol className="learning-path">{plan.concepts.map((c) => <li key={c.id}><div><h3>{c.title}</h3><span>{statuses[c.status]}</span></div><p>{c.objective}</p><small>{c.evidence_refs.length ? `${c.evidence_refs.length} 条资料依据` : "暂无资料依据"}</small>{c.id === next?.id && !["completed", "superseded"].includes(plan.status) && <div className="inline-actions"><button type="button" onClick={() => onStart(c.id)}>开始概念 {c.order}</button><button type="button" onClick={() => onSkip(c.id)}>跳过此概念</button></div>}</li>)}</ol>{plan.status === "completed" && <p role="status">这条学习路径已结束。跳过的概念仍标记为未评估。</p>}</section>;
}
