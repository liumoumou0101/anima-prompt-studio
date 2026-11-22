import {useEffect, useId, useRef, useState, type ReactNode} from "react";
import type {CreationConfiguration, GenerationRecipe, WorkflowParameterField, WorkflowParameterSchema} from "../lib/types";
import {applyRecipe, recipeDifferences, resetParameter, resolveConfiguration, setParameter} from "../lib/creationConfiguration";
import {validateParameter} from "../lib/workflowParameterSchema";
import "./generationSettingsPanel.css";

export interface GenerationSettingsPanelProps {
  configuration: CreationConfiguration; schema: WorkflowParameterSchema; validation?: Record<string,string>;
  recipes?: GenerationRecipe[]; defaultRecipeId?: string; loraContent?: ReactNode; disabled?: boolean;
  onChange: (configuration:CreationConfiguration, action:{kind:"field"|"recipe"|"reset";key?:string;label:string}) => void;
  onPendingChange?: (pending:boolean) => void;
  validateApply?: (values:Record<string,number|string>) => string | undefined;
  contextId?: string;
}

type ParameterState = Pick<CreationConfiguration,"baseRecipeId"|"recipeValues"|"parameterOverrides"|"seedMode">;
type ParameterAction = Parameters<GenerationSettingsPanelProps["onChange"]>[1];
function parameters(configuration:CreationConfiguration):ParameterState {
  const {baseRecipeId,recipeValues,parameterOverrides,seedMode}=configuration;
  return {baseRecipeId,recipeValues,parameterOverrides,seedMode};
}
function parameterKey(configuration:ParameterState) {
  return JSON.stringify([configuration.baseRecipeId,configuration.seedMode,
    Object.entries(configuration.recipeValues).sort(([a],[b])=>a.localeCompare(b)),
    Object.entries(configuration.parameterOverrides).sort(([a],[b])=>a.localeCompare(b))]);
}

function ParameterInput({field,value,onChange,error,disabled}:{field:WorkflowParameterField;value:number|string;onChange:(value:number|string)=>void;error?:string;disabled?:boolean}) {
  const id = useId();
  const [text,setText] = useState(String(value));
  const [localError,setLocalError] = useState<string>();
  useEffect(()=>{setText(String(value));setLocalError(undefined);},[value]);
  const issue = localError || error;
  function edit(next:string) {
    setText(next);
    const converted = field.type === "number" || field.type === "integer" ? next.trim() === "" || !Number.isFinite(Number(next)) ? next : Number(next) : next;
    setLocalError(validateParameter(field,converted));
    // Keep incomplete input in the local draft so confirmation remains blocked.
    onChange(converted);
  }
  return <label htmlFor={id}>{field.label}
    {field.enum?.length ? <select id={id} aria-label={field.label} value={text} disabled={disabled} aria-invalid={!!issue} onChange={event=>edit(event.target.value)}>
      {!field.enum.includes(text) && <option value={text}>{text || "请选择"}</option>}
      {field.enum.map(option=><option key={option}>{option}</option>)}
    </select> : <input id={id} aria-label={field.label} type="text" inputMode={field.type === "seed" || field.type === "integer" ? "numeric" : field.type === "number" ? "decimal" : "text"}
      value={text} disabled={disabled} aria-invalid={!!issue} aria-describedby={issue ? `${id}-error` : undefined} onChange={event=>edit(event.target.value)}
      onBlur={()=>{const next = field.type === "number" || field.type === "integer" ? text.trim() === "" ? "" : Number(text) : text;setLocalError(validateParameter(field,next));}} />}
    {issue && <small id={`${id}-error`} role="alert">{issue}</small>}
  </label>;
}

