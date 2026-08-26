import {useEffect, useMemo, useRef, useState} from "react";
import type {FormEvent} from "react";
import {useNavigate} from "react-router-dom";
import {apiRequest, ApiClientError} from "../lib/api";
import type {CandidateLane, GenerationRunRecord, GenerationTarget, GenerationTargetListResponse, IntentParseResponse, PromptCandidate, TranslationResponse, WorkbenchResponse, WorkspaceDraft, WorkspaceListResponse, WorkspaceRecord} from "../lib/types";
import {EmptyState, ErrorState, LoadingState} from "../components/States";

const profiles = [
  {id: "anima_base_v1", label: "ANIMA Base"},
  {id: "anima_aesthetic_v1", label: "ANIMA Aesthetic"},
  {id: "anima_turbo_v1", label: "ANIMA Turbo"},
];

const laneMeta: Record<CandidateLane, {index: string; label: string; detail: string}> = {
  literal: {index: "L", label: "Literal", detail: "只保留可确定映射的输入"},
  conservative: {index: "C", label: "Conservative", detail: "增加少量高置信相关标签"},
  artist: {index: "A", label: "Artist", detail: "在保守候选上增加一位画师"},
  hybrid: {index: "H", label: "Hybrid", detail: "保留画面计划与明确关系"},
};

