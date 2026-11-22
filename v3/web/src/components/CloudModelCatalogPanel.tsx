import {useEffect, useRef, useState} from "react";
import {apiRequest} from "../lib/api";
import {cloudMappingForCurrentWorkflow, cloudSuggestionPreview, type CloudCatalogResponse, type ApplyCloudMappingRequest} from "../lib/cloudModelCatalog";
import type {CreationConfiguration, WorkflowParameterSchema} from "../lib/types";
export interface CloudModelCatalogPanelProps {
  environmentId?: string | null; environmentName?: string;
  configuration: CreationConfiguration; schema: WorkflowParameterSchema; disabled?: boolean;
  onChange: (configuration: CreationConfiguration) => void; onMappingApplied?: () => void;
  onEnvironmentRefreshed?: () => void;
}
const statusLabels={unchecked:"尚未检查",ready:"目录已更新",stale:"目录已过期，请刷新",unavailable:"云端目录暂不可用",unsupported:"云端目录格式尚未适配"};
export function CloudModelCatalogPanel({environmentId,environmentName,configuration,schema,disabled,onChange,onMappingApplied,onEnvironmentRefreshed}:CloudModelCatalogPanelProps) {
  const contextKey=JSON.stringify([environmentId,configuration.modelProfile,configuration.workflow.id,configuration.workflow.revision]);
  const latestContext=useRef(contextKey);latestContext.current=contextKey;
  const sequence=useRef(0);
  const request=useRef<AbortController|null>(null);
  const [state,setState]=useState<{key:string;catalog?:CloudCatalogResponse;busy?:string;error?:string;notice?:string}>({key:contextKey});
  const visible=state.key===contextKey?state:{key:contextKey};
  const catalog=visible.catalog;
  const item=catalog?.items.find(model=>model.id===configuration.modelProfile);
  const supported=Boolean(item?.supported);
  const preview=item&&supported?cloudSuggestionPreview(item.suggested_defaults,configuration,schema):null;
  const mapping=catalog&&item?cloudMappingForCurrentWorkflow(catalog,item,configuration):undefined;
  const actionable=catalog?.status==="ready"&&supported&&item?.ready;
  const blocked=disabled||Boolean(visible.busy);
  const base=environmentId?`/api/v3/settings/remote-profiles/${encodeURIComponent(environmentId)}/model-catalog`:"";

  async function load(refresh=false) {
    if(!environmentId)return;
    request.current?.abort();const controller=new AbortController();request.current=controller;
    const ticket=++sequence.current;
    setState({key:contextKey,busy:"load"});
    try {
      const result=await apiRequest<CloudCatalogResponse>(base+(refresh?"/refresh":""),{method:refresh?"POST":"GET",body:refresh?"{}":undefined,signal:controller.signal});
      if(controller.signal.aborted||ticket!==sequence.current||latestContext.current!==contextKey)return;
      if(result.remote_profile_id!==environmentId)throw new Error("catalog_identity_mismatch");
      setState({key:contextKey,catalog:result});
      if(refresh)onEnvironmentRefreshed?.();
    } catch {
      if(!controller.signal.aborted&&ticket===sequence.current&&latestContext.current===contextKey)
        setState({key:contextKey,error:"无法读取云端模型目录，请稍后刷新重试。"});
    }
  }
  useEffect(()=>{
    if(environmentId)void load();else setState({key:contextKey});
    return ()=>{request.current?.abort();sequence.current++;};
  },[contextKey]);

  async function applyMapping() {
    if(blocked||!mapping||!catalog||!item)return;
    const controller=new AbortController();request.current=controller;const ticket=++sequence.current;
    setState({key:contextKey,catalog,busy:"mapping"});
    const payload:ApplyCloudMappingRequest={model_id:item.id,workflow_profile_id:configuration.workflow.id,session_id:catalog.session_id,environment_epoch:catalog.environment_epoch};
    try {
      await apiRequest(base+"/apply-mapping",{method:"POST",body:JSON.stringify(payload),signal:controller.signal});
      if(controller.signal.aborted||ticket!==sequence.current||latestContext.current!==contextKey)return;
      setState({key:contextKey,catalog,notice:"当前工作流文件映射已保存。"});onMappingApplied?.();
    } catch {
      if(!controller.signal.aborted&&ticket===sequence.current&&latestContext.current===contextKey)
        setState({key:contextKey,error:"文件映射未保存，环境或工作流可能已变化，请刷新目录后重试。"});
    }
  }
  return <section className="cloud-model-catalog" aria-label="云端模型目录">
    <h3>云端模型目录</h3>
    {!environmentId?<p>请先选择固定执行环境，再查看该环境的模型目录。</p>:<>
      <p>当前环境：{environmentName||"已选环境"}</p>
      <button type="button" disabled={blocked} onClick={()=>void load(true)}>刷新云端目录</button>
      {visible.busy==="load"&&<p role="status">正在读取云端模型目录…</p>}
      {visible.error&&<p role="alert">{visible.error}</p>}
      {visible.notice&&<p role="status">{visible.notice}</p>}
      {catalog&&<>
        <p>{statusLabels[catalog.status]}{catalog.checked_at!=null&&<> · 检查于 {new Date(catalog.checked_at*1000).toLocaleString()}</>}</p>
        {catalog.message&&<p>{catalog.message}</p>}
        {!item?<p>{catalog.status==="ready"?"当前模型未列入此云端目录，尚未适配。":"当前目录无法确认此模型的文件状态。"}</p>:!supported?<p>当前模型尚未适配云端目录</p>:<>
          <p>当前模型：{item.display_name} · <strong>{catalog.status==="ready"?(item.ready?"文件齐全":"缺少文件"):(item.ready?"上次检查文件齐全，当前未确认":"上次检查缺少文件，当前未确认")}</strong>{item.selected_for_startup&&" · 云端启动所选模型"}</p>
          <p className="conversation-muted">文件齐全仅表示报告中的文件存在；模型是否已加载、能否出图仍需实际验证。</p>
          <ul aria-label="当前模型文件">{item.assets.map(asset=><li key={`${asset.category}/${asset.filename}`}>{asset.filename} · {catalog.status==="ready"?(asset.ready?"可用":"缺失或未识别"):(asset.ready?"上次检查可用，当前未确认":"上次检查缺失或未识别，当前未确认")}</li>)}</ul>
          <button type="button" disabled={blocked||!mapping} onClick={()=>void applyMapping()}>应用当前工作流文件映射</button>
          {!mapping&&<small>当前目录与工作流尚无可应用的完整文件映射。</small>}
          {preview&&<div>
            <h4>云端建议参数预览</h4>
            <ul aria-label="建议参数改动">{preview.changes.map(change=><li key={change.key}>{change.label}：{String(change.from)} → {String(change.to)}</li>)}</ul>
            {preview.errors.map(error=><p key={error}>{error}</p>)}
            {!preview.changes.length&&!preview.errors.length&&<p>当前参数与云端建议一致，或暂无建议。</p>}
            <button type="button" disabled={blocked||!actionable||!preview.changes.length||Boolean(preview.errors.length)} onClick={()=>onChange(preview.configuration)}>应用云端建议参数</button>
            <small>仅更新 Steps、CFG、Sampler、Scheduler；应用后请保存创作设置。</small>
          </div>}
        </>}
        {catalog.items.some(model=>!model.supported)&&<ul aria-label="尚未适配的云端模型">{catalog.items.filter(model=>!model.supported).map(model=><li key={model.id}>{model.display_name} · 尚未适配</li>)}</ul>}
      </>}
    </>}
  </section>;
}
