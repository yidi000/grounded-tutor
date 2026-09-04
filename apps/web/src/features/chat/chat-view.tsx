import type { ChatResponse, Citation } from "../../api/types";
import { AnswerBlock } from "./answer-block";

export type ChatExchange = { question: string; response: ChatResponse };

type ChatViewProps = {
  exchanges: ChatExchange[];
  selectedBlockId: string | null;
  onSelectCitation: (
    citation: Citation,
    blockId: string,
    anchor: HTMLButtonElement,
  ) => void;
  onAddSource: () => void;
  onRephrase: () => void;
};

export function ChatView({
  exchanges,
  selectedBlockId,
  onSelectCitation,
  onAddSource,
  onRephrase,
}: ChatViewProps) {
  return (
    <section className="chat-view" aria-label="对话">
      {exchanges.map(({ question, response }) => {
        const citationById = new Map(
          response.citations.map((citation) => [citation.id, citation]),
        );
        const orderedIds = response.answer_blocks.flatMap((block) => block.citation_ids);
        const citationNumbers = new Map(
          [...new Set(orderedIds)].map((citationId, index) => [citationId, index + 1]),
        );
        return (
          <div className="chat-exchange" key={response.message_id}>
            <div className="user-message"><span>你</span><p>{question}</p></div>
            <div className="assistant-message">
              <div className="assistant-label"><span aria-hidden="true">GT</span><strong>Grounded Tutor</strong></div>
              {response.status === "insufficient_material" ? (
                <div className="insufficient-state">
                  <h2>当前资料不足以支持这个答案</h2>
                  <p>可以补充相关资料，或换一种问法继续。</p>
                  <div className="inline-actions">
                    <button type="button" onClick={onAddSource}>添加相关资料</button>
                    <button type="button" onClick={onRephrase}>换一种问法</button>
                  </div>
                </div>
              ) : (
                response.answer_blocks.map((block) => {
                  const blockKey = `${response.message_id}:${block.id}`;
                  return (
                    <AnswerBlock
                      key={block.id}
                      block={block}
                      citationById={citationById}
                      citationNumbers={citationNumbers}
                      selected={selectedBlockId === blockKey}
                      onSelectCitation={(nextCitation, _blockId, anchor) =>
                        onSelectCitation(nextCitation, blockKey, anchor)
                      }
                    />
                  );
                })
              )}
            </div>
          </div>
        );
      })}
    </section>
  );
}
