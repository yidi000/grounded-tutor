import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "../../api/client";
import type {
  SourceIngestionCapabilities,
  WorkspaceResponse,
} from "../../api/types";
import { useModal } from "../../components/use-modal";

type WorkspaceDialogProps = {
  open: boolean;
  capabilities: SourceIngestionCapabilities;
  onClose: () => void;
  onCreated: (workspace: WorkspaceResponse) => void;
};

const MODEL_FIELDS = {
  vector_model: {
    label: "向量模型",
    help: "决定资料如何转换成可检索表示；更换后通常需要重新建立资料索引。",
  },
  agent_model: {
    label: "文本处理模型",
    help: "用于问答对提取等资料整理能力，不等同于最终回答模型。",
  },
  vlm_model: {
    label: "图片理解模型",
    help: "用于读取图片或扫描内容；留空时使用系统默认配置。",
  },
} as const;

type ModelKey = keyof typeof MODEL_FIELDS;

export function WorkspaceDialog({
  open,
  capabilities,
  onClose,
  onCreated,
}: WorkspaceDialogProps) {
  const [title, setTitle] = useState("");
  const [models, setModels] = useState<Partial<Record<ModelKey, string>>>({});
  const [created, setCreated] = useState<WorkspaceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [showModels, setShowModels] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);
  const dialogRef = useModal(open, onClose, titleRef);
  const supportedModels = capabilities.workspace_models
    .filter((item) => item.supported && item.key in MODEL_FIELDS)
    .map((item) => item.key as ModelKey);

  useEffect(() => {
    if (open) return;
    setTitle("");
    setModels({});
    setCreated(null);
    setError(null);
    setShowModels(false);
  }, [open]);

  if (!open) return null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const cleanTitle = title.trim();
    if (!cleanTitle) {
      titleRef.current?.focus();
      setError("请先填写主题名称");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = Object.fromEntries(
        Object.entries({ title: cleanTitle, ...models }).filter(
          ([, value]) => typeof value !== "string" || value.trim(),
        ),
      );
      const workspace = await api.createWorkspace(payload as { title: string });
      setCreated(workspace);
      onCreated(workspace);
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.code === "unsupported_workspace_model"
          ? "当前部署不支持这个模型，请留空并使用系统默认配置。"
          : "暂时无法创建主题，请保留内容后重试。",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation">
      <section ref={dialogRef} className="dialog-card workspace-dialog" role="dialog" aria-modal="true" aria-labelledby="workspace-dialog-title">
        <div className="dialog-title-row">
          <div>
            <span className="eyebrow">学习主题</span>
            <h2 id="workspace-dialog-title">{created ? "主题已创建" : "创建学习主题"}</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="关闭创建主题">
            ×
          </button>
        </div>
        {created ? (
          <div className="created-summary">
            <strong>{created.title}</strong>
            <p>模型配置在创建后保持只读，避免无意中重建资料索引。</p>
            {supportedModels.map((key) => (
              <div className="readonly-setting" key={key}>
                <span>{MODEL_FIELDS[key].label}</span>
                <strong>{created.model_choices[key] || "系统默认"}</strong>
              </div>
            ))}
            <button className="primary-button" type="button" onClick={onClose}>进入主题</button>
          </div>
        ) : (
          <form onSubmit={submit}>
            <label className="field-label" htmlFor="workspace-title">主题名称</label>
            <input id="workspace-title" ref={titleRef} value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} placeholder="例如：统计学期末复习" />
            {supportedModels.length > 0 && <button className="text-button model-toggle" type="button" aria-expanded={showModels} onClick={() => setShowModels((open) => !open)}>模型配置（高级）</button>}
            {showModels && supportedModels.length > 0 && (
              <div className="advanced-section">
                <p>普通使用无需填写；只有部署者明确提供模型 ID 时才配置。</p>
                {supportedModels.map((key) => (
                  <div className="setting-field" key={key}>
                    <label className="field-label" htmlFor={key}>{MODEL_FIELDS[key].label}</label>
                    <input id={key} value={models[key] ?? ""} onChange={(event) => setModels((current) => ({ ...current, [key]: event.target.value }))} placeholder="留空使用系统默认" />
                    <p>{MODEL_FIELDS[key].help}</p>
                  </div>
                ))}
              </div>
            )}
            {error && <p className="form-error" role="alert">{error}</p>}
            <div className="dialog-actions">
              <button className="secondary-button" type="button" onClick={onClose}>取消</button>
              <button className="primary-button" type="submit" disabled={saving}>{saving ? "正在创建" : "创建主题"}</button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
