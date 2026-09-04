import { useState } from "react";

import type { AppMode } from "../config";

type ComposerProps = {
  mode: AppMode;
  onAddSource?: () => void;
  ready?: boolean;
  onSubmit?: (question: string) => Promise<void>;
};

export function Composer({ mode, onAddSource, ready = false, onSubmit }: ComposerProps) {
  const isDemo = mode === "demo_read_only";
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState(false);
  const enabled = !isDemo && ready && Boolean(onSubmit);

  async function send() {
    const question = draft.trim();
    if (!enabled || !question || sending) return;
    setSending(true);
    setFailed(false);
    try {
      await onSubmit?.(question);
      setDraft("");
    } catch {
      setFailed(true);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="composer-wrap">
      <label className="composer-label" htmlFor="study-question">
        继续提问
      </label>
      <div className="composer">
        {!isDemo && onAddSource && <button className="composer-add" type="button" onClick={onAddSource}>＋ 添加资料</button>}
        <textarea
          id="study-question"
          aria-label="向资料提问"
          disabled={!enabled}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={
            isDemo
              ? "只读示例暂不接受新的问题"
              : ready ? "输入你想从资料中了解的问题" : "至少一份资料就绪后可以提问"
          }
          rows={2}
        />
        <button className="composer-send" type="button" disabled={!enabled || !draft.trim() || sending} onClick={() => void send()}>
          {sending ? "发送中" : "发送"}
        </button>
      </div>
      {failed && <p className="composer-error" role="alert">当前无法完成提问，请保留内容后重试。</p>}
      <p>
        {isDemo
          ? "这是预先生成的回答；真实提问请使用本地版本。"
          : ready ? "回答只使用当前主题中已就绪的资料。" : "接受至少一份资料后开放提问。"}
      </p>
    </div>
  );
}
