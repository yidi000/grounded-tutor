import type { ReactNode } from "react";
import { useState } from "react";

type ContextPanelProps = { sources?: ReactNode; initialView?: "evidence" | "sources" };

export function ContextPanel({ sources, initialView = sources ? "sources" : "evidence" }: ContextPanelProps) {
  const [view, setView] = useState(initialView);
  return (
    <aside className="context-panel" aria-label="上下文">
      <div className="proof-tab" aria-hidden="true" />
      <div className="context-tabs" aria-label="上下文内容"><button type="button" aria-pressed={view === "evidence"} onClick={() => setView("evidence")}>回答依据</button><button type="button" aria-pressed={view === "sources"} onClick={() => setView("sources")}>全部资料</button></div>
      {view === "sources" && sources ? sources : <><div className="context-heading"><span>核对区</span><span className="status-label">等待依据</span></div><h2>回答依据</h2><div className="context-empty"><span className="context-glyph" aria-hidden="true">引</span><h3>回答依据会显示在这里</h3><p>选择回答里的引用后，这一栏会显示资料片段和原始位置。</p></div><p className="context-note">当前还没有可核对的回答。</p></>}
    </aside>
  );
}
