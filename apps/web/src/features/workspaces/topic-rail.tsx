import type { AppMode } from "../../config";
import { demoFixture } from "../../demo/fixture";

type TopicRailProps = {
  mode: AppMode;
};

export function TopicRail({ mode }: TopicRailProps) {
  const isDemo = mode === "demo_read_only";

  return (
    <nav className="topic-rail" aria-label="学习主题">
      <p className="rail-eyebrow">学习主题</p>
      {isDemo ? (
        <div className="topic-entry topic-entry-active" aria-current="page">
          <span className="sample-label">{demoFixture.topic.label}</span>
          <strong>{demoFixture.topic.title}</strong>
          <span>固定 · 只读</span>
        </div>
      ) : (
        <div className="topic-entry topic-entry-empty">
          <strong>还没有主题</strong>
          <span>资料能力读取完成后，这里会显示你的学习主题。</span>
        </div>
      )}
      <p className="rail-footnote">每个主题保留自己的资料和对话。</p>
    </nav>
  );
}
