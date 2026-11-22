import {useEffect, useRef, useState} from "react";
import {apiRequest} from "./api";
import type {RequirementLora} from "./types";

export const libraryPath = "/api/v3/loras";
const CONNECTION_CHANGED="anima-lora-connection-changed";
export function notifyLoraEnvironmentChanged(remote:string) {
  if(!remote)return;
  window.dispatchEvent(new CustomEvent(CONNECTION_CHANGED,{detail:remote}));
  // Other desktop tabs share local storage. Store only the profile ID and a change nonce.
  try{localStorage.setItem(CONNECTION_CHANGED,JSON.stringify([remote,crypto.randomUUID()]));}catch{/* Focus and pre-submit checks remain available. */}
}
export const families = {unknown:"待分类",anima:"ANIMA",moss:"MOSS",sdxl:"SDXL / Illustrious"};
export type LoraFamily = keyof typeof families;
export interface LibraryLora {
  id:string; sha256:string; name:string; file_name:string; relative_path:string; size_bytes:number;
  family:LoraFamily; model_profiles:string[]; trigger_words:string[]; weight:number; clip_weight:number|null;
  present:boolean; valid:boolean; error:string|null;
}
export interface LibraryListing {root_path:string; items:LibraryLora[]; errors?:{path:string;error:string}[]}
export function libraryRequirement(asset:LibraryLora):RequirementLora {
  return {logical_id:"library:"+asset.sha256,sha256:asset.sha256,file_name:asset.file_name,weight:asset.weight,
    clip_weight:asset.clip_weight,enabled:true,trigger_words:[...asset.trigger_words],required:true,source:{kind:"user"}};
}
interface AssetResult {sha256:string; cached?:boolean; installed?:boolean; restored?:boolean; uploaded_bytes?:number}
interface SyncJob {id:string; state:"queued"|"running"|"completed"|"failed"; environment_signature?:string; progress?:number; message?:string; results?:AssetResult[]; error?:string}
interface PreparationStatus {key:string; state:"preparing"|"ready"|"failed"; signature?:string; message:string; progress?:number; results?:AssetResult[]}
export interface LoraPreparation {
  blocked:boolean; message:string; state:"idle"|"waiting"|"preparing"|"ready"|"failed"; progress?:number; results?:AssetResult[]; retry:()=>void;
  verifyCurrent:()=>Promise<void>;
}
// Check the selected runtime afresh on mount, reconnect, or a change to the enabled file set.
export function useLoraPreparation(remote:string|undefined,requirements:RequirementLora[]):LoraPreparation {
  const hashes=[...new Set(requirements.filter(r=>r.enabled!==false && r.sha256).map(r=>r.sha256!))].sort().join(",");
  const [attempt,setAttempt]=useState(0);
  const [status,setStatus]=useState<PreparationStatus|null>(null);
  const key=JSON.stringify([remote,hashes,attempt]);
  const currentKey=useRef<string|null>(key);
  currentKey.current=key;
  function retry(){currentKey.current=null;setAttempt(n=>n+1);}
  async function verifyCurrent(){
    if(!hashes)return;
    if(!remote || status?.key!==key || status.state!=="ready")throw new Error("请先完成当前环境的 LoRA 准备。");
    let identity:{signature:string};
    try{
      identity=await apiRequest(libraryPath+"/environments/"+encodeURIComponent(remote)+"/identity",{signal:AbortSignal.timeout(10_000)});
    }catch(error){
      if(currentKey.current===key)setStatus({key,state:"failed",message:"无法确认当前连接，请重新准备 LoRA。"});
      throw error;
    }
    if(currentKey.current!==key)throw new Error("当前生成条件已变化，请重新确认。");
    if(!identity.signature || status.signature!==identity.signature){
      retry();
      throw new Error("运行环境已变化，正在重新准备 LoRA。");
    }
  }
  useEffect(()=>{
    if(!remote||!hashes || status?.state!=="ready" || status.key!==key)return;
    const verifyOnReturn=()=>{if(document.visibilityState!=="hidden")void verifyCurrent().catch(()=>{});};
    window.addEventListener("focus",verifyOnReturn);document.addEventListener("visibilitychange",verifyOnReturn);
    return ()=>{window.removeEventListener("focus",verifyOnReturn);document.removeEventListener("visibilitychange",verifyOnReturn);};
  },[key,status]);
  useEffect(()=>{
    if(!remote||!hashes){setStatus(null);return;}
    currentKey.current=key;
    function otherTab(event:StorageEvent){
      if(event.key!==CONNECTION_CHANGED || !event.newValue)return;
      try{if(JSON.parse(event.newValue)[0]===remote)retry();}catch{/* Ignore malformed notifications. */}
    }
    function thisTab(event:Event){if((event as CustomEvent).detail===remote)retry();}
    window.addEventListener("storage",otherTab);window.addEventListener(CONNECTION_CHANGED,thisTab);
    window.addEventListener("online",retry);
    const controller=new AbortController();
    let timer=0;
    const started=Date.now();
    async function check(id?:string) {
      try {
        const signal=AbortSignal.any([controller.signal,AbortSignal.timeout(30_000)]);
        const job=id ? await apiRequest<SyncJob>(libraryPath+"/jobs/"+encodeURIComponent(id),{signal})
          : await apiRequest<SyncJob>(libraryPath+"/environments/"+encodeURIComponent(remote!)+"/sync",{method:"POST",body:JSON.stringify({sha256s:hashes.split(",")}),signal});
        if(controller.signal.aborted || currentKey.current!==key)return;
        if(job.state==="failed"){
          setStatus({key,state:"failed",message:job.error || job.message || "LoRA 准备失败",results:job.results});return;
        }
        if(job.state==="completed") {
          if(!job.environment_signature || !hashes.split(",").every(sha=>job.results?.some(r=>r.sha256===sha && r.installed)))
            throw new Error("同步返回的已安装文件不完整，请重新检查环境。");
          setStatus({key,state:"ready",signature:job.environment_signature,message:"所选 LoRA 在当前环境已就绪。",results:job.results});return;
        }
        if(!job.id || !["queued","running"].includes(job.state))throw new Error("未取得有效的准备任务，请重试。");
        if(Date.now()-started>30*60*1000)throw new Error("准备任务仍未确认，可重新检查当前环境。");
        setStatus({key,state:"preparing",message:job.message || "正在检查 Drive 缓存并准备当前环境…",progress:job.progress,results:job.results});
        timer=window.setTimeout(()=>void check(job.id),id?1200:0);
      } catch(error) {
        if(!controller.signal.aborted && currentKey.current===key)setStatus({key,state:"failed",message:(error as Error).message});
      }
    }
    timer=window.setTimeout(()=>void check(),0);
    return ()=>{currentKey.current=null;controller.abort();window.clearTimeout(timer);window.removeEventListener("online",retry);
      window.removeEventListener("storage",otherTab);window.removeEventListener(CONNECTION_CHANGED,thisTab);};
  },[key,remote,hashes]);
  if(!hashes)return {blocked:false,state:"idle",message:"",retry,verifyCurrent};
  if(!remote)return {blocked:true,state:"waiting",message:"选择执行环境后准备 LoRA。",retry,verifyCurrent};
  if(status?.key!==key)return {blocked:true,state:"preparing",message:"正在检查当前环境的 LoRA…",retry,verifyCurrent};
  return {...status,blocked:status.state!=="ready",retry,verifyCurrent};
}
