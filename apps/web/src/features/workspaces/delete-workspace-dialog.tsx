import { useRef, useState } from "react";
import { api } from "../../api/client";
import type { WorkspaceResponse } from "../../api/types";
import { useModal } from "../../components/use-modal";

type Props = {
  workspace: Pick<WorkspaceResponse, "id" | "title" | "source_count">;
  onClose: () => void;
  onDeleted: (id: string) => void | Promise<void>;
};

export function DeleteWorkspaceDialog({ workspace, onClose, onDeleted }: Props) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useModal(true, () => { if (!pending) onClose(); }, cancelRef);
  async function remove() {
    if (pending) return;
    setPending(true); setError(false);
    try { await api.deleteWorkspace(workspace.id); await onDeleted(workspace.id); }
    catch { setError(true); }
    finally { setPending(false); }
  }
  return <div className="dialog-backdrop">
    <section className="dialog-card workspace-dialog" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="delete-topic-title" aria-describedby="delete-topic-detail" aria-busy={pending}>
      <h2 id="delete-topic-title">删除“{workspace.title}”？</h2>
      <p id="delete-topic-detail">将永久删除此主题的 {workspace.source_count} 份资料、全部对话和学习进度，以及对应的云端资料库。此操作无法撤销。</p>
      {error && <p className="form-error" role="alert">删除尚未确认完成，主题暂时保留在列表中。请重试；如部分云端资料已移除，重试会继续清理。</p>}
      {pending && <p role="status">正在删除，请稍候…</p>}
      <div className="dialog-actions">
        <button ref={cancelRef} className="secondary-button" type="button" disabled={pending} onClick={onClose}>取消</button>
        <button className="primary-button danger-button" type="button" disabled={pending} onClick={() => void remove()}>{pending ? "正在删除" : "永久删除"}</button>
      </div>
    </section>
  </div>;
}
