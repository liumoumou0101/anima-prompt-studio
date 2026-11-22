import type {ReactNode} from "react";
import {ChatCircleDots, GearSix, Plus} from "@phosphor-icons/react";
import {layerLabels, type ConversationRecord, type LayerName, type LocalConversation, type RequirementLayers} from "../lib/conversation";
import {conflictValueLabel,type mergeConversation} from "../lib/conversationMerge";
import type {WorkspaceListResponse} from "../lib/types";

type WorkspaceItem = WorkspaceListResponse["items"][number];
type MergeResult = ReturnType<typeof mergeConversation>;

export function WorkbenchHeader({
  record, local, workspaces, archived, busy, pending, draftAtRisk, proposal, conflict, dirty,
  storageWarning, sessionSearch, moreSessions, rename, showLlmToggle, showLlmSettings,
  adviceBusy, thinkingSaving, llmSettingsBusy,
  onSelectSession, onSearchChange, onSearch, onArchivedChange, onLoadMore,
  onStartRename, onRenameChange, onSaveRename, onCancelRename, onArchive,
  onToggleLlmSettings, onStartNew,
}: {
  record: ConversationRecord | null;
  local: LocalConversation | null;
  workspaces: WorkspaceItem[];
  archived: boolean;
  busy: string;
  pending: unknown;
  draftAtRisk: boolean;
  proposal: unknown;
  conflict: boolean;
  dirty: boolean;
  storageWarning: string;
  sessionSearch: string;
  moreSessions: boolean;
  rename: string | null;
  showLlmToggle: boolean;
  showLlmSettings: boolean;
  adviceBusy: boolean;
  thinkingSaving: boolean;
  llmSettingsBusy: boolean;
  onSelectSession: (id: string) => void;
  onSearchChange: (value: string) => void;
  onSearch: () => void;
  onArchivedChange: (archived: boolean) => void;
  onLoadMore: () => void;
  onStartRename: () => void;
  onRenameChange: (value: string) => void;
  onSaveRename: () => void;
  onCancelRename: () => void;
  onArchive: () => void;
  onToggleLlmSettings: () => void;
  onStartNew: () => void;
}) {
  return (
    <header className={`conversation-heading${record && !archived ? " has-session" : ""}`}>
      <div className="conversation-title">
        <h1 className={record && !archived ? "conversation-sr-only" : undefined}>{record?.title || "开始创作"}</h1>
        <div className="conversation-session-select">
          <ChatCircleDots size={19} aria-hidden="true" />
          <select
            aria-label={archived ? "恢复已归档会话" : "打开已有会话"}
            title={archived ? "恢复已归档会话" : "切换会话"}
            value={archived ? "" : record?.id || ""}
            disabled={Boolean(busy || pending || draftAtRisk)}
            onChange={event => {if (event.target.value) onSelectSession(event.target.value);}}
          >
            <option value="">{archived ? "选择会话并恢复" : "打开已有会话…"}</option>
            {record && !archived && !workspaces.some(item => item.id === record.id) && <option value={record.id}>{record.title}</option>}
            {workspaces.map(item => <option key={item.id} value={item.id}>{item.title} · {new Date(item.updated_at).toLocaleDateString()}</option>)}
          </select>
        </div>
        {record && (
          <span className="conversation-save-state" title="修改自动保留为草稿；更新提示词和生成图片时自动保存所需内容。">
            {storageWarning ? "草稿保存需注意" : dirty || local?.delta.trim() ? "草稿已保留" : "已保存"}
          </span>
        )}
        <details className="conversation-session-tools">
          <summary>查找与管理</summary>
          <div className="conversation-session-tools__panel">
            <div className="conversation-actions">
              <input aria-label="搜索会话" value={sessionSearch} onChange={event => onSearchChange(event.target.value)} onKeyDown={event => {if (event.key === "Enter") onSearch();}} placeholder="按会话名称搜索" />
              <button disabled={Boolean(busy)} onClick={onSearch}>搜索</button>
              <label><input type="checkbox" checked={archived} disabled={Boolean(busy)} onChange={event => onArchivedChange(event.target.checked)} />已归档会话</label>
              {moreSessions && <button disabled={Boolean(busy)} onClick={onLoadMore}>加载更多会话</button>}
              {record && (
                <>
                  <button disabled={Boolean(busy || pending || proposal || conflict)} onClick={onStartRename}>重命名当前会话</button>
                  <button disabled={Boolean(busy || pending || proposal || dirty || conflict || local?.delta.trim())} onClick={onArchive}>归档当前会话</button>
                </>
              )}
            </div>
            {rename !== null && (
              <div className="conversation-actions">
                <input aria-label="会话名称" maxLength={200} value={rename} onChange={event => onRenameChange(event.target.value)} />
                <button disabled={Boolean(busy) || !rename.trim()} onClick={onSaveRename}>保存名称</button>
                <button onClick={onCancelRename}>取消改名</button>
              </div>
            )}
          </div>
        </details>
      </div>
      <div className="conversation-actions conversation-toolbar">
        {showLlmToggle && (
          <button aria-expanded={showLlmSettings} aria-controls="conversation-llm-settings" disabled={Boolean(busy || adviceBusy || thinkingSaving || llmSettingsBusy)} onClick={onToggleLlmSettings}>
            <GearSix size={17} aria-hidden="true" />LLM 设置
          </button>
        )}
        <button className="conversation-new" disabled={Boolean(busy || pending || draftAtRisk)} onClick={onStartNew}><Plus size={16} aria-hidden="true" />新会话</button>
      </div>
    </header>
  );
}

