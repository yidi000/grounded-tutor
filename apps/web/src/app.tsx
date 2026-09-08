import { QueryClient, QueryClientProvider, useQuery, useQueryClient, useIsMutating } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, apiFetch } from "./api/client";
import { SourceIngestionCapabilitiesSchema, type ChatRequest, type ChatHistoryResponse, type Citation, type SourceResponse, type WorkspaceResponse } from "./api/types";
import { AppShell } from "./components/app-shell";
import { Composer } from "./components/composer";
import { ContextPanel } from "./components/context-panel";
import { ConversationSurface } from "./components/conversation-surface";
import type { AppMode } from "./config";
import { demoFixture } from "./demo/fixture";
import { SourcePanel } from "./features/sources/source-panel";
import { SourceWizard } from "./features/sources/source-wizard";
import { TopicRail } from "./features/workspaces/topic-rail";
import { DeleteWorkspaceDialog } from "./features/workspaces/delete-workspace-dialog";
import { WorkspaceDialog } from "./features/workspaces/workspace-dialog";
import { ChatView } from "./features/chat/chat-view";

import { LearningWorkspace } from "./features/learning/learning-workspace";

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
  const [currentId, setCurrentId] = useState<string | null>(() => new URLSearchParams(window.location.search).get("workspace"));
  const [deletingWorkspace, setDeletingWorkspace] = useState<WorkspaceResponse | null>(null);
  const allLearningPending = useIsMutating({ mutationKey: ["learning-write"] }) > 0;
  const [workspaceDialog, setWorkspaceDialog] = useState(false);
  const [wizard, setWizard] = useState<{ open: boolean; file?: File; source?: SourceResponse; intent?: "review" | "reprocess" }>({ open: false });
  // ponytail: retries survive topic switches, not page reloads; persist requests if reload recovery is needed.
  const retryRequests = useRef<Record<string, ChatRequest>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [failedAsks, setFailedAsks] = useState<string[]>([]);
  const [pendingAsks, setPendingAsks] = useState<string[]>([]);
  const [citation, setCitation] = useState<Citation | null>(null);
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const lastTrigger = useRef<HTMLElement | null>(null);
  const citationTrigger = useRef<HTMLButtonElement | null>(null);
  const chatGeneration = useRef(0);
  const learningRetries = useRef(new Map<string, string>());
  const learningPending = useIsMutating({ mutationKey: ["learning-write", currentId] }) > 0;

  useEffect(() => {
    if (workspaces.data?.length && !workspaces.data.some((item) => item.id === currentId)) setCurrentId(workspaces.data[0].id);
  }, [currentId, workspaces.data]);

  const current = workspaces.data?.find((workspace) => workspace.id === currentId) ?? null;
  useEffect(() => {
    if (!current) return;
    const url = new URL(window.location.href);
    url.searchParams.set("workspace", current.id);
    window.history.replaceState(null, "", url);
  }, [current?.id]);
  const chatHistory = useQuery({ queryKey: ["chat-history", currentId], queryFn: ({ signal }) => api.chatHistory(currentId!, signal), enabled: Boolean(current), refetchOnWindowFocus: false });
  const exchanges = chatHistory.data?.exchanges ?? [];
  const conversationId = exchanges.at(-1)?.response.conversation_id ?? null;
  const readyCount = current?.ready_source_count ?? 0;
  const capabilityMessage = capabilities.isPending ? "正在读取资料能力" : capabilities.isError ? "暂时无法读取资料能力" : "资料能力已读取";

  function rememberTrigger() { lastTrigger.current = document.activeElement as HTMLElement | null; }
  function openWizard(options: Omit<typeof wizard, "open"> = {}) { rememberTrigger(); setWizard({ open: true, ...options }); }
  function closeWizard() { setWizard({ open: false }); window.setTimeout(() => lastTrigger.current?.focus(), 0); }
  function closeWorkspaceDialog() { setWorkspaceDialog(false); window.setTimeout(() => lastTrigger.current?.focus(), 0); }
  function dismissCitation() { setCitation(null); setSelectedBlockId(null); }
  function closeCitation() { dismissCitation(); window.setTimeout(() => citationTrigger.current?.focus(), 0); }
  function selectWorkspace(workspace: WorkspaceResponse) { if (workspace.id === currentId) return; chatGeneration.current += 1; setCurrentId(workspace.id); setCitation(null); setSelectedBlockId(null); }
  async function ask(question: string) {
    if (!current || !chatHistory.isSuccess || chatHistory.isFetching || pendingAsks.includes(current.id) || learningPending) return;
    const workspaceId = current.id;
    const previous = retryRequests.current[workspaceId];
    const payload = previous?.message === question ? previous : { conversation_id: conversationId, message: question, idempotency_key: crypto.randomUUID() };
    retryRequests.current[workspaceId] = payload;
    setFailedAsks((items) => items.filter((id) => id !== workspaceId));
    setPendingAsks((items) => [...items, workspaceId]);
    const generation = chatGeneration.current;
    try {
      const response = await api.ask(workspaceId, payload);
      delete retryRequests.current[workspaceId];
      await queryClient.invalidateQueries({ queryKey: ["learning", workspaceId] });
      await queryClient.cancelQueries({ queryKey: ["chat-history", workspaceId] });
      queryClient.setQueryData<ChatHistoryResponse>(["chat-history", workspaceId], (history) => history?.exchanges.some((item) => item.response.message_id === response.message_id) ? history : ({ exchanges: [...(history?.exchanges ?? []), { question, response }] }));
      // Re-read persisted history after a workspace switch, including older turns.
      if (generation !== chatGeneration.current) await queryClient.invalidateQueries({ queryKey: ["chat-history", workspaceId] });
    } catch (error) {
      setFailedAsks((items) => [...items, workspaceId]);
      throw error;
    } finally {
      setPendingAsks((items) => items.filter((id) => id !== workspaceId));
    }
  }
  async function refresh() { await Promise.all([queryClient.invalidateQueries({ queryKey: ["workspaces"] }), currentId ? queryClient.invalidateQueries({ queryKey: ["sources", currentId] }) : Promise.resolve()]); }
  async function deletedWorkspace(id: string) {
    await queryClient.cancelQueries({ queryKey: ["workspaces"] });
    chatGeneration.current += 1;
    setDeletingWorkspace(null);
    const remaining = (workspaces.data ?? []).filter((item) => item.id !== id);
    queryClient.setQueryData(["workspaces"], remaining);
    queryClient.removeQueries({ predicate: (query) => query.queryKey[1] === id });
    delete retryRequests.current[id];
    setDrafts(({ [id]: _removed, ...rest }) => rest);
    setFailedAsks((items) => items.filter((item) => item !== id));
    if (id === currentId) {
      setCurrentId(remaining[0]?.id ?? null); dismissCitation();
      const url = new URL(window.location.href);
      if (remaining.length) url.searchParams.set("workspace", remaining[0].id);
      else url.searchParams.delete("workspace");
      window.history.replaceState(null, "", url);
    }
    window.setTimeout(() => document.querySelector<HTMLButtonElement>(".rail-add")?.focus(), 0);
  }
  function upsert(workspace: WorkspaceResponse) { queryClient.setQueryData<WorkspaceResponse[]>(["workspaces"], (items = []) => items.some((item) => item.id === workspace.id) ? items.map((item) => item.id === workspace.id ? workspace : item) : [...items, workspace]); }
  function addWorkspace(workspace: WorkspaceResponse) { upsert(workspace); selectWorkspace(workspace); }

  const intro = current ? (
    <section className={readyCount ? "workspace-heading" : "intro-card workspace-intro"} aria-labelledby="intro-title">
      <h1 id="intro-title">{current.title}</h1>
      <p>{readyCount ? `${readyCount} 份资料已就绪 · 回答依据可在右侧核对` : "先添加讲义或笔记，复核处理结果后，就可以围绕资料提问。"}</p>
      {!readyCount && <p className="intro-hint">使用右上角“添加资料”，或将文件拖入这里。</p>}
    </section>
  ) : (
    <section className="intro-card" aria-labelledby="intro-title">
      <h1 id="intro-title">先建立一个学习主题</h1>
      <p>一个主题保存自己的资料、对话和学习进度。创建后再上传讲义或粘贴笔记。</p>
      <p className="intro-hint">{capabilityMessage}</p>
      {capabilities.isSuccess && <button className="primary-button" type="button" onClick={() => { rememberTrigger(); setWorkspaceDialog(true); }}>创建学习主题</button>}
    </section>
  );

  return <>
    <AppShell
      headerActions={capabilities.isSuccess ? <div className="top-actions"><span className="workspace-mode">本地工作区</span><button className="primary-button compact" type="button" onClick={() => current && openWizard()} disabled={!current}>添加资料</button></div> : undefined}
      topicRail={<TopicRail mode="local" workspaces={workspaces.data} currentId={currentId} onSelect={selectWorkspace} onCreate={capabilities.isSuccess ? () => { rememberTrigger(); setWorkspaceDialog(true); } : undefined} onRenamed={upsert} deleteDisabled={pendingAsks.length > 0 || allLearningPending || wizard.open} onDelete={(workspace) => { rememberTrigger(); setDeletingWorkspace(workspace); }} />}
      conversation={<ConversationSurface intro={intro} activity={<>{current && chatHistory.isFetching && <p role="status">正在读取历史对话…</p>}{current && chatHistory.isError && <div className="insufficient-state" role="alert"><p>暂时无法读取历史对话</p><button type="button" onClick={() => void chatHistory.refetch()}>重新加载对话</button></div>}{exchanges.length ? <ChatView exchanges={exchanges} selectedBlockId={selectedBlockId} onAddSource={() => openWizard()} onRephrase={() => document.getElementById("study-question")?.focus()} onSelectCitation={(nextCitation, blockId, anchor) => { citationTrigger.current = anchor; setCitation(nextCitation); setSelectedBlockId(blockId); }} /> : null}{current && <LearningWorkspace key={current.id} workspaceId={current.id} title={current.title} chatPending={pendingAsks.includes(current.id)} retries={learningRetries.current} onSelectCitation={(nextCitation, blockId, anchor) => { citationTrigger.current = anchor; setCitation(nextCitation); setSelectedBlockId(blockId); }} />}</>} onFileDrop={current && capabilities.data ? (file) => openWizard({ file }) : undefined}><Composer key={current?.id ?? "no-workspace"} mode="local" draft={drafts[currentId ?? ""] ?? ""} onDraftChange={(draft) => setDrafts((items) => ({ ...items, [currentId ?? ""]: draft }))} failed={failedAsks.includes(currentId ?? "")} ready={readyCount > 0} blocked={learningPending || !chatHistory.isSuccess || chatHistory.isFetching || pendingAsks.includes(currentId ?? "")} onSubmit={ask} /></ConversationSurface>}
      contextPanel={<ContextPanel citation={citation} onCloseCitation={closeCitation} onDismissCitation={dismissCitation} sources={current ? <SourcePanel workspaceId={current.id} onReview={(source) => openWizard({ source, intent: "review" })} onReprocess={(source) => openWizard({ source, intent: "reprocess" })} /> : undefined} />}
    />
    {deletingWorkspace && <DeleteWorkspaceDialog workspace={deletingWorkspace} onDeleted={deletedWorkspace} onClose={() => { setDeletingWorkspace(null); window.setTimeout(() => lastTrigger.current?.focus(), 0); }} />}
    {capabilities.data && <WorkspaceDialog open={workspaceDialog} capabilities={capabilities.data} onClose={closeWorkspaceDialog} onCreated={addWorkspace} />}
    {capabilities.data && current && <SourceWizard key={`${wizard.open}-${wizard.source?.id ?? "new"}-${wizard.file?.name ?? ""}`} workspaceId={current.id} capabilities={capabilities.data} open={wizard.open} initialFile={wizard.file} existingSource={wizard.source} intent={wizard.intent} onClose={closeWizard} onChanged={() => { void refresh(); }} />}
  </>;
}

