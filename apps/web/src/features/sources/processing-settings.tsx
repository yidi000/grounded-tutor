import { useState } from "react";

import type {
  ChunkSettings,
  SourceIngestionCapabilities,
} from "../../api/types";

type ProcessingSettingsProps = {
  value: ChunkSettings;
  capabilities: SourceIngestionCapabilities;
  onChange: (value: ChunkSettings) => void;
};

function Help({ purpose, effect, recommendation }: { purpose: string; effect: string; recommendation: string }) {
  return <p className="field-help"><span>{purpose}</span><span>{effect}</span><strong>推荐：{recommendation}</strong></p>;
}

export function ProcessingSettings({ value, capabilities, onChange }: ProcessingSettingsProps) {
  const [advanced, setAdvanced] = useState(false);
  const pdfCapability = capabilities.settings.find((item) => item.key === "customPdfParse");
  const pdfEnabled = pdfCapability?.supported === true;
  const set = <K extends keyof ChunkSettings>(key: K, next: ChunkSettings[K]) => onChange({ ...value, [key]: next });

  return (
    <section className="processing-settings" aria-labelledby="settings-title">
      <div className="settings-summary">
        <div><span className="eyebrow">处理方式</span><h3 id="settings-title">推荐设置</h3></div>
        <p>按段落保留原文，兼顾上下文与检索精度。</p>
      </div>
      <button className="text-button" type="button" aria-expanded={advanced} onClick={() => setAdvanced((open) => !open)}>高级设置</button>
      {advanced && (
        <div className="advanced-grid">
          <h4>内容怎样被整理</h4>
          <div className="setting-field">
            <label className="field-label" htmlFor="trainingType">保存方式</label>
            <select id="trainingType" value={value.trainingType} onChange={(event) => set("trainingType", event.target.value as ChunkSettings["trainingType"])}><option value="chunk">原文片段</option><option value="qa">问答对</option></select>
            <Help purpose="决定保存原文片段还是提取问答对。" effect="问答对更聚焦，原文片段保留更多上下文。" recommendation="学习讲义优先使用原文片段" />
          </div>
          <div className="setting-field">
            <label className="field-label" htmlFor="chunkSettingMode">分块规则</label>
            <select id="chunkSettingMode" value={value.chunkSettingMode} onChange={(event) => set("chunkSettingMode", event.target.value as ChunkSettings["chunkSettingMode"])}><option value="auto">系统推荐</option><option value="custom">自定义</option></select>
            <Help purpose="决定由系统还是由你控制分块细节。" effect="自定义更灵活，也更容易产生不合适的片段。" recommendation="先使用系统推荐" />
          </div>
          <div className="setting-field">
            <label className="field-label" htmlFor="chunkSplitMode">分段方式</label>
            <select id="chunkSplitMode" value={value.chunkSplitMode} onChange={(event) => set("chunkSplitMode", event.target.value as ChunkSettings["chunkSplitMode"])}><option value="paragraph">按段落</option><option value="size">按长度</option><option value="char">按指定分隔符</option></select>
            <Help purpose="决定长资料在哪里切开。" effect="自然边界更易阅读，固定长度更可预测。" recommendation="结构清晰的资料按段落" />
          </div>
          <div className="setting-field">
            <label className="field-label" htmlFor="chunkSize">片段长度</label>
            <input id="chunkSize" type="number" min={100} max={3000} value={value.chunkSize} onChange={(event) => set("chunkSize", Number(event.target.value))} />
            <Help purpose="控制每个资料片段的最大长度。" effect="影响每个片段保留多少上下文；过大会混入无关内容，过小会割裂概念。" recommendation="1000，通常在 500–1500 之间" />
          </div>
          <div className="setting-field">
            <label className="field-label" htmlFor="chunkSplitter">自定义分隔符</label>
            <input id="chunkSplitter" maxLength={20} value={value.chunkSplitter} onChange={(event) => set("chunkSplitter", event.target.value)} disabled={value.chunkSplitMode !== "char"} />
            <Help purpose="用指定字符识别片段边界。" effect="只在按指定分隔符时生效。" recommendation="资料有统一标记时使用" />
          </div>
          <div className="setting-field wide-setting">
            <label className="field-label" htmlFor="qaPrompt">问答提取要求</label>
            <textarea id="qaPrompt" maxLength={4000} value={value.qaPrompt} onChange={(event) => set("qaPrompt", event.target.value)} disabled={value.trainingType !== "qa"} rows={3} />
            <Help purpose="告诉系统怎样从资料中整理问题与答案。" effect="要求越具体，生成的问答对越贴近复习目标。" recommendation="仅在选择问答对时填写" />
          </div>

          <h4>内容怎样被检索</h4>
          <div className="setting-field checkbox-setting">
            <label><input type="checkbox" checked={value.indexPrefixTitle} onChange={(event) => set("indexPrefixTitle", event.target.checked)} aria-label="将标题加入索引" />将标题加入索引</label>
            <Help purpose="把标题也用于检索匹配。" effect="提升章节名称命中，也会增加少量索引内容。" recommendation="有清晰标题的资料开启" />
          </div>
          <div className="setting-field">
            <label className="field-label" htmlFor="indexSize">索引内容长度</label>
            <input id="indexSize" type="number" min={32} max={value.chunkSize} value={value.indexSize} onChange={(event) => set("indexSize", Number(event.target.value))} />
            <Help purpose="控制每个片段用于搜索的文字量。" effect="更多文字提高关键词覆盖，也可能增加噪音与成本。" recommendation="256，且不要超过片段长度" />
          </div>

          <h4>特殊资料处理</h4>
          <div className="setting-field checkbox-setting">
            <label><input type="checkbox" checked={value.customPdfParse} onChange={(event) => set("customPdfParse", event.target.checked)} disabled={!pdfEnabled} aria-label="增强 PDF 解析" />增强 PDF 解析</label>
            <Help purpose="为复杂排版或扫描 PDF 使用增强读取。" effect="可能改善表格与版面理解，并增加处理成本。" recommendation="普通文字 PDF 保持关闭" />
            {!pdfEnabled && <p className="disabled-reason">当前部署尚未验证此能力</p>}
          </div>
        </div>
      )}
    </section>
  );
}
