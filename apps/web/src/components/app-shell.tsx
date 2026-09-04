import type { ReactNode } from "react";

type AppShellProps = {
  topicRail: ReactNode;
  conversation: ReactNode;
  contextPanel: ReactNode;
};

export function AppShell({
  topicRail,
  conversation,
  contextPanel,
}: AppShellProps) {
  return (
    <div className="app-shell">
      <header className="top-bar">
        <a className="wordmark" href="/" aria-label="Grounded Tutor 首页">
          <span className="wordmark-mark" aria-hidden="true">
            GT
          </span>
          <span>Grounded Tutor</span>
        </a>
        <p>把问题放在资料旁边，把依据留在视线里。</p>
      </header>
      {topicRail}
      {conversation}
      {contextPanel}
    </div>
  );
}
