import type { ReactNode } from "react";

type ConversationSurfaceProps = {
  children: ReactNode;
  intro: ReactNode;
  onFileDrop?: (file: File) => void;
};

export function ConversationSurface({
  children,
  intro,
  onFileDrop,
}: ConversationSurfaceProps) {
  return (
    <main className="conversation-surface" onDragOver={onFileDrop ? (event) => event.preventDefault() : undefined} onDrop={onFileDrop ? (event) => { event.preventDefault(); const file = event.dataTransfer.files[0]; if (file) onFileDrop(file); } : undefined}>
      <div className="conversation-scroll">{intro}</div>
      {children}
    </main>
  );
}
