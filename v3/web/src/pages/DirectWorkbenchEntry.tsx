import {useEffect,useState} from "react";
import {Link,Navigate,useLocation} from "react-router-dom";
import {DIRECT_MIGRATION_RECEIPT_KEY,LEGACY_DIRECT_DRAFT_KEY,legacyDirectImportId,readDirectImport,storeDirectImport} from "../lib/directPrompt";
import {defaultGenerationSettings} from "../lib/generationSettings";
import {MOSS_IMAGE_MODEL} from "../lib/modelProfiles";
import type {WorkbenchGenerationSettings} from "../lib/types";

type EntryState={to:string}|{error:string;pending?:boolean}|null;
const object=(value:unknown):value is Record<string,unknown>=>Boolean(value)&&typeof value==="object"&&!Array.isArray(value);

/** Compatibility entry only. All editable state and submissions belong to the workbench. */
export function DirectWorkbenchEntry(){
 const [state,setState]=useState<EntryState>(null);const location=useLocation();
 useEffect(()=>{
  let canceled=false;
  try{
   const parameters=new URLSearchParams(location.search);
   if(parameters.get("workspace")){setState({to:`/workbench?${parameters.toString()}`});return;}
   // No receipt or frozen request is deleted, rewritten, or resubmitted by this entry.
   for(const storage of [localStorage,sessionStorage])for(let index=0;index<storage.length;index++){
    const key=storage.key(index);if(key&&/^anima(?:-v3)?-direct-(?:prompt-)?(?:submission|pending)(?::|$)/.test(key)&&storage.getItem(key)!==null){setState({error:"旧版原文生成请求的结果尚未确认。恢复记录已保留，请先到任务记录核对，避免重复提交。",pending:true});return;}
   }
   if(readDirectImport()){setState({to:"/workbench?from=direct"});return;}
   const raw=localStorage.getItem(LEGACY_DIRECT_DRAFT_KEY);
   if(raw===null){setState({to:"/workbench?entry=raw"});return;}
   let legacy:unknown;try{legacy=JSON.parse(raw);}catch{throw new Error("旧版原文草稿已损坏；原始记录保留在本机，未覆盖。请先导出或核对旧草稿。");}
   if(!object(legacy)||typeof legacy.positive_prompt!=="string"||legacy.negative_prompt!==undefined&&typeof legacy.negative_prompt!=="string")throw new Error("旧版原文草稿结构已损坏；原始记录保留在本机，未覆盖。");
   if(legacy.pending_submission||legacy.pending){setState({error:"旧版原文生成请求的结果尚未确认。原始草稿与请求记录已保留，请先到任务记录核对。",pending:true});return;}
   const receiptRaw=localStorage.getItem(DIRECT_MIGRATION_RECEIPT_KEY);
   if(receiptRaw){let receipt:unknown;try{receipt=JSON.parse(receiptRaw);}catch{throw new Error("旧版原文草稿的迁移回执已损坏；原始草稿与回执均保留，请先核对会话记录。");}
    if(object(receipt)&&receipt.raw===raw){setState({to:typeof receipt.workspaceId==="string"?`/workbench?workspace=${encodeURIComponent(receipt.workspaceId)}`:"/workbench"});return;}
   }
   if(legacy.generation_settings!==undefined&&!object(legacy.generation_settings))throw new Error("旧版原文草稿的生成参数已损坏；原始记录保留在本机，未覆盖。");
   const settings=legacy.generation_settings ? {...(legacy.model_profile===MOSS_IMAGE_MODEL?{}:defaultGenerationSettings()),...legacy.generation_settings} as Partial<WorkbenchGenerationSettings> : undefined;
   if(settings&&!settings.execution_policy)settings.execution_policy=settings.remote_profile_id?{mode:"pinned",environmentId:settings.remote_profile_id}:{mode:"auto",preferredEnvironmentIds:[]};
   const preview=object(legacy.preview)?legacy.preview:null;
   const payload={positive_text:typeof legacy.chinese_positive==="string"?legacy.chinese_positive:typeof preview?.chinese_positive==="string"?preview.chinese_positive:"",excluded_text:typeof legacy.chinese_negative==="string"?legacy.chinese_negative:typeof preview?.chinese_negative==="string"?preview.chinese_negative:"",english_positive:legacy.positive_prompt,english_negative:typeof legacy.negative_prompt==="string"?legacy.negative_prompt:"",title:typeof legacy.project_name==="string"&&legacy.project_name.trim()?legacy.project_name:"英文原文创作",model_profile:typeof legacy.model_profile==="string"&&legacy.model_profile?legacy.model_profile:"anima_aesthetic_v1_1",generation_settings:settings,legacy_source_raw:raw};
   void legacyDirectImportId(raw).then(importId=>{if(canceled)return;storeDirectImport({...payload,import_id:importId,...(!payload.english_positive.trim()?{allow_empty:true}:{})});setState({to:"/workbench?from=direct"});}).catch(caught=>{if(!canceled)setState({error:(caught as Error).message});});
  }catch(caught){setState({error:(caught as Error).message});}
  return()=>{canceled=true;};
 },[location.search]);
 if(!state)return <p role="status">正在恢复原文编辑…</p>;
 if("to" in state)return <Navigate to={state.to} replace/>;
 return <section className="page"><h1>恢复原文创作</h1><p role="alert">{state.error}</p><p>此入口不会自动提交生成，旧记录会继续保留。</p><Link to="/generate">打开任务记录核对</Link><p><Link to="/workbench">返回工作台</Link></p></section>;
}
