export function ContextPanel() {
  return (
    <aside className="context-panel" aria-label="上下文">
      <div className="proof-tab" aria-hidden="true" />
      <div className="context-heading">
        <span>核对区</span>
        <span className="status-label">等待依据</span>
      </div>
      <h2>上下文</h2>
      <div className="context-empty">
        <span className="context-glyph" aria-hidden="true">
          引
        </span>
        <h3>回答依据会显示在这里</h3>
        <p>之后选择回答里的引用，就能在这一栏核对资料片段和原始位置。</p>
      </div>
      <p className="context-note">当前还没有可核对的回答。</p>
    </aside>
  );
}
