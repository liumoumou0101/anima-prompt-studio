import {useEffect, useRef, useState} from "react";
import {apiRequest} from "../lib/api";
import type {RequirementsEdit} from "../lib/conversation";
import {applySceneChoices, parseSceneAdvice, sceneChoice, sceneFields, sceneLabels, sceneLocked, sceneOptions, sceneSourceLabels, undoSceneChoices, type SceneAdvice, type SceneChoice, type SceneChoices, type SceneField} from "../lib/sceneDesign";
import "./sceneDesign.css";

export interface SceneDesignControlsProps {
  requirements: RequirementsEdit;
  onChange: (requirements: RequirementsEdit) => void;
  workspaceId?: string;
  workspaceRevision?: number;
  delta?: string;
  positive?: string;
  negative?: string;
  disabled?: boolean;
  adviceDisabledReason?: string;
  llmContextKey?: string;
  onBusyChange?: (busy: boolean) => void;
}

export function SceneDesignControls({requirements, onChange, workspaceId, workspaceRevision, delta = "", positive = "", negative = "", disabled = false,
  adviceDisabledReason = "", llmContextKey = "", onBusyChange}: SceneDesignControlsProps) {
  const [custom, setCustom] = useState<Partial<Record<SceneField, string>>>({});
  const [target, setTarget] = useState(sceneChoice(requirements, "gaze")?.target || "");
  const [undo, setUndo] = useState<{before: RequirementsEdit; after: RequirementsEdit} | null>(null);
  const [pendingShot, setPendingShot] = useState<SceneChoice | null>(null);
  const [advice, setAdvice] = useState<SceneAdvice | null>(null);
  const [requestPending, setRequestPending] = useState(false);
  const requestLock = useRef(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const epoch = useRef(0);
  const contextKey = JSON.stringify({requirements, delta, positive, negative, workspaceId, workspaceRevision, custom, target, llmContextKey});
  const requirementsKey = JSON.stringify(requirements);
  const savedTarget = sceneChoice(requirements, "gaze")?.target || "";
  useEffect(() => {setTarget(savedTarget);}, [savedTarget]);
  useEffect(() => {onBusyChange?.(requestPending); return () => onBusyChange?.(false);}, [requestPending, onBusyChange]);
  useEffect(() => {
    epoch.current += 1; setAdvice(null);
  }, [contextKey]);
  useEffect(() => {setPendingShot(null);}, [requirementsKey]);
  useEffect(() => {
    epoch.current += 1;
    setAdvice(null); setError(""); setNotice(""); setUndo(null); setPendingShot(null); setCustom({});
    setTarget(sceneChoice(requirements, "gaze")?.target || "");
    return () => {epoch.current += 1;};
    // A workspace switch must discard in-flight suggestions, not draft contents.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);
  const commit = (next: RequirementsEdit, message: string) => {
    epoch.current += 1; setAdvice(null); setPendingShot(null);
    setUndo({before: structuredClone(requirements), after: structuredClone(next)});
    onChange(next); setNotice(message); setError("");
  };
  function choose(field: SceneField, value: string) {
    if (disabled) return;
    setPendingShot(null);
    if (field === "gaze" && value && !target.trim()) {setError("先填写视线作用的人物，例如“左侧女孩”。"); return;}
    const choice: SceneChoice | null = value ? {value: value.trim(), source: "user", ...(field === "gaze" ? {target: target.trim()} : {})} : null;
    if (field === "shot" && choice && requirements.layers.composition.shot && requirements.layers.composition.shot !== choice.value) {
      setPendingShot(choice); return;
    }
    commit(applySceneChoices(requirements, {[field]: choice}), choice ? `已指定${sceneLabels[field]}，更新提示词后生效。` : `已清除${sceneLabels[field]}，手写要求已保留。`);
  }
  async function suggest() {
    if (disabled || adviceDisabledReason || requestLock.current || !workspaceId || !workspaceRevision || (requirements.layers.composition.locked && requirements.layers.lighting.locked)) return;
    requestLock.current = true; setRequestPending(true);
    const requestEpoch = ++epoch.current;
    setError(""); setAdvice(null);
    try {
      const result = parseSceneAdvice(await apiRequest<unknown>("/api/v3/workbench/scene-advice", {method: "POST", body: JSON.stringify({
        workspace_id: workspaceId, revision: workspaceRevision, requirements, delta, positive, negative,
      })}));
      if (requestEpoch === epoch.current) setAdvice(result);
    } catch (err) {if (requestEpoch === epoch.current) setError(err instanceof Error ? err.message : "暂时未能获取建议，请重试。");}
    finally {requestLock.current = false; setRequestPending(false);}
  }
  function adopt(changes: SceneChoices) {
    if (disabled) return;
    if (Object.keys(changes).some(field => sceneLocked(requirements, field as SceneField))) {setError("建议涉及锁定层，请先解除锁定后再采用。"); return;}
    if (changes.shot && requirements.layers.composition.shot && requirements.layers.composition.shot !== changes.shot.value) {setError("建议景别与原景别不同，请先在景别栏明确修改。"); return;}
    const additions: SceneChoices = {};
    for (const field of sceneFields) {
      const choice = changes[field];
      if (!choice) continue;
      const selected = sceneChoice(requirements, field);
      if (selected) {
        if (selected.value !== choice.value || (selected.target || "") !== (choice.target || "")) {
          setError(`建议与已指定的${sceneLabels[field]}不同，请先手动调整或清除该项。`); return;
        }
        // Repeating a selected value does not turn the user's choice into an
        // assistant suggestion or erase the evidence of a confirmed extraction.
      } else additions[field] = choice;
    }
    if (!Object.keys(additions).length) {setAdvice(null); setNotice("这些选项已经指定，当前来源已保留。"); return;}
    commit(applySceneChoices(requirements, additions), "已采用到草稿，更新提示词后生效。");
  }
  return <section className="scene-design" aria-label="画面设计辅助">
    <div className="scene-design__heading"><div><h3>画面设计</h3><p>按需指定，或让助手提供几个方向。</p></div>
      <button type="button" onClick={() => void suggest()} disabled={disabled || Boolean(adviceDisabledReason) || requestPending || !workspaceId || !workspaceRevision || (requirements.layers.composition.locked && requirements.layers.lighting.locked)}>{requestPending ? "正在获取建议…" : "给我建议"}</button></div>
    {adviceDisabledReason && <p className="scene-design__note">{adviceDisabledReason}</p>}
    <div className="scene-design__fields">
      {sceneFields.map(field => {
        const selected = sceneChoice(requirements, field);
        const customMode = custom[field] !== undefined || Boolean(selected && !sceneOptions[field].includes(selected.value));
        return <div className="scene-design__field" key={field}>
          <label htmlFor={`scene-${field}`}>{sceneLabels[field]}</label>
          <select id={`scene-${field}`} value={customMode ? "__custom" : selected?.value || ""} disabled={disabled} onChange={event => {
            if (event.target.value === "__custom") {setPendingShot(null); setCustom({...custom, [field]: selected?.value || ""});}
            else {setCustom(previous => {const next = {...previous}; delete next[field]; return next;}); choose(field, event.target.value);}
          }}><option value="">不指定</option>{sceneOptions[field].map(value => <option key={value}>{value}</option>)}<option value="__custom">自定义…</option></select>
          {field === "gaze" && <label className="scene-design__target">作用人物<input aria-label="视线作用人物" value={target} maxLength={200} disabled={disabled} placeholder="例如：左侧女孩" onChange={event => setTarget(event.target.value)} onBlur={() => {
            if (selected && !target.trim()) {setError("已有视线需要明确作用人物；如不再需要，请清除人物视线。"); setTarget(selected.target || ""); return;}
            if (selected && target.trim() && target.trim() !== selected.target) choose("gaze", selected.value);
          }} /></label>}
          {customMode && <div className="scene-design__custom"><input aria-label={`自定义${sceneLabels[field]}`} value={custom[field] ?? selected?.value ?? ""} maxLength={400} disabled={disabled} onChange={event => {setPendingShot(null); setCustom({...custom, [field]: event.target.value});}} />
            <button type="button" disabled={disabled || !(custom[field] ?? selected?.value ?? "").trim()} onClick={() => choose(field, custom[field] ?? selected?.value ?? "")}>确定</button></div>}
          {selected && <div className="scene-design__selection"><span>{sceneSourceLabels[selected.source]}{selected.target ? ` · ${selected.target}` : ""}</span><button type="button" aria-label={`清除${sceneLabels[field]}`} disabled={disabled} onClick={() => {setCustom(previous => {const next = {...previous}; delete next[field]; return next;}); choose(field, "");}}>清除</button></div>}
          {selected?.evidence && <small>原句：{selected.evidence}</small>}
        </div>;
      })}
    </div>
    {(requirements.layers.composition.locked || requirements.layers.lighting.locked) && <p className="scene-design__note">{requirements.layers.composition.locked ? "构图" : ""}{requirements.layers.composition.locked && requirements.layers.lighting.locked ? "、" : ""}{requirements.layers.lighting.locked ? "光影" : ""}已锁定自动改写；你仍可手动调整。</p>}
    {(requirements.layers.composition.text || requirements.layers.composition.shot || requirements.layers.lighting.text) && <details className="scene-design__context"><summary>核对已有的构图与光影要求</summary>
      <p>{[requirements.layers.composition.shot, requirements.layers.composition.text, requirements.layers.lighting.text].filter(Boolean).join("；")}</p><small>快捷选择不会删除这些文字。如有矛盾，请先在画面要求中修改。</small></details>}
    {pendingShot && <div className="scene-design__review" role="alert"><p>原景别是“{requirements.layers.composition.shot}”，这次选择“{pendingShot.value}”。</p>
      <button type="button" disabled={disabled} onClick={() => {const next = applySceneChoices(requirements, {shot: pendingShot}); next.layers.composition.shot = ""; commit(next, "已替换原景别，其他手写要求已保留。"); setPendingShot(null);}}>替换原景别</button><button type="button" onClick={() => setPendingShot(null)}>取消</button></div>}
    {error && <p role="alert" className="scene-design__error">{error}</p>}
    <div className="scene-design__status"><span role="status">{notice || "选择先保存在草稿；点击“更新提示词”后由助手结合全文表达。"}</span>{undo && <button type="button" disabled={disabled} onClick={() => {
      const next = undoSceneChoices(requirements, undo.before, undo.after);
      onChange(next); setUndo(null); setCustom({}); setError(""); setNotice("已撤销这次画面调整。");
    }}>撤销画面调整</button>}</div>
    {advice && <div className="scene-design__advice"><div className="scene-design__heading"><h4>待你选择</h4><button type="button" onClick={() => setAdvice(null)}>收起建议</button></div>
      {!advice.extracted.length && !advice.suggestions.length && <p>暂时没有需要补充的方向，可以继续完善自己的描述。</p>}
      {advice.extracted.map((item, index) => <div className="scene-design__suggestion" key={`extracted-${index}`}><strong>原文提取 · 待确认：{sceneLabels[item.field]} · {item.value}</strong><p>“{item.evidence}”{item.target ? ` · ${item.target}` : ""}</p><button type="button" disabled={disabled || sceneLocked(requirements, item.field)} onClick={() => adopt({[item.field]: {value: item.value, target: item.target, evidence: item.evidence, source: "extracted"}})}>确认这项提取</button></div>)}
      {advice.suggestions.map((item, index) => <div className="scene-design__suggestion" key={index}><strong>助手建议 · {item.title}</strong><p>{item.reason}</p><ul>{Object.entries(item.choices).map(([field, choice]) => <li key={field}>{sceneLabels[field as SceneField]}：{choice.value}{choice.target ? `（${choice.target}）` : ""}</li>)}</ul><button type="button" disabled={disabled || Object.keys(item.choices).some(field => sceneLocked(requirements, field as SceneField))} onClick={() => adopt(Object.fromEntries(Object.entries(item.choices).map(([field, choice]) => [field, {...choice, source: "suggestion"}])))}>采用“{item.title}”</button></div>)}
    </div>}
  </section>;
}
