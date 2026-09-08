import { useEffect, useReducer, useRef, useState } from "react";

import { api, ApiError } from "../../api/client";
import {
  ChunkSettingsSchema,
  type ChunkSettings,
  type PreviewResponse,
  type ProcessedPreviewResponse,
  type SourceIngestionCapabilities,
  type SourceResponse,
} from "../../api/types";
import { ProcessingSettings } from "./processing-settings";
import { useModal } from "../../components/use-modal";

export type WizardStage = "select" | "settings" | "estimate" | "processing" | "review" | "ready" | "failed";
export type WizardInput = { kind: "file"; file: File } | { kind: "text"; sourceName: string; text: string };

type State = {
  stage: WizardStage;
  input: WizardInput | null;
  settings: ChunkSettings;
  estimate: PreviewResponse | null;
  actual: ProcessedPreviewResponse | null;
  source: SourceResponse | null;
  error: string | null;
  resumeStage: Exclude<WizardStage, "failed">;
  reprocessBaseId: string | null;
};

type Action =
  | { type: "input"; input: WizardInput }
  | { type: "settings"; settings: ChunkSettings }
  | { type: "invalid"; error: string }
  | { type: "stage"; stage: WizardStage }
  | { type: "estimated"; estimate: PreviewResponse }
  | { type: "processed"; source: SourceResponse; actual: ProcessedPreviewResponse }
  | { type: "ready"; source: SourceResponse }
  | { type: "failed"; error: string; resumeStage: Exclude<WizardStage, "failed"> }
  | { type: "review"; source: SourceResponse; actual: ProcessedPreviewResponse }
  | { type: "replace" };

const DEFAULT_SETTINGS = ChunkSettingsSchema.parse({});

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "input": return { ...state, input: action.input, stage: "settings", error: null };
    case "settings": return { ...state, settings: action.settings, error: null };
    case "invalid": return { ...state, error: action.error };
    case "stage": return { ...state, stage: action.stage, actual: action.stage === "processing" ? null : state.actual, error: null };
    case "estimated": return { ...state, stage: "estimate", estimate: action.estimate, error: null };
    case "processed": return { ...state, stage: "review", source: action.source, actual: action.actual, error: null };
    case "review": return { ...state, stage: "review", source: action.source, actual: action.actual, error: null };
    case "ready": return { ...state, stage: "ready", source: action.source, error: null };
    case "replace": return { ...state, stage: "select", input: null, estimate: null, actual: null, error: null };
    case "failed": return { ...state, stage: "failed", error: action.error, resumeStage: action.resumeStage };
  }
}

type SourceWizardProps = {
  workspaceId: string;
  capabilities: SourceIngestionCapabilities;
  open: boolean;
  initialFile?: File | null;
  existingSource?: SourceResponse | null;
  intent?: "review" | "reprocess";
  onClose: () => void;
  onChanged: () => void;
};

const ERROR_COPY: Record<string, string> = {
  request_body_too_large: "资料太大，请缩小后重试。",
  file_too_large: "文件太大，请缩小后重试。",
  text_too_large: "文本太长，请缩小后重试。",
  source_too_large: "资料太大，请拆分后重试。",
  source_work_limit_exceeded: "这份资料处理量过大，请拆成更小的资料。",
  unsupported_file_type: "当前不支持这种文件，请选择支持的格式。",
  unsafe_archive: "这个压缩文件无法安全读取，请重新导出后再试。",
  invalid_chunk_settings: "处理设置有误，请检查标出的字段。",
  workspace_ingestion_busy: "当前主题已有资料在处理，请稍后手动重试。",
  processed_preview_unavailable: "实际处理结果暂时不可用，请稍后重试或重新选择原资料。",
  empty_processed_source: "系统没有读到可用内容，请调整设置或更换资料。",
  persistence_error: "本地保存失败；输入仍保留，可以手动重试。",
  external_service_error: "资料服务暂时无法完成请求，可能尚未处理完毕。输入和设置已保留，请返回当前步骤重试。",
};

