import {useEffect, useMemo, useRef, useState} from "react";
import {useNavigate} from "react-router-dom";
import {ApiClientError, apiRequest} from "../lib/api";
import {storeDirectImport} from "../lib/directPrompt";
import {applyAspect, applyGenerationRecipe, defaultGenerationSettings, findGenerationRecipe, markGenerationCustom, resolvedGenerationSettings} from "../lib/generationSettings";
import type {DirectPromptPreview, GenerationRunRecord, GenerationTarget, GenerationTargetListResponse, ModelProfileOption, WorkbenchGenerationSettings} from "../lib/types";
import {ErrorState} from "../components/States";

const DRAFT_KEY = "anima-v3-direct-prompt-draft";
const GENERATION_TARGET_KEY = "anima-v3-generation-target";
const PREFERRED_REMOTE_KEY = "anima-v3-preferred-remote";
const FALLBACK_PROFILES = [
  {id: "anima_base_v1", label: "ANIMA Base"},
  {id: "anima_aesthetic_v1", label: "ANIMA Aesthetic"},
  {id: "anima_turbo_v1", label: "ANIMA Turbo"},
];
const aspectLabels: Record<WorkbenchGenerationSettings["aspect"], string> = {portrait: "竖图 896×1152", landscape: "横图 1152×896", square: "方形 1024×1024", custom: "自定义尺寸", model_default: "模型默认"};

type DirectDraft = {
  project_name: string;
  positive_prompt: string;
  negative_prompt: string;
  model_profile: string;
  generation_settings: WorkbenchGenerationSettings;
};

const emptyDraft: DirectDraft = {
  project_name: "英文提示词直出",
  positive_prompt: "",
  negative_prompt: "",
  model_profile: "anima_aesthetic_v1",
  generation_settings: defaultGenerationSettings(),
};