export function GenerationSettingsPanel({configuration,schema,validation,recipes=[],defaultRecipeId,onChange,onPendingChange,validateApply,contextId,loraContent,disabled}:GenerationSettingsPanelProps) {
  // Parameter drafts deliberately exclude resources: LoRA controls keep their own live state.
  const contextKey=JSON.stringify([contextId,configuration.modelProfile,configuration.workflow,schema]);
  const baselineKey=contextKey+parameterKey(configuration);
  const [staged,setStaged]=useState<{baseline:string;parameters:ParameterState;action:ParameterAction;fixedSeedSelected:boolean}|null>(null);
  const [confirmedKey,setConfirmedKey]=useState<string|null>(null);
  const [invalidated,setInvalidated]=useState(false);
  const draft=staged?.baseline===baselineKey?{...configuration,...staged.parameters}:configuration;
  const applied=resolveConfiguration(configuration,schema);
  const resolved = resolveConfiguration(draft,schema);
  const fixedSeedError=staged?.baseline===baselineKey&&staged.fixedSeedSelected&&draft.seedMode==="fixed"&&resolved.values.seed==="-1"
    ?"固定 Seed 需要填写非负整数；-1 表示随机。":undefined;
  const pending=parameterKey(draft)!==parameterKey(configuration)||Boolean(fixedSeedError);
  const pendingCallback=useRef(onPendingChange);
  useEffect(()=>{pendingCallback.current=onPendingChange;onPendingChange?.(pending);},[onPendingChange,pending]);
  useEffect(()=>()=>pendingCallback.current?.(false),[]);
  useEffect(()=>{if(staged&&staged.baseline!==baselineKey){setStaged(null);setInvalidated(true);}},[baselineKey,staged]);
  const appliedRecipe = recipes.find(item=>item.id===configuration.baseRecipeId);
  const recommendedRecipe = recipes.find(item=>item.id===draft.baseRecipeId) || recipes.find(item=>item.id===defaultRecipeId) || recipes[0];
  const [recipeId,setRecipeId] = useState(recommendedRecipe?.id || "");
  useEffect(()=>{setRecipeId(recommendedRecipe?.id || "");},[configuration.modelProfile,configuration.workflow.id,configuration.baseRecipeId,recommendedRecipe?.id]);
  const recipe = recipes.find(item=>item.id===recipeId);
  const proposal = recipe ? {id:recipe.id,parameters:{...recipe.parameters}} : undefined;
  const differences = proposal ? recipeDifferences(draft,proposal,schema) : [];
  const recipeChangesSource = proposal && (draft.baseRecipeId!==proposal.id || Object.entries(proposal.parameters).some(([key,value])=>
    Object.hasOwn(draft.parameterOverrides,key) || draft.recipeValues[key]!==value));
  const recommendedValues:Record<string,number|string> = {...Object.fromEntries(schema.fields.map(field=>[field.key,field.default])),...recommendedRecipe?.parameters};
  const staleBaseline = recommendedRecipe && (!appliedRecipe || Object.entries(recommendedRecipe.parameters).some(([key,value])=>String(configuration.recipeValues[key])!==String(value)));
  const errors:Record<string,string> = {...resolved.errors,...validation,...(fixedSeedError?{seed:fixedSeedError}:{})};
  const applyError=resolved.valid?validateApply?.(resolved.values):undefined;
  const canApply=pending&&!disabled&&!Object.values(errors).some(Boolean)&&!applyError;
  function stage(next:CreationConfiguration,action:ParameterAction) {
    if(disabled)return;
    // Loaded legacy fixed/-1 configurations remain usable; choosing fixed anew requires a real seed.
    const fixedSeedSelected=next.seedMode==="fixed"&&(draft.seedMode!=="fixed"||Boolean(staged?.baseline===baselineKey&&staged.fixedSeedSelected));
    setStaged({baseline:baselineKey,parameters:parameters(next),action,fixedSeedSelected});
    setConfirmedKey(null);
    setInvalidated(false);
  }
  function confirm() {
    if(!canApply)return;
    onChange({...configuration,...parameters(draft)},staged?.action||{kind:"field",label:"确认应用参数"});
    setConfirmedKey(contextKey+parameterKey(draft));
    setStaged(null);
    setInvalidated(false);
  }
  return <section className="generation-settings-panel" aria-label="生成参数">
    <div className="generation-parameter-commit" data-pending={pending}>
      <div aria-label="已应用参数" className="generation-parameter-applied"><strong>已应用</strong><span>{applied.values.width} × {applied.values.height} · Steps {applied.values.steps} · CFG {applied.values.cfg}</span></div>
      <p role="status">{pending?"有未应用修改，确认后用于下一次生成":confirmedKey===baselineKey?"参数已应用，将用于下一次生成":invalidated?"工作流或已应用参数已变化，请重新核对。":"修改参数后，请确认应用"}</p>
      <div className="generation-parameter-actions"><button type="button" disabled={!canApply} onClick={confirm}>确认应用参数</button>
        <button type="button" disabled={disabled||!pending} onClick={()=>{setStaged(null);setConfirmedKey(null);setInvalidated(false);}}>放弃修改</button></div>
      {applyError&&<p role="alert">{applyError}</p>}
    </div>
    {!schema.templateRevision && <p role="status">模板参数声明待检测；提交前会校验实际支持情况。</p>}
    {staleBaseline && <p role="status">当前条件保留了已有参数；下方推荐值来自当前工作流，可预览后应用推荐配方。</p>}
    {recipes.length>0 && <details className="generation-recipe"><summary>配方：{recipes.find(item=>item.id===configuration.baseRecipeId)?.display_name || "自定义基线"}</summary><fieldset disabled={disabled}><label>推荐配方<select value={recipeId} onChange={event=>setRecipeId(event.target.value)}><option value="">选择配方</option>{recipes.map(item=><option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label>
      {differences.length>0 && <ul aria-label="配方改变项">{differences.map(diff=><li key={diff.key}>{schema.fields.find(field=>field.key===diff.key)?.label || diff.key}：{String(diff.from)} → {diff.to}</li>)}</ul>}
      {proposal && <small>应用后采用所选配方，并清除其中参数的手动覆盖。</small>}
      <small>载入配方后，仍需点击“确认应用参数”。</small>
      <button type="button" disabled={!proposal || (!differences.length&&!recipeChangesSource)} onClick={()=>proposal && stage(applyRecipe(draft,proposal),{kind:"recipe",label:`应用配方：${recipe?.display_name}`})}>应用配方</button>
    </fieldset></details>}
    {([ ["common","常用"],["sampling","采样"],["workflow","工作流特有参数"] ] as const).map(([group,label])=>{
      const fields = schema.fields.filter(field=>field.group===group);
      if (!fields.length) return null;
      return <fieldset key={group} disabled={disabled}><legend>{label}</legend>
        {group==="common" && <><div className="generation-size-presets" aria-label="画幅快捷选择">{[["竖图",896,1152],["横图",1152,896],["方图",1024,1024]].map(([name,width,height])=><button key={name} type="button" onClick={()=>stage(setParameter(setParameter(draft,"width",Number(width)),"height",Number(height)),{kind:"field",key:"dimensions",label:`画幅：${name}`})}>{name}</button>)}</div>
          <label>种子模式<select value={draft.seedMode} onChange={event=>stage({...draft,seedMode:event.target.value as "random"|"fixed"},{kind:"field",key:"seedMode",label:"修改种子模式"})}><option value="random">随机</option><option value="fixed">固定 Seed</option></select></label></>}
        {fields.map(field=><div className="generation-parameter-field" key={field.key}>
          <ParameterInput field={field} value={resolved.values[field.key]} error={errors[field.key]} disabled={disabled || !!field.readOnlyReason}
            onChange={value=>stage(setParameter(draft,field.key,value),{kind:"field",key:field.key,label:`修改 ${field.label}`})}/>
          {field.readOnlyReason ? <small>模板固定：{field.readOnlyReason}</small> : <small>推荐值：{String(recommendedValues[field.key])}</small>}
          {field.key==="seed" && <small>-1 表示每次新生成随机；填写非负整数可复现。</small>}
          {Object.hasOwn(draft.parameterOverrides,field.key) && <><span>已修改</span><button type="button" disabled={disabled} onClick={()=>stage(resetParameter({...draft,recipeValues:{...draft.recipeValues,[field.key]:recommendedValues[field.key]}},field.key),{kind:"reset",key:field.key,label:`恢复 ${field.label}`})}>恢复 {field.label}</button></>}
          {errors[field.key] && <button type="button" disabled={disabled} onClick={()=>stage(setParameter(draft,field.key,field.default),{kind:"field",key:field.key,label:`采用 ${field.label} 模板建议`})}>使用模板建议：{String(field.default)}</button>}
        </div>)}
      </fieldset>;
    })}
    {schema.seedDerivation && <p>{schema.seedDerivation}</p>}
    {loraContent && <fieldset className="generation-lora-section" disabled={disabled}><legend>LoRA</legend>{loraContent}</fieldset>}
    {Object.entries(errors).filter(([key])=>!schema.fields.some(field=>field.key===key)).map(([key,error])=><p key={key} role="alert">{key}：{error}<button type="button" disabled={disabled} onClick={()=>stage(resetParameter(draft,key),{kind:"reset",key,label:`移除不兼容参数 ${key}`})}>移除此覆盖</button></p>)}
  </section>;
}
