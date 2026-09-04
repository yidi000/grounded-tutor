import { render } from "@testing-library/react";
import { useRef, useState } from "react";

import type { ChatResponse, Citation } from "../api/types";
import { AppShell } from "../components/app-shell";
import { Composer } from "../components/composer";
import { ContextPanel } from "../components/context-panel";
import { ConversationSurface } from "../components/conversation-surface";
import { ChatView, type ChatExchange } from "../features/chat/chat-view";

export function renderChatApp(value: ChatResponse | ChatExchange[]) {
  const exchanges = Array.isArray(value)
    ? value
    : [{ question: "What is a mean?", response: value }];
  return render(<ChatHarness exchanges={exchanges} />);
}

function ChatHarness({ exchanges }: { exchanges: ChatExchange[] }) {
  const [citation, setCitation] = useState<Citation | null>(null);
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);

  function closeCitation() {
    setCitation(null);
    setSelectedBlockId(null);
    window.setTimeout(() => trigger.current?.focus(), 0);
  }

  return (
    <AppShell
      topicRail={<nav aria-label="学习主题">测试主题</nav>}
      conversation={
        <ConversationSurface
          intro={<h1>Intro Statistics</h1>}
          activity={
            <ChatView
              exchanges={exchanges}
              selectedBlockId={selectedBlockId}
              onAddSource={() => undefined}
              onRephrase={() => undefined}
              onSelectCitation={(nextCitation, blockId, anchor) => {
                trigger.current = anchor;
                setCitation(nextCitation);
                setSelectedBlockId(blockId);
              }}
            />
          }
        >
          <Composer mode="local" ready onSubmit={async () => undefined} />
        </ConversationSurface>
      }
      contextPanel={
        <ContextPanel citation={citation} onCloseCitation={closeCitation} />
      }
    />
  );
}
