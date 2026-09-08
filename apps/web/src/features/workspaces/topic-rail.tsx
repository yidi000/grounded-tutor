import { useState } from "react";

import { api } from "../../api/client";
import type { WorkspaceResponse } from "../../api/types";
import type { AppMode } from "../../config";
import { demoFixture } from "../../demo/fixture";

type TopicRailProps = { mode: AppMode; workspaces?: WorkspaceResponse[]; currentId?: string | null; onSelect?: (workspace: WorkspaceResponse) => void; onCreate?: () => void; onDelete?: (workspace: WorkspaceResponse) => void; deleteDisabled?: boolean; onRenamed?: (workspace: WorkspaceResponse) => void };

export function TopicRail({ mode, workspaces = [], currentId, onSelect, onCreate, onRenamed, onDelete, deleteDisabled }: TopicRailProps) {
  const isDemo = mode === "demo_read_only";
  const [renaming, setRenaming] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [error, setError] = useState(false);

  async function save(workspace: WorkspaceResponse) {
    if (!title.trim()) return;
    try {
      const updated = await api.renameWorkspace(workspace.id, { title: title.trim() });
      setRenaming(null); setError(false); onRenamed?.(updated);
    } catch { setError(true); }
  }

  return (
    <nav className="topic-rail" aria-label="学习主题">
      <div className="rail-title-row"><p className="rail-eyebrow">学习主题</p>{!isDemo && onCreate && <button className="rail-add" type="button" onClick={onCreate} aria-label="创建学习主题">＋</button>}</div>
      {isDemo ? <div className="topic-entry topic-entry-active" aria-current="page"><span className="sample-label">{demoFixture.topic.label}</span><strong>{demoFixture.topic.title}</strong><span>固定 · 只读</span></div> : workspaces.length ? <div className="topic-list">{workspaces.map((workspace) => <div className={`topic-entry ${workspace.id === currentId ? "topic-entry-active" : ""}`} key={workspace.id}>{renaming === workspace.id ? <form onSubmit={(event) => { event.preventDefault(); void save(workspace); }}><label className="visually-hidden" htmlFor={`rename-${workspace.id}`}>新的主题名称</label><input id={`rename-${workspace.id}`} autoFocus value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} /><div className="inline-actions"><button type="button" onClick={() => setRenaming(null)}>取消</button><button type="submit">保存</button></div></form> : <><button className="topic-select" type="button" onClick={() => onSelect?.(workspace)} aria-current={workspace.id === currentId ? "page" : undefined}><strong>{workspace.title}</strong><span>{workspace.ready_source_count} 份资料已就绪</span></button><button className="rename-topic" type="button" aria-label={`重命名学习主题：${workspace.title}`} onClick={() => { setTitle(workspace.title); setRenaming(workspace.id); }}>编辑</button>{onDelete && <button className="delete-topic" type="button" disabled={deleteDisabled} aria-label={`删除学习主题：${workspace.title}`} onClick={() => onDelete(workspace)}>删除</button>}</>}{error && renaming === workspace.id && <p className="form-error" role="alert">暂时无法保存名称。</p>}</div>)}</div> : <div className="topic-entry topic-entry-empty"><strong>还没有主题</strong><span>先创建一个学习主题，再加入自己的资料。</span></div>}
      {!isDemo && onCreate && <button className="new-topic-button" type="button" onClick={onCreate}>＋ 新主题</button>}
      <p className="rail-footnote">每个主题保留自己的资料和对话。</p>
    </nav>
  );
}
