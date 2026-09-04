import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { apiFetch } from "./api/client";
import { SourceIngestionCapabilitiesSchema } from "./api/types";
import { AppShell } from "./components/app-shell";
import { Composer } from "./components/composer";
import { ContextPanel } from "./components/context-panel";
import { ConversationSurface } from "./components/conversation-surface";
import type { AppMode } from "./config";
import { demoFixture } from "./demo/fixture";
import { TopicRail } from "./features/workspaces/topic-rail";

type AppProps = {
  mode: AppMode;
};

export function App({ mode }: AppProps) {
  if (mode === "demo_read_only") {
    return <EvidenceNotebook mode={mode} capabilityMessage={null} />;
  }

  return <LocalApp />;
}

function LocalApp() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false } },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <LocalNotebook />
    </QueryClientProvider>
  );
}

function LocalNotebook() {
  const capabilities = useQuery({
    queryKey: ["source-ingestion-capabilities"],
    queryFn: ({ signal }) =>
      apiFetch(
        SourceIngestionCapabilitiesSchema,
        "/api/capabilities/source-ingestion",
        { signal },
      ),
  });

  return (
    <EvidenceNotebook
      mode="local"
      capabilityMessage={
        capabilities.isPending
          ? "正在读取资料能力"
          : capabilities.isError
            ? "暂时无法读取资料能力"
            : "资料能力已读取"
      }
    />
  );
}

type EvidenceNotebookProps = {
  mode: AppMode;
  capabilityMessage: string | null;
};

function EvidenceNotebook({ mode, capabilityMessage }: EvidenceNotebookProps) {
  const isDemo = mode === "demo_read_only";
  const intro = isDemo ? (
    <section className="intro-card demo-intro" aria-labelledby="intro-title">
      <div className="intro-meta">
        <span className="mode-label">公开只读示例</span>
        <span>固定主题：RAG 基础</span>
      </div>
      <h1 id="intro-title">先看结论，也要看结论从哪里来</h1>
      <p>
        这是证据笔记本的基础界面。带引用的示例内容会在下一阶段进入中央区域，原文依据固定在右侧核对。
      </p>
      <a className="primary-link" href={demoFixture.localInstructionsUrl}>
        在本地使用我的资料
        <span aria-hidden="true">↗</span>
      </a>
    </section>
  ) : (
    <section className="intro-card" aria-labelledby="intro-title">
      <div className="intro-meta">
        <span className="mode-label local-label">本地工作区</span>
        <span>{capabilityMessage}</span>
      </div>
      <h1 id="intro-title">让学习资料成为可以核对的答案</h1>
      <p>
        页面骨架已经就绪。学习主题、资料处理和带引用问答会按能力逐步开放，不会提前显示尚不可用的操作。
      </p>
      <div className="reading-guide" aria-label="使用方式">
        <span>中央提问</span>
        <span aria-hidden="true">→</span>
        <span>右侧核对依据</span>
      </div>
    </section>
  );

  return (
    <AppShell
      topicRail={<TopicRail mode={mode} />}
      conversation={
        <ConversationSurface intro={intro}>
          <Composer mode={mode} />
        </ConversationSurface>
      }
      contextPanel={<ContextPanel />}
    />
  );
}