export function ConflictPanel({
  merge, conflictChoices, busy, onChoiceChange, onResolve, onBranch, onAdoptRemote,
}: {
  merge: MergeResult | null;
  conflictChoices: Record<string, "local" | "remote">;
  busy: boolean;
  onChoiceChange: (path: string, choice: "local" | "remote") => void;
  onResolve: () => void;
  onBranch: () => void;
  onAdoptRemote: () => void;
}) {
  return (
    <section role="alert" className="conversation-conflict">
      <strong>其他窗口已保存了更新，你的编辑仍在这里。</strong>
      {merge ? (
        <>
          <p>不同字段的修改会一起保留；同一字段有分歧时，请逐项选择。</p>
          {merge.conflicts.map(item => (
            <fieldset key={item.path}>
              <legend>{item.label}</legend>
              <label>
                <input type="radio" name={`conflict-${item.path}`} checked={conflictChoices[item.path] === "local"} onChange={() => onChoiceChange(item.path, "local")} />
                保留本窗口：<pre>{conflictValueLabel(item,"local")}</pre>
              </label>
              <label>
                <input type="radio" name={`conflict-${item.path}`} checked={conflictChoices[item.path] === "remote"} onChange={() => onChoiceChange(item.path, "remote")} />
                采用服务端：<pre>{conflictValueLabel(item,"remote")}</pre>
              </label>
            </fieldset>
          ))}
          <button disabled={merge.conflicts.some(item => !conflictChoices[item.path])} onClick={onResolve}>
            {merge.conflicts.length ? "应用所选合并结果" : "合并双方修改"}
          </button>
        </>
      ) : (
        <p>这份旧草稿缺少共同版本，无法安全自动合并。可将本窗口内容另存为新会话，原会话的更新会完整保留。</p>
      )}
      <button disabled={busy} onClick={onBranch}>将本窗口草稿另存为新会话</button>
      <button onClick={onAdoptRemote}>采用服务端版本</button>
    </section>
  );
}

