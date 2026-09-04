import type { AppMode } from "../config";

type ComposerProps = {
  mode: AppMode;
  onAddSource?: () => void;
};

export function Composer({ mode, onAddSource }: ComposerProps) {
  const isDemo = mode === "demo_read_only";

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
          disabled
          placeholder={
            isDemo
              ? "只读示例暂不接受新的问题"
              : "问答将在引用界面准备好后开放"
          }
          rows={2}
        />
        <span className="composer-state">{isDemo ? "只读示例" : "准备中"}</span>
      </div>
      <p>
        {isDemo
          ? "此页面不会保存输入或发送请求。"
          : "资料与问答操作将在下一阶段接入。"}
      </p>
    </div>
  );
}
