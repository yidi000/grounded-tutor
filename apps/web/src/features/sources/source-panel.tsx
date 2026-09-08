import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../api/client";
import type { SourceResponse } from "../../api/types";

type SourcePanelProps = {
  workspaceId: string;
  onReview: (source: SourceResponse) => void;
  onReprocess: (source: SourceResponse) => void;
};

const STATUS_LABEL = {
  uploading: "处理中",
  parsing: "处理中",
  indexing: "处理中",
  review: "待复核",
  ready: "已就绪",
  failed: "处理失败",
} as const;

export function SourcePanel({ workspaceId, onReview, onReprocess }: SourcePanelProps) {
  const queryClient = useQueryClient();
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState(false);
  const sources = useQuery({ queryKey: ["sources", workspaceId], queryFn: ({ signal }) => api.listSources(workspaceId, signal) });
  const current = (sources.data ?? []).filter((source) => !source.deleted_at && !source.superseded_at);

  async function remove(sourceId: string) {
    setDeleteError(false);
    try {
      await api.deleteSource(workspaceId, sourceId);
      setConfirmDelete(null);
      await queryClient.invalidateQueries({ queryKey: ["sources", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["workspaces"] });
    } catch {
      setDeleteError(true);
    }
  }

  return (
    <div className="source-panel">
      <div className="source-panel-heading"><h2>全部资料</h2><span className="status-label">{current.length} 份</span></div>
      {sources.isPending && <p className="panel-message">正在读取资料</p>}
      {sources.isError && <p className="form-error">暂时无法读取资料，请稍后重试。</p>}
      {!sources.isPending && current.length === 0 && <div className="context-empty"><h3>还没有学习资料</h3><p>上传讲义或粘贴笔记，处理后先复核再用于问答。</p><p>使用右上角“添加资料”开始。</p></div>}
      <div className="source-list">
        {current.map((source) => (
          <article className="source-card" key={source.id}>
            <div className="source-card-title"><strong>{source.name}</strong><span className={`source-status status-${source.status}`}>{STATUS_LABEL[source.status]}</span></div>
            <p>版本 {source.version} · {source.source_type === "file" ? "本地文件" : "粘贴文本"}</p>
            <div className="source-actions">
              {source.status === "review" && <button type="button" onClick={() => onReview(source)}>检查实际结果</button>}
              {source.status === "failed" && <button type="button" onClick={() => onReprocess(source)}>重新处理</button>}
              {source.status === "ready" && <button type="button" onClick={() => onReview(source)}>查看处理结果</button>}
              <button type="button" onClick={() => setConfirmDelete(source.id)}>移除</button>
            </div>
            {confirmDelete === source.id && <div className="delete-confirm" role="alertdialog" aria-label={`确认移除 ${source.name}`}><p>移除后不再用于新问答；已有引用历史仍会保留。</p><div><button type="button" onClick={() => setConfirmDelete(null)}>取消</button><button className="danger-button" type="button" onClick={() => remove(source.id)}>确认移除</button></div></div>}
          </article>
        ))}
      </div>
      {deleteError && <p className="form-error" role="alert">暂时无法移除资料，请手动重试。</p>}
    </div>
  );
}