function DemoNotebook() {
  const [citation, setCitation] = useState<Citation | null>(null);
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const citationTrigger = useRef<HTMLButtonElement | null>(null);
  function dismissCitation() { setCitation(null); setSelectedBlockId(null); }
  function closeCitation() { dismissCitation(); window.setTimeout(() => citationTrigger.current?.focus(), 0); }
  const intro = <section className="intro-card demo-intro" aria-labelledby="intro-title"><div className="intro-meta"><span className="mode-label">公开只读示例</span><span>固定主题：RAG 基础</span></div><h1 id="intro-title">先看结论，也要看结论从哪里来</h1><p>这是证据笔记本的只读示例。带引用回答会在问答阶段进入中央区域，原文依据固定在右侧核对。</p><a className="primary-link" href={demoFixture.localInstructionsUrl}>在本地使用我的资料<span aria-hidden="true">↗</span></a></section>;
  return <AppShell topicRail={<TopicRail mode="demo_read_only" />} conversation={<ConversationSurface intro={intro} activity={<ChatView exchanges={[demoFixture.exchange]} selectedBlockId={selectedBlockId} onAddSource={() => undefined} onRephrase={() => undefined} onSelectCitation={(nextCitation, blockId, anchor) => { citationTrigger.current = anchor; setCitation(nextCitation); setSelectedBlockId(blockId); }} />}><Composer mode="demo_read_only" /></ConversationSurface>} contextPanel={<ContextPanel citation={citation} onCloseCitation={closeCitation} onDismissCitation={dismissCitation} />} />;
}