export function WorkbenchPage({remoteEnabled = false, naturalLanguageEnabled = false, localTranslationEnabled = false}: {remoteEnabled?: boolean; naturalLanguageEnabled?: boolean; localTranslationEnabled?: boolean}) {
  const navigate = useNavigate();
  const [draft, setDraft] = useState<WorkspaceDraft>({positive_text: "", excluded_text: "", model_profile: "anima_base_v1", input_mode: "concepts", natural_text: ""});
  const [past, setPast] = useState<WorkspaceDraft[]>([]);
  const [future, setFuture] = useState<WorkspaceDraft[]>([]);
  const [result, setResult] = useState<WorkbenchResponse | null>(null);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceRecord | null>(null);
  const [workspaceTitle, setWorkspaceTitle] = useState("未命名工作台");
  const [workspaceList, setWorkspaceList] = useState<WorkspaceRecord[] | null>(null);
  const [workspaceNotice, setWorkspaceNotice] = useState<{kind: "success" | "error"; text: string} | null>(null);
  const [workspaceBusy, setWorkspaceBusy] = useState(false);
  const [generationTargets, setGenerationTargets] = useState<GenerationTarget[]>([]);
  const [selectedTarget, setSelectedTarget] = useState("");
  const [generationBusy, setGenerationBusy] = useState<string | null>(null);
  const [generationNotice, setGenerationNotice] = useState<string | null>(null);
  const [parseInfo, setParseInfo] = useState<IntentParseResponse | null>(null);
  const [translation, setTranslation] = useState<TranslationResponse | null>(null);
  const [translationBusy, setTranslationBusy] = useState(false);
  const [privateKeyPassphrase, setPrivateKeyPassphrase] = useState("");
  const idempotencyKeys = useRef(new Map<string, string>());

  const positiveText = draft.positive_text;
  const excludedText = draft.excluded_text;
  const profile = draft.model_profile;
  const inputMode = draft.input_mode || "concepts";
  const naturalText = draft.natural_text || "";

  const positiveItems = useMemo(() => splitConcepts(positiveText), [positiveText]);
  const excludedItems = useMemo(() => splitConcepts(excludedText), [excludedText]);
  const compatibleTargets = useMemo(
    () => generationTargets.filter((target) => !target.compatible_model_profiles.length || target.compatible_model_profiles.includes(profile)),
    [generationTargets, profile],
  );
  const activeTarget = compatibleTargets.find((target) => targetKey(target) === selectedTarget);
  const translationSource = inputMode === "natural" ? naturalText : positiveText;

  useEffect(() => {
    if (!remoteEnabled) return;
    apiRequest<GenerationTargetListResponse>("/api/v3/generation-targets")
      .then((payload) => setGenerationTargets(payload.items.filter((item) => item.host_fingerprint_ready)))
      .catch((caught) => setGenerationNotice((caught as ApiClientError).message));
  }, [remoteEnabled]);

  useEffect(() => {
    if (!compatibleTargets.some((target) => targetKey(target) === selectedTarget)) {
      setSelectedTarget(compatibleTargets[0] ? targetKey(compatibleTargets[0]) : "");
    }
  }, [compatibleTargets, selectedTarget]);

  function editDraft(patch: Partial<WorkspaceDraft>) {
    const next = {...draft, ...patch};
    if (next.positive_text === draft.positive_text && next.excluded_text === draft.excluded_text && next.model_profile === draft.model_profile && next.input_mode === draft.input_mode && next.natural_text === draft.natural_text) return;
    setPast((items) => [...items.slice(-49), draft]);
    setDraft(next);
    setFuture([]);
    setWorkspaceNotice(null);
    setResult(null);
    setParseInfo(null);
    setTranslation(null);
  }

  function undo() {
    const previous = past[past.length - 1];
    if (!previous) return;
    setPast((items) => items.slice(0, -1));
    setFuture((items) => [draft, ...items].slice(0, 50));
    setDraft(previous);
    setResult(null);
    setParseInfo(null);
  }

  function redo() {
    const next = future[0];
    if (!next) return;
    setFuture((items) => items.slice(1));
    setPast((items) => [...items.slice(-49), draft]);
    setDraft(next);
    setResult(null);
    setParseInfo(null);
  }

  async function saveWorkspace() {
    setWorkspaceBusy(true);
    setWorkspaceNotice(null);
    try {
      const saved = workspace ? await apiRequest<WorkspaceRecord>(`/api/v3/workspaces/${workspace.id}`, {
        method: "PUT",
        body: JSON.stringify({title: workspaceTitle, draft, candidate_snapshot: result, revision: workspace.revision}),
      }) : await apiRequest<WorkspaceRecord>("/api/v3/workspaces", {
        method: "POST",
        body: JSON.stringify({title: workspaceTitle, draft, candidate_snapshot: result}),
      });
      setWorkspace(saved);
      setWorkspaceTitle(saved.title);
      setWorkspaceNotice({kind: "success", text: `已保存 revision ${saved.revision}`});
      setWorkspaceList((items) => items ? [saved, ...items.filter((item) => item.id !== saved.id)] : items);
    } catch (caught) {
      const apiError = caught as ApiClientError;
      setWorkspaceNotice({kind: "error", text: apiError.code === "workspace_revision_conflict" ? "另一个标签页已更新此工作台；请重新打开后再合并。" : apiError.message});
    } finally {
      setWorkspaceBusy(false);
    }
  }

  async function openWorkspaceList() {
    setWorkspaceBusy(true);
    setWorkspaceNotice(null);
    try {
      const payload = await apiRequest<WorkspaceListResponse>("/api/v3/workspaces");
      setWorkspaceList(payload.items);
    } catch (caught) {
      setWorkspaceNotice({kind: "error", text: (caught as ApiClientError).message});
    } finally {
      setWorkspaceBusy(false);
    }
  }

  function loadWorkspace(item: WorkspaceRecord) {
    setWorkspace(item);
    setWorkspaceTitle(item.title);
    setDraft({...item.draft, input_mode: item.draft.input_mode || "concepts", natural_text: item.draft.natural_text || ""});
    setPast([]);
    setFuture([]);
    setResult(item.candidate_snapshot || null);
    setParseInfo(null);
    setError(null);
    setWorkspaceList(null);
    setWorkspaceNotice({kind: "success", text: `已打开 revision ${item.revision}`});
  }

  async function generate(event: FormEvent) {
    event.preventDefault();
    if (inputMode === "natural" ? !naturalText.trim() : !positiveItems.length) return;
    setLoading(true);
    setError(null);
    try {
      let payload: WorkbenchResponse;
      if (inputMode === "natural") {
        const parsed = await apiRequest<IntentParseResponse>("/api/v3/intent/parse", {
          method: "POST",
          body: JSON.stringify({source_text: naturalText, source_language: "zh"}),
        });
        setParseInfo(parsed);
        payload = await apiRequest<WorkbenchResponse>("/api/v3/prompt-candidates", {
          method: "POST",
          body: JSON.stringify({intent: parsed.intent, model_profile: profile}),
        });
      } else {
        setParseInfo(null);
        const elements = [
          ...positiveItems.map((raw, index) => ({
            id: `e_positive_${index + 1}`,
            text: raw.startsWith("!") ? raw.slice(1).trim() : raw,
            state: raw.startsWith("!") ? "locked" : "required",
          })),
          ...excludedItems.map((text, index) => ({id: `e_excluded_${index + 1}`, text, state: "excluded"})),
        ];
        payload = await apiRequest<WorkbenchResponse>("/api/v3/workbench/candidates", {
          method: "POST",
          body: JSON.stringify({
            source_text: [...positiveItems, ...excludedItems.map((item) => `不要 ${item}`)].join("，"),
            source_language: "mixed",
            model_profile: profile,
            elements,
          }),
        });
      }
      setResult(payload);
    } catch (caught) {
      setError(caught as ApiClientError);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  async function copyPrompt(candidate: PromptCandidate, kind: "positive" | "negative") {
    const value = kind === "positive" ? candidate.positive_prompt : candidate.negative_prompt;
    await navigator.clipboard.writeText(value);
    const key = `${candidate.id}:${kind}`;
    setCopied(key);
    window.setTimeout(() => setCopied((current) => current === key ? null : current), 1500);
  }

  async function submitGeneration(candidate: PromptCandidate) {
    if (!result) return;
    const target = compatibleTargets.find((item) => targetKey(item) === selectedTarget);
    if (!target) {
      setGenerationNotice("当前模型没有可用的远程工作流。");
      return;
    }
    setGenerationBusy(candidate.id);
    setGenerationNotice(null);
    let idempotencyKey = idempotencyKeys.current.get(candidate.id);
    if (!idempotencyKey) {
      idempotencyKey = `web-${workspace?.id || "draft"}-${workspace?.revision || 0}-${candidate.id}-${crypto.randomUUID()}`;
      idempotencyKeys.current.set(candidate.id, idempotencyKey);
    }
    try {
      if (target.auth_type === "private_key" && privateKeyPassphrase) {
        await apiRequest<{configured: boolean}>("/api/v3/generation-credentials/private-key-passphrase", {
          method: "POST",
          body: JSON.stringify({remote_profile_id: target.remote_profile_id, passphrase: privateKeyPassphrase}),
        });
        setPrivateKeyPassphrase("");
        setGenerationTargets((items) => items.map((item) => item.remote_profile_id === target.remote_profile_id ? {...item, private_key_passphrase_configured: true} : item));
      }
      await apiRequest<GenerationRunRecord>("/api/v3/generation-runs", {
        method: "POST",
        headers: {"Idempotency-Key": idempotencyKey},
        body: JSON.stringify({
          candidate,
          intent: result.intent,
          project_name: workspaceTitle,
          workspace_id: workspace?.id || null,
          workspace_revision: workspace?.revision || null,
          remote_profile_id: target.remote_profile_id,
          workflow_profile_id: target.workflow_profile_id,
        }),
      });
      idempotencyKeys.current.delete(candidate.id);
      navigate("/generate");
    } catch (caught) {
      setGenerationNotice((caught as ApiClientError).message);
    } finally {
      setGenerationBusy(null);
    }
  }

  async function previewTranslation() {
    if (!translationSource.trim()) return;
    setTranslationBusy(true);
    setTranslation(null);
    setError(null);
    try {
      const payload = await apiRequest<TranslationResponse>("/api/v3/translation", {
        method: "POST",
        body: JSON.stringify({source_text: translationSource, direction: "zh_en"}),
      });
      setTranslation(payload);
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setTranslationBusy(false);
    }
  }

  return (
    <section className="page workbench-page">
      <header className="page-header workbench-header">
        <div><span className="eyebrow">PROMPT WORKBENCH</span><h1>候选工作台</h1><p>先忠实映射输入，再把推荐和画师作为可比较、可移除的增量。</p></div>
        <div className="header-stat"><strong>{result?.candidates.length || "—"}</strong><span>validated lanes</span></div>
      </header>

      <div className="workspace-toolbar">
        <input aria-label="工作台名称" value={workspaceTitle} onChange={(event) => setWorkspaceTitle(event.target.value)} maxLength={200} />
        <span className="workspace-identity">{workspace ? `r${workspace.revision}` : "未保存"}</span>
        <button type="button" onClick={undo} disabled={!past.length} aria-label="撤销">↶</button>
        <button type="button" onClick={redo} disabled={!future.length} aria-label="恢复">↷</button>
        <button type="button" onClick={openWorkspaceList} disabled={workspaceBusy}>打开</button>
        <button type="button" className="workspace-save" onClick={saveWorkspace} disabled={workspaceBusy || !workspaceTitle.trim()}>{workspaceBusy ? "处理中…" : "保存工作台"}</button>
      </div>
      {workspaceNotice && <div className={`workspace-notice workspace-notice--${workspaceNotice.kind}`} role={workspaceNotice.kind === "error" ? "alert" : "status"}>{workspaceNotice.text}</div>}
      {workspaceList && <div className="workspace-picker">
        <div><strong>打开工作台</strong><button type="button" onClick={() => setWorkspaceList(null)} aria-label="关闭工作台列表">×</button></div>
        {workspaceList.length ? workspaceList.map((item) => <button type="button" key={item.id} onClick={() => loadWorkspace(item)}><span>{item.title}</span><small>r{item.revision} · {new Date(item.updated_at).toLocaleString()}</small></button>) : <p>还没有保存的工作台。</p>}
      </div>}

      <div className="input-mode-tabs" role="tablist" aria-label="输入方式">
        <button type="button" role="tab" aria-selected={inputMode === "concepts"} onClick={() => editDraft({input_mode: "concepts"})}>结构化概念</button>
        <button type="button" role="tab" aria-selected={inputMode === "natural"} disabled={!naturalLanguageEnabled} title={naturalLanguageEnabled ? "复用 V2 AI 抽取并进入 V3 管线" : "请先在 V2 设置中配置 AI API Key"} onClick={() => editDraft({input_mode: "natural"})}>自然语言描述</button>
      </div>
      <form className="workbench-composer" onSubmit={generate}>
        <div className="composer-main">
          {inputMode === "natural" ? <>
            <label htmlFor="natural-description">描述你想生成的画面</label>
            <textarea id="natural-description" value={naturalText} onChange={(event) => editDraft({natural_text: event.target.value})} placeholder="可以粘贴小说片段或完整画面描述。系统只抽取当前画面可见事实。" rows={7} />
            <div className="concept-summary"><span>{naturalText.trim().length} 字</span><span>V2 负责抽取 · V3 负责映射、推荐与校验</span></div>
          </> : <>
            <label htmlFor="positive-concepts">希望画面中出现</label>
            <textarea id="positive-concepts" value={positiveText} onChange={(event) => editDraft({positive_text: event.target.value})} placeholder="每行或用逗号分隔，例如：女仆、双马尾、咖啡厅\n在词前加 ! 可锁定" rows={5} />
            <div className="concept-summary"><span>{positiveItems.length} 个正向概念</span><span>输入精确标签、中文名或有效别名</span></div>
          </>}
        </div>
        <div className="composer-side">
          {inputMode === "concepts" ? <>
            <label htmlFor="excluded-concepts">明确排除</label>
            <textarea id="excluded-concepts" value={excludedText} onChange={(event) => editDraft({excluded_text: event.target.value})} placeholder="例如：金发、文字、水印" rows={3} />
          </> : <p className="natural-mode-hint">需要排除的内容请直接写进描述，例如“不要文字和水印”；抽取后会以删除线事实展示。</p>}
          <label htmlFor="model-profile">模型配置</label>
          <select id="model-profile" value={profile} onChange={(event) => editDraft({model_profile: event.target.value})}>
            {profiles.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
          <button className="button generate-button" type="submit" disabled={(inputMode === "natural" ? !naturalText.trim() : !positiveItems.length) || loading}>{loading ? (inputMode === "natural" ? "正在抽取并验证…" : "正在验证…") : (inputMode === "natural" ? "解析并生成候选" : "生成候选")}</button>
        </div>
      </form>

      {localTranslationEnabled && <section className="translation-preview" aria-label="本地翻译预览">
        <div><strong>本地英译预览</strong><span>独立工具，不参与 V3 候选编译</span></div>
        <button type="button" onClick={() => void previewTranslation()} disabled={!translationSource.trim() || translationBusy}>{translationBusy ? "正在本地翻译…" : "翻译当前输入"}</button>
        {translation && <div className="translation-result"><p>{translation.translated_text}</p><small>{translation.engine} · {translation.model_ready ? "本地 Marian 模型" : "内置离线词典"}</small></div>}
      </section>}

      {parseInfo && <section className="intent-review" aria-label="自然语言抽取结果">
        <div><strong>已抽取 {parseInfo.intent.graph.elements.length} 项画面事实</strong><span>{parseInfo.parser.name} · {parseInfo.extraction.summary_zh}</span></div>
        <div className="intent-facts">{parseInfo.intent.graph.elements.map((element) => <span key={element.id} className={element.state === "excluded" ? "is-excluded" : ""}>{element.original_text}<small>{element.type}</small></span>)}</div>
        {parseInfo.intent.scene_plan_en && <details><summary>查看 Hybrid 英文画面计划</summary><p>{parseInfo.intent.scene_plan_en}</p></details>}
        <p className="intent-review-warning">AI 抽取可能归错人物或动作；远程生图前请检查此处和候选说明。</p>
      </section>}

      <div className="workbench-results" aria-live="polite">
        {loading ? <LoadingState label="正在映射标签、计算推荐并验证候选…" /> : error ? (
          <ErrorState message={error.message} requestId={error.requestId} />
        ) : result ? (
          <>
            <div className="validation-strip"><span className="status-dot is-ready" /><strong>安全校验通过</strong><span>{result.candidates.length} 条候选 · {result.data_pack_id}</span></div>
            {remoteEnabled && <div className="generation-submit-bar">
              <div><strong>远程生图</strong><span>{compatibleTargets.length ? "选择 V2 已验证目标后，从候选卡片提交" : "当前模型没有已确认指纹的兼容工作流"}</span></div>
              <select aria-label="远程生成目标" value={selectedTarget} onChange={(event) => setSelectedTarget(event.target.value)} disabled={!compatibleTargets.length}>
                {compatibleTargets.length ? compatibleTargets.map((target) => <option key={targetKey(target)} value={targetKey(target)}>{target.remote_display_name} · {target.workflow_display_name}</option>) : <option value="">无可用目标</option>}
              </select>
              {activeTarget?.auth_type === "private_key" && <label className="passphrase-input"><span>私钥口令（可选，仅本次运行内存）</span><input type="password" autoComplete="current-password" value={privateKeyPassphrase} onChange={(event) => setPrivateKeyPassphrase(event.target.value)} placeholder={activeTarget.private_key_passphrase_configured ? "已在本次运行中设置" : "私钥未加密可留空"} /></label>}
            </div>}
            {generationNotice && <div className="workspace-notice workspace-notice--error" role="alert">{generationNotice}</div>}
            <div className="candidate-grid">
              {result.candidates.map((candidate) => (
                <CandidateCard key={candidate.id} candidate={candidate} copied={copied} onCopy={copyPrompt} onGenerate={remoteEnabled ? submitGeneration : undefined} generationBusy={generationBusy === candidate.id} generationDisabled={!selectedTarget || generationBusy !== null} />
              ))}
            </div>
          </>
        ) : (
          <EmptyState title="从忠实基准开始" detail="输入画面概念后，工作台会并排生成可追踪的候选。自动推荐不会静默加入角色或版权标签。" />
        )}
      </div>
    </section>
  );
}

function CandidateCard({candidate, copied, onCopy, onGenerate, generationBusy = false, generationDisabled = false}: {
  candidate: PromptCandidate;
  copied: string | null;
  onCopy: (candidate: PromptCandidate, kind: "positive" | "negative") => Promise<void>;
  onGenerate?: (candidate: PromptCandidate) => Promise<void>;
  generationBusy?: boolean;
  generationDisabled?: boolean;
}) {
  const meta = laneMeta[candidate.lane];
  const automatic = candidate.tags.filter((tag) => tag.state === "automatic");
  return (
    <article className={`candidate-card candidate-card--${candidate.lane}`}>
      <header className="candidate-header">
        <span className="lane-index">{meta.index}</span>
        <div><span>{meta.label}</span><h2>{candidate.title}</h2><p>{meta.detail}</p></div>
        <span className="candidate-valid">✓ VALID</span>
      </header>
      <PromptBlock label="Positive" value={candidate.positive_prompt} copied={copied === `${candidate.id}:positive`} onCopy={() => onCopy(candidate, "positive")} />
      {candidate.negative_prompt && <PromptBlock label="Negative" value={candidate.negative_prompt} copied={copied === `${candidate.id}:negative`} onCopy={() => onCopy(candidate, "negative")} negative />}
      <div className="candidate-tokens">
        {candidate.tags.map((tag) => <span key={tag.name} className={tag.state === "automatic" ? "is-automatic" : tag.state === "locked" ? "is-locked" : ""} title={tag.reason}>{tag.rendered}</span>)}
        {candidate.artists.map((artist) => <span key={artist.name} className="is-artist" title={artist.reason}>{artist.rendered}</span>)}
      </div>
      <footer className="candidate-footer">
        <span>{candidate.tags.length} tags{candidate.artists.length ? ` · ${candidate.artists.length} artist` : ""}</span>
        <span>{automatic.length ? `${automatic.length} 个自动推荐` : "无自动扩展"}</span>
        {candidate.unresolved_element_ids.length > 0 && <span className="unresolved-count">{candidate.unresolved_element_ids.length} 项未解析</span>}
        {onGenerate && <button type="button" className="candidate-generate" disabled={generationDisabled} onClick={() => void onGenerate(candidate)}>{generationBusy ? "正在提交…" : "远程生图"}</button>}
      </footer>
      {candidate.warnings.length > 0 && <details className="candidate-warnings"><summary>{candidate.warnings.length} 条说明</summary>{candidate.warnings.map((warning) => <p key={`${warning.code}-${warning.message}`}>{warning.message}</p>)}</details>}
    </article>
  );
}

function PromptBlock({label, value, copied, onCopy, negative = false}: {label: string; value: string; copied: boolean; onCopy: () => void; negative?: boolean}) {
  return (
    <div className={`prompt-block${negative ? " prompt-block--negative" : ""}`}>
      <div><span>{label}</span><button type="button" onClick={onCopy}>{copied ? "已复制" : "复制"}</button></div>
      <code>{value}</code>
    </div>
  );
}

function splitConcepts(value: string): string[] {
  return value.split(/[，,;；\n]+/).map((item) => item.trim()).filter(Boolean);
}

function targetKey(target: GenerationTarget): string {
  return `${target.remote_profile_id}::${target.workflow_profile_id}`;
}