export function PendingSubmissionPanel({
  pending, showPendingEnvironment, pendingState, executionEnvironmentControl, optionalRequests, busy,
  onQueryCurrent, onQueryDirect, onForgetDirect,
}: {
  pending: boolean;
  showPendingEnvironment: boolean;
  pendingState?: string;
  executionEnvironmentControl: ReactNode;
  optionalRequests: {key: string; body: string}[];
  busy: boolean;
  onQueryCurrent: () => void;
  onQueryDirect: (request: {key: string; body: string}) => void;
  onForgetDirect: (request: {key: string; body: string}) => void;
}) {
  return (
    <>
      {pending && (
        <section className="conversation-conflict" aria-label="本次提交状态" aria-busy={busy}>
          {showPendingEnvironment ? (
            <><strong>{pendingState === "resolving" ? "正在检查本次生成" : "本次生成尚未接受"}</strong>{executionEnvironmentControl}</>
          ) : (
            <><p>上次生成请求的接受结果尚未确认。请先查询原请求。</p><button disabled={busy} onClick={onQueryCurrent}>查询本次提交</button></>
          )}
        </section>
      )}
      {optionalRequests.length > 0 && (
        <section className="conversation-conflict" aria-label="未确认的提交">
          <p>有 {optionalRequests.length} 条提交的结果尚未确认。可以继续编辑、换连接或新建会话；旧任务仍可能完成。</p>
          {optionalRequests.map((request, index) => (
            <div key={request.key}>
              <span>旧提交 {index + 1} </span>
              <button aria-label={optionalRequests.length > 1 ? `查询旧提交 ${index + 1} 的结果` : undefined} disabled={busy || pending} onClick={() => onQueryDirect(request)}>查询旧提交结果</button>
              <button aria-label={optionalRequests.length > 1 ? `忽略旧提交 ${index + 1} 的记录` : undefined} disabled={busy} onClick={() => onForgetDirect(request)}>忽略这条记录</button>
            </div>
          ))}
        </section>
      )}
    </>
  );
}

export function LayerRequirementsEditor({
  layers, onLayerChange,
}: {
  layers: RequirementLayers;
  onLayerChange: <K extends LayerName>(name: K, patch: Partial<RequirementLayers[K]>) => void;
}) {
  const generalTags = layers.subject.general_tags || [];
  return (
    <details>
      <summary>分层画面要求与锁定</summary>
      <div aria-label="明确选择的普通标签">
        <strong>已选普通标签 · {generalTags.length} / 64</strong>
        {generalTags.map(tag => (
          <span key={tag}>
            {" "}{tag}{" "}
            <button aria-label={`移除普通标签 ${tag}`} onClick={() => onLayerChange("subject", {general_tags: generalTags.filter(value => value !== tag)})}>移除</button>
          </span>
        ))}
      </div>
      <p className="conversation-muted">
        这里锁定整组中文要求。只想保留人物特征，同时修改服装或动作时，可在提示词页固定相应英文片段。已锁定 {Object.values(layers).filter(item => item.locked).length} 组。
      </p>
      {(Object.keys(layerLabels) as LayerName[]).map(name => (
        <div className="conversation-layer" key={name}>
          <div className="conversation-actions">
            <strong>{layerLabels[name]}</strong>
            <label>
              <input type="checkbox" aria-label={`锁定${layerLabels[name]}要求`} checked={layers[name].locked} onChange={event => onLayerChange(name, {locked: event.target.checked})} />
              锁定改写
            </label>
          </div>
          {name !== "exclusions" ? (
            <textarea aria-label={`${layerLabels[name]}要求`} rows={2} value={layers[name].text} onChange={event => onLayerChange(name, {text: event.target.value})} />
          ) : (
            <>
              <label>全局排除（每行一项）<textarea value={layers.exclusions.global.join("\n")} onChange={event => onLayerChange("exclusions", {global: event.target.value.split("\n")})} /></label>
              {layers.exclusions.scoped.map((item, i) => (
                <div className="conversation-actions" key={i}>
                  <input aria-label={`排除对象 ${i + 1}`} value={item.target} onChange={event => onLayerChange("exclusions", {scoped: layers.exclusions.scoped.map((entry, index) => index === i ? {...entry, target: event.target.value} : entry)})} />
                  <input aria-label={`排除内容 ${i + 1}`} value={item.concept} onChange={event => onLayerChange("exclusions", {scoped: layers.exclusions.scoped.map((entry, index) => index === i ? {...entry, concept: event.target.value} : entry)})} />
                  <button onClick={() => onLayerChange("exclusions", {scoped: layers.exclusions.scoped.filter((_, index) => index !== i)})}>移除</button>
                </div>
              ))}
              <button onClick={() => onLayerChange("exclusions", {scoped: [...layers.exclusions.scoped, {target: "", concept: ""}]})}>添加局部排除</button>
            </>
          )}
          {name === "style" && <label>媒介<input value={layers.style.medium} onChange={event => onLayerChange("style", {medium: event.target.value})} /></label>}
          {name === "composition" && <label>景别<input value={layers.composition.shot} onChange={event => onLayerChange("composition", {shot: event.target.value})} /></label>}
        </div>
      ))}
    </details>
  );
}