export function SourceWizard({ workspaceId, capabilities, open, initialFile, existingSource, intent, onClose, onChanged }: SourceWizardProps) {
  const initialFileError = initialFile ? fileError(initialFile, capabilities) : null;
  const initialInput = initialFile && !initialFileError ? { kind: "file" as const, file: initialFile } : null;
  const [state, dispatch] = useReducer(reducer, {
    stage: initialFileError ? "failed" : intent === "review" && existingSource ? "processing" : initialInput ? "settings" : "select",
    input: initialInput,
    settings: existingSource?.ingestion_config ?? DEFAULT_SETTINGS,
    estimate: null,
    actual: null,
    source: existingSource ?? null,
    error: initialFileError,
    resumeStage: "select",
    reprocessBaseId: existingSource?.status === "ready" ? existingSource.id : existingSource?.replaces_source_id ?? null,
  });
  const [textName, setTextName] = useState("学习笔记");
  const [text, setText] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const refreshingRef = useRef(false);
  const acceptingRef = useRef(false);
  const [accepting, setAccepting] = useState(false);
  const adjustingRef = useRef(false);
  const [adjusting, setAdjusting] = useState(false);
  const dialogRef = useModal(open, onClose);

  async function loadActual(source: SourceResponse) {
    if (refreshingRef.current) return;
    refreshingRef.current = true;
    dispatch({ type: "stage", stage: "processing" });
    try {
      const actual = await api.processedPreview(workspaceId, source.id);
      dispatch({ type: "review", source, actual });
    } catch (error) {
      dispatch({ type: "failed", error: publicError(error), resumeStage: "review" });
    } finally {
      refreshingRef.current = false;
    }
  }

  useEffect(() => {
    if (!open || !existingSource || intent !== "review") return;
    void loadActual(existingSource);
    // The existing Source identity is the trigger; loadActual intentionally keeps current input state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existingSource, intent, open, workspaceId]);

  if (!open) return null;

  function chooseText() {
    dispatch({ type: "input", input: { kind: "text", sourceName: textName, text } });
  }

  function chooseFile(file: File | undefined) {
    if (!file) return;
    const error = fileError(file, capabilities);
    if (error) {
      dispatch({ type: "failed", error, resumeStage: "select" });
      return;
    }
    dispatch({ type: "input", input: { kind: "file", file } });
  }

  function validatedSettings() {
    const effective = state.settings.chunkSettingMode === "auto" ? {
      ...state.settings,
      chunkSplitMode: DEFAULT_SETTINGS.chunkSplitMode,
      chunkSize: DEFAULT_SETTINGS.chunkSize,
      indexSize: DEFAULT_SETTINGS.indexSize,
      chunkSplitter: DEFAULT_SETTINGS.chunkSplitter,
    } : state.settings;
    const result = ChunkSettingsSchema.safeParse(effective);
    if (result.success) return result.data;
    const field = result.error.issues[0]?.path[0];
    const messages: Record<string, string> = {
      chunkSize: "片段长度：原文片段需为 100–3000 之间的整数。",
      indexSize: "索引内容长度：需至少为 32，且不能超过片段长度。",
      chunkSplitter: "自定义分隔符：请输入 1–20 个字符。",
      qaPrompt: "问答提取要求：不能超过 4000 个字符。",
    };
    dispatch({ type: "invalid", error: messages[String(field)] ?? "请检查处理设置中的数值。" });
    window.requestAnimationFrame(() => document.getElementById(String(field))?.focus());
    return null;
  }

  async function estimate() {
    const settings = validatedSettings();
    if (!settings || !state.input) return;
    if (state.input.kind === "text" && (!textName.trim() || !text.trim())) {
      document.getElementById(!textName.trim() ? "source-name" : "source-text")?.focus();
      dispatch({ type: "invalid", error: "请填写资料名称和内容。" });
      return;
    }
    try {
      const preview = state.input.kind === "file"
        ? await api.previewFile(workspaceId, state.input.file, settings)
        : await api.previewText(workspaceId, textName.trim(), text, settings);
      dispatch({ type: "estimated", estimate: preview });
    } catch (error) {
      dispatch({ type: "failed", error: publicError(error), resumeStage: "settings" });
    }
  }

  async function process() {
    const settings = validatedSettings();
    if (!settings || !state.input) return;
    dispatch({ type: "stage", stage: "processing" });
    try {
      const result = state.input.kind === "file"
        ? await api.ingestFile(workspaceId, state.input.file, settings, state.reprocessBaseId ?? undefined)
        : await api.ingestText(workspaceId, textName.trim(), text, settings, state.reprocessBaseId ?? undefined);
      dispatch({ type: "processed", source: result.source, actual: result.processed_preview });
      onChanged();
    } catch (error) {
      dispatch({ type: "failed", error: publicError(error), resumeStage: "estimate" });
    }
  }

  async function accept() {
    if (!state.source || acceptingRef.current || state.source.status !== "review") return;
    acceptingRef.current = true;
    setAccepting(true);
    try {
      const source = await api.acceptSource(workspaceId, state.source.id);
      dispatch({ type: "ready", source });
      onChanged();
    } catch (error) {
      dispatch({ type: "failed", error: publicError(error), resumeStage: "review" });
    } finally {
      acceptingRef.current = false;
      setAccepting(false);
    }
  }

  function retryFailure() {
    if (state.resumeStage === "review" && state.source && !state.actual) {
      void loadActual(state.source);
      return;
    }
    dispatch({ type: "stage", stage: state.resumeStage });
  }

  async function adjustAndReplace() {
    if (adjustingRef.current) return;
    adjustingRef.current = true;
    setAdjusting(true);
    if (state.source?.status === "review") {
      try {
        await api.deleteSource(workspaceId, state.source.id);
        onChanged();
      } catch (error) {
        dispatch({ type: "failed", error: publicError(error), resumeStage: "review" });
        adjustingRef.current = false;
        setAdjusting(false);
        return;
      }
    }
    dispatch({ type: "replace" });
    adjustingRef.current = false;
    setAdjusting(false);
  }

  const actualItems = state.actual?.items.filter((item) => item.q.trim() || item.a.trim()) ?? [];
  const visibleStage = state.stage === "failed" ? state.resumeStage : state.stage;
  const title = existingSource ? existingSource.name : "添加学习资料";
  return (
    <div className="dialog-backdrop" role="presentation" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); chooseFile(event.dataTransfer.files[0]); }}>
      <section ref={dialogRef} className="dialog-card source-wizard" role="dialog" aria-modal="true" aria-labelledby="source-wizard-title">
        <div className="dialog-title-row"><div><h2 id="source-wizard-title">{title}</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label="关闭资料向导">×</button></div>
        <ol className="wizard-steps" aria-label="处理步骤">{["选择资料", "处理方式", "预计片段", "实际复核"].map((label, index) => <li key={label} className={stepClass(visibleStage, index)} aria-current={stepClass(visibleStage, index) === "current" ? "step" : undefined}>{label}</li>)}</ol>

        {state.stage === "select" && (
          <div className="wizard-body select-source">
            {existingSource && <div className="notice"><strong>重新选择原资料后处理新版本</strong><p>原始内容没有长期保存在浏览器中；选择替代输入前不会发送请求。</p></div>}
            <button className="source-choice" type="button" aria-label="上传本地资料" onClick={() => fileInput.current?.click()}><strong>上传本地资料</strong><span>{formatExtensions(capabilities.accepted_extensions)} · 最大 {formatBytes(capabilities.max_upload_bytes)}</span></button>
            <input ref={fileInput} className="visually-hidden" tabIndex={-1} type="file" accept={capabilities.accepted_extensions.join(",")} onChange={(event) => chooseFile(event.target.files?.[0])} />
            <button className="source-choice" type="button" aria-label="粘贴文本" onClick={chooseText}><strong>粘贴文本</strong><span>适合课堂笔记、摘要和短资料</span></button>
          </div>
        )}

        {state.stage === "settings" && state.input && (
          <div className="wizard-body">
            <div className="selected-source"><span>已选择</span><strong>{state.input.kind === "file" ? state.input.file.name : "粘贴文本"}</strong><button type="button" className="text-button" onClick={() => dispatch({ type: "stage", stage: "select" })}>更换</button></div>
            {state.input.kind === "text" && <div className="text-source-fields"><label className="field-label" htmlFor="source-name">资料名称</label><input id="source-name" value={textName} maxLength={255} onChange={(event) => { setTextName(event.target.value); dispatch({ type: "input", input: { kind: "text", sourceName: event.target.value, text } }); }} /><label className="field-label" htmlFor="source-text">资料内容</label><textarea id="source-text" rows={7} value={text} onChange={(event) => { setText(event.target.value); dispatch({ type: "input", input: { kind: "text", sourceName: textName, text: event.target.value } }); }} /></div>}
            <ProcessingSettings invalid={Boolean(state.error)} value={state.settings} capabilities={capabilities} onChange={(settings) => dispatch({ type: "settings", settings })} />
            {state.error && <p className="form-error" role="alert">{state.error}</p>}
            <div className="dialog-actions"><button className="secondary-button" type="button" onClick={() => dispatch({ type: "stage", stage: "select" })}>返回</button><button className="primary-button" type="button" onClick={estimate}>查看预计片段</button></div>
          </div>
        )}

        {state.stage === "estimate" && state.estimate && <PreviewView title="预计片段" badge="本地估算" items={state.estimate.items.map((item) => item.text)} actions={<><button className="secondary-button" type="button" onClick={() => dispatch({ type: "stage", stage: "settings" })}>调整设置</button><button className="primary-button" type="button" onClick={process}>确认处理</button></>} />}
        {state.stage === "processing" && <div className="wizard-body processing-state" aria-live="polite"><span className="processing-mark" aria-hidden="true">···</span><h3>正在读取并整理资料</h3><p>完成后会先让你复核实际处理结果，不会自动用于问答。</p><button className="text-button" type="button" onClick={onClose}>关闭并稍后查看</button></div>}
        {state.stage === "review" && state.actual && <PreviewView title="实际处理结果" badge={state.source?.status === "ready" ? "已就绪" : "待复核"} items={actualItems.map((item) => item.q ? `${item.q}\n${item.a}` : item.a)} actions={<>{actualItems.length === 0 && state.source && <button className="secondary-button" type="button" onClick={() => void loadActual(state.source!)}>刷新处理结果</button>}<button className="secondary-button" type="button" disabled={adjusting} onClick={() => void adjustAndReplace()}>{adjusting ? "正在准备新版本" : "调整设置并重新处理"}</button>{state.source?.status === "review" ? <button className="primary-button" type="button" disabled={actualItems.length === 0 || accepting} onClick={accept}>{accepting ? "正在接受" : "接受并用于问答"}</button> : <button className="primary-button" type="button" onClick={onClose}>关闭</button>}</>} />}
        {state.stage === "ready" && <div className="wizard-body ready-state"><span className="ready-mark" aria-hidden="true">✓</span><h3>资料已准备好</h3><p>{state.source?.name} 现在可以用于带引用的问答。</p><button className="primary-button" type="button" onClick={onClose}>完成</button></div>}
        {state.stage === "failed" && <div className="wizard-body failed-state" role="alert"><h3>{state.resumeStage === "estimate" ? "资料导入没有完成" : state.resumeStage === "review" ? "实际结果尚未确认" : "这项操作没有完成"}</h3><p>{state.error}</p><div className="dialog-actions">{state.input && <button className="secondary-button" type="button" onClick={() => dispatch({ type: "stage", stage: "settings" })}>调整设置</button>}<button className="primary-button" type="button" onClick={retryFailure}>返回重试</button></div></div>}
      </section>
    </div>
  );
}

