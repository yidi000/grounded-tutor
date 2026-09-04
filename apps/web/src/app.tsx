import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, apiFetch } from "./api/client";
import { SourceIngestionCapabilitiesSchema, type SourceResponse, type WorkspaceResponse } from "./api/types";
import { AppShell } from "./components/app-shell";
import { Composer } from "./components/composer";
import { ContextPanel } from "./components/context-panel";
import { ConversationSurface } from "./components/conversation-surface";
import type { AppMode } from "./config";
import { demoFixture } from "./demo/fixture";
import { SourcePanel } from "./features/sources/source-panel";
import { SourceWizard } from "./features/sources/source-wizard";
import { TopicRail } from "./features/workspaces/topic-rail";
import { WorkspaceDialog } from "./features/workspaces/workspace-dialog";

type AppProps = { mode: AppMode };

export function App({ mode }: AppProps) {
  if (mode === "demo_read_only") return <DemoNotebook />;
  return <LocalApp />;
}

function LocalApp() {
  const [queryClient] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  return <QueryClientProvider client={queryClient}><LocalNotebook /></QueryClientProvider>;
}

function LocalNotebook() {
  const queryClient = useQueryClient();
  const capabilities = useQuery({ queryKey: ["source-ingestion-capabilities"], queryFn: ({ signal }) => apiFetch(SourceIngestionCapabilitiesSchema, "/api/capabilities/source-ingestion", { signal }) });
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: ({ signal }) => api.listWorkspaces(signal), enabled: capabilities.isSuccess });
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [workspaceDialog, setWorkspaceDialog] = useState(false);
  const [wizard, setWizard] = useState<{ open: boolean; file?: File; source?: SourceResponse; intent?: "review" | "reprocess" }>({ open: false });
  const lastTrigger = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!currentId && workspaces.data?.[0]) setCurrentId(workspaces.data[0].id);
  }, [currentId, workspaces.data]);

  const current = workspaces.data?.find((workspace) => workspace.id === currentId) ?? null;
  const readyCount = current?.ready_source_count ?? 0;
  const capabilityMessage = capabilities.isPending ? "正在读取资料能力" : capabilities.isError ? "暂时无法读取资料能力" : "资料能力已读取";

  function rememberTrigger() { lastTrigger.current = document.activeElement as HTMLElement | null; }
  function openWizard(options: Omit<typeof wizard, "open"> = {}) { rememberTrigger(); setWizard({ open: true, ...options }); }
  function closeWizard() { setWizard({ open: false }); window.setTimeout(() => lastTrigger.current?.focus(), 0); }
  function closeWorkspaceDialog() { setWorkspaceDialog(false); window.setTimeout(() => lastTrigger.current?.focus(), 0); }
  async function refresh() { await Promise.all([queryClient.invalidateQueries({ queryKey: ["workspaces"] }), currentId ? queryClient.invalidateQueries({ queryKey: ["sources", currentId] }) : Promise.resolve()]); }
  function upsert(workspace: WorkspaceResponse) { queryClient.setQueryData<WorkspaceResponse[]>(["workspaces"], (items = []) => items.some((item) => item.id === workspace.id) ? items.map((item) => item.id === workspace.id ? workspace : item) : [...items, workspace]); setCurrentId(workspace.id); }

  const intro = current ? <section className="intro-card workspace-intro" aria-labelledby="intro-title"><div className="intro-meta"><span className="mode-label local-label">本地工作区</span><span>{capabilityMessage}</span></div><h1 id="intro-title">{current.title}</h1><p>{readyCount ? `已有 ${readyCount} 份资料可以用于问答。你仍可继续添加或复核资料。` : "至少一份资料准备好后才能提问。先添加资料，并检查系统实际读到的内容。"}</p><div className="intro-actions"><button className="primary-button" type="button" onClick={() => openWizard()}>上传本地资料</button><button className="secondary-button" type="button" onClick={() => openWizard()}>粘贴文本</button></div></section> : <section className="intro-card" aria-labelledby="intro-title"><div className="intro-meta"><span className="mode-label local-label">本地工作区</span><span>{capabilityMessage}</span></div><h1 id="intro-title">先建立一个学习主题</h1><p>一个主题保存自己的资料、对话和学习进度。创建后再上传讲义或粘贴笔记。</p>{capabilities.isSuccess && <button className="primary-button" type="button" onClick={() => { rememberTrigger(); setWorkspaceDialog(true); }}>创建学习主题</button>}</section>;

  return <>
    <AppShell
      headerActions={capabilities.isSuccess ? <div className="top-actions"><button className="materials-button" type="button" onClick={() => current && openWizard()} disabled={!current}>资料 · {readyCount} 已就绪</button><button className="primary-button compact" type="button" onClick={() => current && openWizard()} disabled={!current}>上传你的资料 ＋</button></div> : undefined}
      topicRail={<TopicRail mode="local" workspaces={workspaces.data} currentId={currentId} onSelect={(workspace) => setCurrentId(workspace.id)} onCreate={capabilities.isSuccess ? () => { rememberTrigger(); setWorkspaceDialog(true); } : undefined} onRenamed={upsert} />}
      conversation={<ConversationSurface intro={intro} onFileDrop={current && capabilities.data ? (file) => openWizard({ file }) : undefined}><Composer mode="local" onAddSource={current ? () => openWizard() : undefined} /></ConversationSurface>}
      contextPanel={<ContextPanel sources={current ? <SourcePanel workspaceId={current.id} onAdd={() => openWizard()} onReview={(source) => openWizard({ source, intent: "review" })} onReprocess={(source) => openWizard({ source, intent: "reprocess" })} /> : undefined} />}
    />
    {capabilities.data && <WorkspaceDialog open={workspaceDialog} capabilities={capabilities.data} onClose={closeWorkspaceDialog} onCreated={upsert} />}
    {capabilities.data && current && <SourceWizard key={`${wizard.open}-${wizard.source?.id ?? "new"}-${wizard.file?.name ?? ""}`} workspaceId={current.id} capabilities={capabilities.data} open={wizard.open} initialFile={wizard.file} existingSource={wizard.source} intent={wizard.intent} onClose={closeWizard} onChanged={() => { void refresh(); }} />}
  </>;
}

function DemoNotebook() {
  const intro = <section className="intro-card demo-intro" aria-labelledby="intro-title"><div className="intro-meta"><span className="mode-label">公开只读示例</span><span>固定主题：RAG 基础</span></div><h1 id="intro-title">先看结论，也要看结论从哪里来</h1><p>这是证据笔记本的只读示例。带引用回答会在问答阶段进入中央区域，原文依据固定在右侧核对。</p><a className="primary-link" href={demoFixture.localInstructionsUrl}>在本地使用我的资料<span aria-hidden="true">↗</span></a></section>;
  return <AppShell topicRail={<TopicRail mode="demo_read_only" />} conversation={<ConversationSurface intro={intro}><Composer mode="demo_read_only" /></ConversationSurface>} contextPanel={<ContextPanel />} />;
}
