import type { Citation, GroundedContentBlock } from "../../api/types";
import { EvidenceAnchor } from "./evidence-anchor";

type AnswerBlockProps = {
  block: GroundedContentBlock;
  citationById: ReadonlyMap<string, Citation>;
  citationNumbers: ReadonlyMap<string, number>;
  selected: boolean;
  onSelectCitation: (
    citation: Citation,
    blockId: string,
    anchor: HTMLButtonElement,
  ) => void;
};

export function AnswerBlock({
  block,
  citationById,
  citationNumbers,
  selected,
  onSelectCitation,
}: AnswerBlockProps) {
  const citations = block.citation_ids.flatMap((citationId) => {
    const citation = citationById.get(citationId);
    if (!citation) {
      if (import.meta.env.DEV) {
        console.warn("Missing citation for answer block", block.id, citationId);
      }
      return [];
    }
    return [citation];
  });

  return (
    <article
      className={`answer-block${selected ? " answer-block-selected" : ""}`}
    >
      <p>{block.text}</p>
      {citations.length > 0 && (
        <div className="evidence-anchors" aria-label="这段回答的依据">
          {citations.map((citation) => (
            <EvidenceAnchor
              key={citation.id}
              citation={citation}
              number={citationNumbers.get(citation.id) ?? 1}
              onSelect={(anchor) =>
                onSelectCitation(citation, block.id, anchor)
              }
            />
          ))}
        </div>
      )}
    </article>
  );
}