function PreviewView({ title, badge, items, actions }: { title: string; badge: string; items: string[]; actions: React.ReactNode }) {
  return <div className="wizard-body preview-view"><div className="preview-heading"><h3>{title}</h3><span className="status-label">{badge}</span></div><p>{title === "预计片段" ? "这是本地预览的估算，实际结果以处理后复核为准。" : "检查系统实际读到的内容，确认后才会用于问答。"}</p><div className="preview-list">{items.length ? items.map((item, index) => <article key={`${index}-${item.slice(0, 12)}`}><span>片段 {index + 1}</span><p>{item}</p></article>) : <p role="status">{title === "实际处理结果" ? "暂时还没有可用片段，资料可能仍在处理。请稍后刷新处理结果；若持续为空，再调整设置或更换资料。" : "没有读到可用内容，请调整设置或更换资料。"}</p>}</div><div className="dialog-actions">{actions}</div></div>;
}

function publicError(error: unknown) {
  return error instanceof ApiError ? ERROR_COPY[error.code] ?? "当前无法完成这项操作；输入仍保留，可以手动重试。" : "当前无法完成这项操作；输入仍保留，可以手动重试。";
}

function formatExtensions(extensions: string[]) { return extensions.map((item) => item.replace(".", "").toUpperCase()).join("、"); }
function formatBytes(bytes: number) { return `${Math.max(1, Math.round(bytes / 1_000_000))} MB`; }
function fileError(file: File, capabilities: SourceIngestionCapabilities) { const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`; if (!capabilities.accepted_extensions.includes(extension)) return `当前支持：${formatExtensions(capabilities.accepted_extensions)}`; if (file.size > capabilities.max_upload_bytes) return `单个文件不能超过 ${formatBytes(capabilities.max_upload_bytes)}`; return null; }
function stepClass(stage: WizardStage, index: number) { const current = ({ select: 0, settings: 1, estimate: 2, processing: 3, review: 3, ready: 3, failed: 0 } as const)[stage]; return current === index ? "current" : current > index ? "done" : ""; }
