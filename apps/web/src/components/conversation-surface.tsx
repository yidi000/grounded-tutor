import type { ReactNode } from "react";

type ConversationSurfaceProps = {
  children: ReactNode;
  intro: ReactNode;
};

export function ConversationSurface({
  children,
  intro,
}: ConversationSurfaceProps) {
  return (
    <main className="conversation-surface">
      <div className="conversation-scroll">{intro}</div>
      {children}
    </main>
  );
}
