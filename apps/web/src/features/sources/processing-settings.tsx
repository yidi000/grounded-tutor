import { useEffect, useState } from "react";

import type {
  ChunkSettings,
  SourceIngestionCapabilities,
} from "../../api/types";

type ProcessingSettingsProps = {
  invalid?: boolean;
  value: ChunkSettings;
  capabilities: SourceIngestionCapabilities;
  onChange: (value: ChunkSettings) => void;
};

function Help({ purpose, effect, recommendation }: { purpose: string; effect: string; recommendation: string }) {
  return <div className="field-help"><p>{purpose}</p><details><summary>设置建议</summary><p>{effect}</p><p>推荐：{recommendation}</p></details></div>;
}

export function ProcessingSettings({ value, capabilities, onChange, invalid = false }: ProcessingSettingsProps) {
  const [advanced, setAdvanced] = useState(false);
  useEffect(() => { if (invalid) setAdvanced(true); }, [invalid]);
  const pdfCapability = capabilities.settings.find((item) => item.key === "customPdfParse");
  const pdfEnabled = pdfCapability?.supported === true;
  const custom = value.chunkSettingMode === "custom";
  const separatorEnabled = custom && value.chunkSplitMode === "char";
  const qaEnabled = value.trainingType === "qa";
  const splitLabel = { paragraph: "按段落", size: "按长度", char: "按指定分隔符" }[value.chunkSplitMode];
  const set = <K extends keyof ChunkSettings>(key: K, next: ChunkSettings[K]) => onChange({ ...value, [key]: next });

  return (
    <section className="processing-settings" aria-labelledby="settings-title">
      <div className="settings-summary">
        <div><h3 id="settings-title">{!custom && !qaEnabled ? "推荐设置" : "当前设置"}</h3>
          <p role="status" aria-label="当前处理设置">{qaEnabled ? "问答对" : "原文片段"} · {custom ? `自定义 · ${splitLabel}` : "系统推荐"}</p>
        </div>
        <p>{custom ? "按下面的设置整理资料，处理后仍需复核。" : "系统推荐按段落预览；需要指定分段方式或分隔符时，选择自定义。"}</p>
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
            <select disabled={!custom} aria-describedby="split-mode-help" id="chunkSplitMode" value={value.chunkSplitMode} onChange={(event) => set("chunkSplitMode", event.target.value as ChunkSettings["chunkSplitMode"])}><option value="paragraph">按段落</option><option value="size">按长度</option><option value="char">按指定分隔符</option></select>
            <p id="split-mode-help" className="setting-state">{custom ? "已启用 · 选择片段边界" : "系统控制 · 选择“自定义”后可修改"}</p>
            <Help purpose="决定长资料在哪里切开。" effect="自然边界更易阅读，固定长度更可预测。" recommendation="结构清晰的资料按段落" />
          </div>
          <div className="setting-field">
            <label className="field-label" htmlFor="chunkSize">片段长度</label>
            <input disabled={!custom} aria-describedby="chunk-size-help" id="chunkSize" type="number" min={100} max={3000} value={value.chunkSize} onChange={(event) => set("chunkSize", Number(event.target.value))} />
            <p id="chunk-size-help" className="setting-state">{custom ? "填写片段目标长度，实际片段以处理结果为准。" : "系统控制 · 此自定义值暂不应用，切换“自定义”后可修改。"}</p>
            <Help purpose="控制每个资料片段的最大长度。" effect="影响每个片段保留多少上下文；过大会混入无关内容，过小会割裂概念。" recommendation="1000，通常在 500–1500 之间" />
          </div>
          <div className="setting-field">
            <label className="field-label" htmlFor="chunkSplitter">自定义分隔符</label>
            <input id="chunkSplitter" maxLength={20} value={value.chunkSplitter} onChange={(event) => set("chunkSplitter", event.target.value)} disabled={!separatorEnabled} aria-describedby="splitter-help" placeholder={separatorEnabled ? "例如 ###，须与资料中的标记一致" : "未启用"} />
            <p id="splitter-help" className="setting-state">{separatorEnabled ? "必填 · 输入资料中实际出现的分隔标记，最多 20 个字符。" : "未启用 · 选择“自定义”及“按指定分隔符”后可填写。"}</p>
          </div>
          <div className="setting-field wide-setting">
            <label className="field-label" htmlFor="qaPrompt">问答提取要求</label>
            <textarea id="qaPrompt" maxLength={4000} value={value.qaPrompt} onChange={(event) => set("qaPrompt", event.target.value)} disabled={!qaEnabled} aria-describedby="qa-prompt-help" placeholder={qaEnabled ? "例如：围绕关键概念提问，答案保留定义与例子。" : "未启用"} rows={3} />
            <p id="qa-prompt-help" className="setting-state">{qaEnabled ? "可选 · 填写复习重点和答案要求；留空使用系统默认要求。" : "未启用 · 保存方式选择“问答对”后可填写。"}</p>
          </div>

          <h4>内容怎样被检索</h4>
          <div className="setting-field checkbox-setting">
            <label><input type="checkbox" checked={value.indexPrefixTitle} onChange={(event) => set("indexPrefixTitle", event.target.checked)} aria-label="将标题加入索引" />将标题加入索引</label>
            <Help purpose="把标题也用于检索匹配。" effect="提升章节名称命中，也会增加少量索引内容。" recommendation="有清晰标题的资料开启" />
          </div>
          <div className="setting-field">
            <label className="field-label" htmlFor="indexSize">索引内容长度</label>
            <input disabled={!custom} aria-describedby="index-size-help" id="indexSize" type="number" min={32} max={value.chunkSize} value={value.indexSize} onChange={(event) => set("indexSize", Number(event.target.value))} />
            <p id="index-size-help" className="setting-state">{custom ? "已启用 · 不要超过片段长度" : "系统控制 · 此自定义值暂不应用"}</p>
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
