import type { Citation, SourceLocator } from "../../api/types";

export function CitationDetail({ citation }: { citation: Citation }) {
  return (
    <div className="citation-detail">
      <div className="context-heading">
        <span>已核对资料</span>
        <span className="status-label">版本 {citation.source_version}</span>
      </div>
      <h2>{citation.source_name}</h2>
      <p className="citation-locator">{locatorLabel(citation.locator)}</p>
      {citation.context_before && (
        <section className="citation-context" aria-label="片段之前">
          <span>前文</span>
          <p>{citation.context_before}</p>
        </section>
      )}
      <section className="citation-excerpt" aria-labelledby="citation-excerpt-title">
        <span id="citation-excerpt-title">命中片段</span>
        <blockquote>{citation.excerpt}</blockquote>
      </section>
      {citation.context_after && (
        <section className="citation-context" aria-label="片段之后">
          <span>后文</span>
          <p>{citation.context_after}</p>
        </section>
      )}
      <details className="citation-technical">
        <summary>技术详情</summary>
        <code>{citation.chunk_id}</code>
      </details>
    </div>
  );
}

function locatorLabel(locator: SourceLocator): string {
  switch (locator.kind) {
    case "chunk":
      return locator.label;
    case "pdf":
      return [`第 ${locator.page} 页`, locator.section].filter(Boolean).join(" · ");
    case "docx": {
      const heading = locator.heading_path.join(" › ");
      const paragraph = locator.paragraph ? `第 ${locator.paragraph} 段` : "";
      return [heading, paragraph].filter(Boolean).join(" · ");
    }
    case "pptx":
      return [`第 ${locator.slide} 张幻灯片`, locator.title].filter(Boolean).join(" · ");
    case "xlsx":
      return [`工作表 ${locator.sheet}`, locator.cell_range].filter(Boolean).join(" · ");
    case "image":
      return [locator.filename, locator.region].filter(Boolean).join(" · ");
  }
}
