import type { Citation } from "../../api/types";

type EvidenceAnchorProps = {
  citation: Citation;
  number: number;
  onSelect: (anchor: HTMLButtonElement) => void;
};

export function EvidenceAnchor({ citation, number, onSelect }: EvidenceAnchorProps) {
  return (
    <button
      className="evidence-anchor"
      type="button"
      aria-label={`引用 ${number}：${citation.source_name}`}
      onClick={(event) => onSelect(event.currentTarget)}
    >
      <span aria-hidden="true">{number}</span>
      <span>{citation.source_name}</span>
    </button>
  );
}