export function DirectPromptPage({modelProfiles, remoteEnabled = false}: {modelProfiles?: ModelProfileOption[]; remoteEnabled?: boolean}) {
  const profiles = modelProfiles?.length
    ? modelProfiles.map((item) => ({id: item.id, label: item.display_name}))
    : FALLBACK_PROFILES;
  const navigate = useNavigate();
  const [draft, setDraft] = useState<DirectDraft>(loadDraft);
  const [preview, setPreview] = useState<DirectPromptPreview | null>(null);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [generationBusy, setGenerationBusy] = useState(false);
  const [generationTargets, setGenerationTargets] = useState<GenerationTarget[]>([]);
  const [selectedTarget, setSelectedTarget] = useState(() => {
    if (draft.generation_settings.remote_profile_id && draft.generation_settings.workflow_profile_id) return `${draft.generation_settings.remote_profile_id}::${draft.generation_settings.workflow_profile_id}`;
    try { return localStorage.getItem(GENERATION_TARGET_KEY) || ""; } catch { return ""; }
  });
  const [preferredRemoteId, setPreferredRemoteId] = useState(() => {
    try {
      return localStorage.getItem(PREFERRED_REMOTE_KEY)
        || (localStorage.getItem(GENERATION_TARGET_KEY) || "").split("::")[0]
        || "";
    } catch { return ""; }
  });
  const [privateKeyPassphrase, setPrivateKeyPassphrase] = useState("");
  const idempotencyKey = useRef<string | null>(null);

  const compatibleTargets = useMemo(() => generationTargets.filter((target) => (
    target.compatible_model_profiles.includes(draft.model_profile)
  )), [generationTargets, draft.model_profile]);
  const remoteConnections = useMemo(() => {
    const unique = new Map<string, GenerationTarget>();
    for (const target of compatibleTargets) {
      if (!unique.has(target.remote_profile_id)) unique.set(target.remote_profile_id, target);
    }
    return [...unique.values()];
  }, [compatibleTargets]);
  const [selectedRemoteId, selectedWorkflowId] = selectedTarget.split("::");
  const connectionWorkflows = useMemo(() => compatibleTargets.filter((target) => target.remote_profile_id === selectedRemoteId), [compatibleTargets, selectedRemoteId]);
  const activeTarget = compatibleTargets.find((target) => targetKey(target) === selectedTarget);

  useEffect(() => {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)); } catch { /* best-effort */ }
  }, [draft]);

  useEffect(() => {
    if (!remoteEnabled) return;
    apiRequest<GenerationTargetListResponse>("/api/v3/generation-targets")
      .then((payload) => {
        setGenerationTargets(payload.items);
        if (payload.preferred_remote_profile_id) {
          setPreferredRemoteId(payload.preferred_remote_profile_id);
          try { localStorage.setItem(PREFERRED_REMOTE_KEY, payload.preferred_remote_profile_id); } catch { /* best-effort */ }
        }
      })
      .catch((caught) => setNotice((caught as ApiClientError).message));
  }, [remoteEnabled]);

  useEffect(() => {
    if (!compatibleTargets.length) return;
    const preferred = preferredRemoteId && compatibleTargets.find((item) => item.remote_profile_id === preferredRemoteId);
    const current = compatibleTargets.find((item) => targetKey(item) === selectedTarget);
    const next = current || preferred || compatibleTargets[0];
    const key = targetKey(next);
    if (key !== selectedTarget || (!findGenerationRecipe(next, draft.generation_settings.preset_id) && draft.generation_settings.preset_id !== "custom")) {
      chooseGenerationTarget(next);
    }
  }, [compatibleTargets, preferredRemoteId, selectedTarget, draft.generation_settings.preset_id]);

  function editDraft(patch: Partial<DirectDraft>) {
    setDraft((current) => ({...current, ...patch}));
    setPreview(null);
    idempotencyKey.current = null;
  }

  function chooseGenerationTarget(target: GenerationTarget) {
    const key = targetKey(target);
    setSelectedTarget(key);
    try { localStorage.setItem(GENERATION_TARGET_KEY, key); } catch { /* best-effort */ }
    setDraft((current) => {
      const settings = current.generation_settings;
      const sameTarget = settings.remote_profile_id === target.remote_profile_id && settings.workflow_profile_id === target.workflow_profile_id;
      const compatibleRecipe = Boolean(findGenerationRecipe(target, settings.preset_id)) || settings.preset_id === "custom";
      return {...current, generation_settings: sameTarget && compatibleRecipe ? settings : applyGenerationRecipe(settings, target)};
    });
  }

  async function matchAndTranslate() {
    if (!draft.positive_prompt.trim()) return;
    setPreviewBusy(true);
    setError(null);
    setNotice(null);
    try {
      const payload = await apiRequest<DirectPromptPreview>("/api/v3/direct-prompt/preview", {
        method: "POST",
        body: JSON.stringify({
          positive_prompt: draft.positive_prompt,
          negative_prompt: draft.negative_prompt,
        }),
      });
      setPreview(payload);
    } catch (caught) {
      setError(caught as ApiClientError);
      setPreview(null);
    } finally {
      setPreviewBusy(false);
    }
  }

  function sendToWorkbench() {
    if (!preview) return;
    const payload = {
      positive_text: preview.chinese_positive,
      excluded_text: preview.chinese_negative,
      english_positive: draft.positive_prompt,
      english_negative: draft.negative_prompt,
    };
    storeDirectImport(payload);
    navigate("/workbench?from=direct");
  }

  async function submitDirect() {
    if (!draft.positive_prompt.trim()) return;
    const target = compatibleTargets.find((item) => targetKey(item) === selectedTarget) || compatibleTargets[0];
    if (!target) {
      setNotice("当前模型没有可用的远程工作流。");
      return;
    }
    if (!idempotencyKey.current) {
      idempotencyKey.current = `direct-${crypto.randomUUID()}`;
    }
    setGenerationBusy(true);
    setNotice(null);
    setError(null);
    try {
      if (target.auth_type === "private_key" && privateKeyPassphrase) {
        await apiRequest<{configured: boolean}>("/api/v3/generation-credentials/private-key-passphrase", {
          method: "POST",
          body: JSON.stringify({remote_profile_id: target.remote_profile_id, passphrase: privateKeyPassphrase}),
        });
        setPrivateKeyPassphrase("");
        setGenerationTargets((items) => items.map((item) => item.remote_profile_id === target.remote_profile_id ? {...item, private_key_passphrase_configured: true} : item));
      }
      await apiRequest<GenerationRunRecord>("/api/v3/direct-prompt/runs", {
        method: "POST",
        headers: {"Idempotency-Key": idempotencyKey.current},
        body: JSON.stringify({
          positive_prompt: draft.positive_prompt,
          negative_prompt: draft.negative_prompt,
          model_profile: draft.model_profile,
          project_name: draft.project_name.trim() || "英文提示词直出",
          settings: resolvedGenerationSettings(draft.generation_settings),
          remote_profile_id: target.remote_profile_id,
          workflow_profile_id: target.workflow_profile_id,
        }),
      });
      idempotencyKey.current = null;
      setNotice("已按原文提交远程队列，没有经过工作台编译。进度可在“生成”页查看。");
    } catch (caught) {
      setNotice((caught as ApiClientError).message);
    } finally {
      setGenerationBusy(false);
    }
  }

  function selectRemoteConnection(remoteId: string) {
    const workflow = compatibleTargets.find((item) => item.remote_profile_id === remoteId);
    if (!workflow) return;
    chooseGenerationTarget(workflow);
  }

  const settings = draft.generation_settings;
  const activeRecipe = findGenerationRecipe(activeTarget, settings.preset_id);
  const capabilities = activeTarget?.parameter_capabilities;

  function changeModel(modelProfile: string) {
    const target = generationTargets.find((item) => item.compatible_model_profiles.includes(modelProfile) && item.remote_profile_id === selectedRemoteId)
      || generationTargets.find((item) => item.compatible_model_profiles.includes(modelProfile));
    if (target) {
      setSelectedTarget(targetKey(target));
      editDraft({model_profile: modelProfile, generation_settings: applyGenerationRecipe(settings, target)});
    } else editDraft({model_profile: modelProfile});
  }

  return (
    <section className="page direct-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">ENGLISH PASSTHROUGH</span>
          <h1>英文提示词直出</h1>
          <p>把已写好的英文提示词原样送给 ANIMA。这里不会拆词、不会补标签、不会改姿势。回译只用来对照中文，方便再拿去工作台改。</p>
        </div>
        <div className="header-stat">
          <strong>{preview ? preview.matched_count : "—"}</strong>
          <span>matched tags</span>
        </div>
      </header>

      <form className="workbench-composer" onSubmit={(event) => { event.preventDefault(); void matchAndTranslate(); }}>
        <div className="composer-main">
          <label htmlFor="direct-project">任务名称</label>
          <input id="direct-project" value={draft.project_name} onChange={(event) => editDraft({project_name: event.target.value})} maxLength={200} />
          <label htmlFor="direct-positive">正向提示词（英文，原样发送）</label>
          <textarea id="direct-positive" value={draft.positive_prompt} onChange={(event) => editDraft({positive_prompt: event.target.value})} placeholder="masterpiece, best quality, 1girl, solo, full body…" rows={8} />
          <label htmlFor="direct-negative">反向提示词（可选）</label>
          <textarea id="direct-negative" value={draft.negative_prompt} onChange={(event) => editDraft({negative_prompt: event.target.value})} placeholder="worst quality, low quality…" rows={4} />
        </div>
        <div className="composer-side">
          <p className="natural-mode-hint">工作台编译会把 `black hair ribbons` 拆成黑发，把 `lineart` 当成线稿。直出页按逗号保留整词，生图时不改原文。</p>
          <label htmlFor="direct-model">模型配置</label>
          <select id="direct-model" value={draft.model_profile} onChange={(event) => changeModel(event.target.value)}>
            {profiles.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
          <div className="generation-spec">
            <strong>生成规格</strong>
            <label htmlFor="direct-aspect">画幅</label>
            <select id="direct-aspect" value={settings.aspect} onChange={(event) => editDraft({generation_settings: applyAspect(settings, event.target.value as WorkbenchGenerationSettings["aspect"])})}>
              <option value="portrait">{aspectLabels.portrait}</option>
              <option value="landscape">{aspectLabels.landscape}</option>
              <option value="square">{aspectLabels.square}</option>
              <option value="custom">{aspectLabels.custom}</option>
              <option value="model_default">{aspectLabels.model_default}</option>
            </select>
            <label htmlFor="direct-preset">生成配方</label>
            <select id="direct-preset" value={activeRecipe?.id || "custom"} onChange={(event) => { if (activeTarget) editDraft({generation_settings: applyGenerationRecipe(settings, activeTarget, event.target.value)}); }} disabled={!activeTarget?.generation_recipes?.length}>
              {settings.preset_id === "custom" && <option value="custom">自定义参数</option>}
              {(activeTarget?.generation_recipes || []).map((recipe) => <option key={recipe.id} value={recipe.id}>{recipe.display_name}{recipe.evidence === "experimental" ? " · 实验" : ""}</option>)}
            </select>
            <small>{activeRecipe?.notes || "选择工作流后加载对应的 V3 生成配方。"}</small>
            {activeTarget?.workflow_notes && <small>{activeTarget.workflow_notes}</small>}
            <details className="generation-advanced" open>
              <summary>高级参数</summary>
              <div className="generation-advanced-grid">
                <label htmlFor="direct-width">宽度</label>
                <input id="direct-width" type="number" min="64" max="8192" step="64" value={settings.width} disabled={settings.aspect === "model_default"} onChange={(event) => editDraft({generation_settings: {...settings, aspect: "custom", width: Math.max(64, Number(event.target.value) || 64)}})} />
                <label htmlFor="direct-height">高度</label>
                <input id="direct-height" type="number" min="64" max="8192" step="64" value={settings.height} disabled={settings.aspect === "model_default"} onChange={(event) => editDraft({generation_settings: {...settings, aspect: "custom", height: Math.max(64, Number(event.target.value) || 64)}})} />
                <label htmlFor="direct-steps">采样步数 Steps</label>
                <input id="direct-steps" type="number" min={capabilities?.steps.minimum ?? 1} max={capabilities?.steps.maximum ?? 200} value={settings.steps} disabled={capabilities?.steps.mode === "fixed"} title={capabilities?.steps.reason} onChange={(event) => editDraft({generation_settings: markGenerationCustom(settings, {steps: Math.max(1, Number(event.target.value) || 1)})})} />
                <label htmlFor="direct-cfg">CFG</label>
                <input id="direct-cfg" type="number" min={capabilities?.cfg.minimum ?? 0} max={capabilities?.cfg.maximum ?? 30} step="0.1" value={settings.cfg} disabled={capabilities?.cfg.mode === "fixed"} title={capabilities?.cfg.reason} onChange={(event) => editDraft({generation_settings: markGenerationCustom(settings, {cfg: Math.max(0, Number(event.target.value) || 0)})})} />
                <label htmlFor="direct-sampler">采样器 Sampler</label>
                <select id="direct-sampler" value={settings.sampler} disabled={capabilities?.sampler.mode === "fixed"} title={capabilities?.sampler.reason} onChange={(event) => editDraft({generation_settings: markGenerationCustom(settings, {sampler: event.target.value})})}>{Array.from(new Set([settings.sampler, ...(capabilities?.sampler.options || [])])).map((option) => <option key={option} value={option}>{option}</option>)}</select>
                <label htmlFor="direct-scheduler">调度器 Scheduler</label>
                <select id="direct-scheduler" value={settings.scheduler} disabled={capabilities?.scheduler.mode === "fixed"} title={capabilities?.scheduler.reason} onChange={(event) => editDraft({generation_settings: markGenerationCustom(settings, {scheduler: event.target.value})})}>{Array.from(new Set([settings.scheduler, ...(capabilities?.scheduler.options || [])])).map((option) => <option key={option} value={option}>{option}</option>)}</select>
              </div>
            </details>
            <label htmlFor="direct-seed">Seed</label>
            <input id="direct-seed" type="number" min="-1" max="2147483647" value={settings.seed} onChange={(event) => editDraft({generation_settings: {...settings, seed: Number(event.target.value)}})} />
            <label htmlFor="direct-batch">批量</label>
            <input id="direct-batch" type="number" min="1" max="8" value={settings.batch_size} onChange={(event) => editDraft({generation_settings: {...settings, batch_size: Math.max(1, Number(event.target.value) || 1)}})} />
          </div>
          {remoteEnabled && <>
            <label htmlFor="direct-remote">云主机连接</label>
            <select id="direct-remote" aria-label="云主机连接" value={selectedRemoteId || ""} onChange={(event) => selectRemoteConnection(event.target.value)} disabled={!remoteConnections.length}>
              {remoteConnections.length ? remoteConnections.map((target) => <option key={target.remote_profile_id} value={target.remote_profile_id}>{target.remote_display_name}{target.host_fingerprint_ready ? "" : " · 待确认指纹"}</option>) : <option value="">无可用连接</option>}
            </select>
            <label htmlFor="direct-workflow">工作流</label>
            <select id="direct-workflow" aria-label="远程工作流" value={selectedWorkflowId || ""} onChange={(event) => { const target = connectionWorkflows.find((item) => item.workflow_profile_id === event.target.value); if (target) chooseGenerationTarget(target); }} disabled={!connectionWorkflows.length}>
              {connectionWorkflows.length ? connectionWorkflows.map((target) => <option key={target.workflow_profile_id} value={target.workflow_profile_id}>{target.workflow_display_name}</option>) : <option value="">当前模型无兼容工作流</option>}
            </select>
            {activeTarget?.auth_type === "private_key" && <label className="passphrase-input"><span>私钥口令（可选）</span><input type="password" autoComplete="current-password" value={privateKeyPassphrase} onChange={(event) => setPrivateKeyPassphrase(event.target.value)} placeholder={activeTarget.private_key_passphrase_configured ? "已在本次运行中设置" : "私钥未加密可留空"} /></label>}
          </>}
          <button className="button generate-button" type="submit" disabled={!draft.positive_prompt.trim() || previewBusy}>{previewBusy ? "正在匹配中英标签…" : "匹配并回译中文"}</button>
          <button className="button" type="button" disabled={!draft.positive_prompt.trim() || generationBusy || !remoteEnabled} onClick={() => void submitDirect()}>{generationBusy ? "正在提交…" : "按原文生图"}</button>
        </div>
      </form>

      {error && <ErrorState message={error.message} requestId={error.requestId} />}
      {notice && <div className="workspace-notice" role="status">{notice}</div>}
      {!remoteEnabled && <div className="workspace-notice" role="status">回译和工作台导入可用。要按原文生图，启动时带上已有云主机配置。</div>}

      {preview && (
        <section className="direct-preview" aria-label="中英标签对照">
          <header>
            <div>
              <strong>按逗号整词匹配</strong>
              <span>{preview.matched_count} 个已对照中文标签 · {preview.unmatched_count} 个未入词典{preview.translation_engine ? ` · ${preview.translation_engine}` : ""}</span>
            </div>
            <button type="button" className="button" onClick={sendToWorkbench}>送到工作台修改</button>
          </header>
          <p className="direct-chinese">{preview.chinese_positive || "（正向为空）"}</p>
          {preview.chinese_negative && <p className="direct-chinese is-negative">排除：{preview.chinese_negative}</p>}
          <TokenTable title="正向" tokens={preview.positive_tokens} />
          {preview.negative_tokens.length > 0 && <TokenTable title="反向" tokens={preview.negative_tokens} />}
        </section>
      )}
    </section>
  );
}

function TokenTable({title, tokens}: {title: string; tokens: DirectPromptPreview["positive_tokens"]}) {
  return (
    <div className="direct-token-table">
      <strong>{title}</strong>
      <ul>
        {tokens.map((token, index) => (
          <li key={`${title}-${index}-${token.original}`}>
            <code>{token.original}</code>
            <span>{token.zh}</span>
            <small>{token.matched ? token.canonical_tag?.replaceAll("_", " ") : "未匹配，保留原词"}</small>
          </li>
        ))}
      </ul>
    </div>
  );
}

function loadDraft(): DirectDraft {
  if (import.meta.env.MODE === "test") return emptyDraft;
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) return emptyDraft;
    const parsed = JSON.parse(raw) as Partial<DirectDraft>;
    return {
      ...emptyDraft,
      ...parsed,
      generation_settings: {...defaultGenerationSettings(), ...(parsed.generation_settings || {})},
    };
  } catch {
    return emptyDraft;
  }
}

function targetKey(target: GenerationTarget): string {
  return `${target.remote_profile_id}::${target.workflow_profile_id}`;
}
