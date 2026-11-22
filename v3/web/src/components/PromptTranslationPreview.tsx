import {useEffect,useRef,useState} from "react";
import {apiRequest} from "../lib/api";
import type {DirectPromptPreview} from "../lib/types";

export interface PromptTranslationPreviewProps {positive:string;negative:string;model:string;disabled?:boolean}

/** Local dictionary/translation preview never changes editor content or submits generation. */
export function PromptTranslationPreview({positive,negative,model,disabled=false}:PromptTranslationPreviewProps){
 const [preview,setPreview]=useState<DirectPromptPreview|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
 const controller=useRef<AbortController|null>(null),epoch=useRef(0),input=useRef("");
 const fingerprint=JSON.stringify([positive,negative,model]);input.current=fingerprint;
 useEffect(()=>{
   epoch.current++;controller.current?.abort();controller.current=null;setPreview(null);setError("");setBusy(false);
   return()=>{epoch.current++;controller.current?.abort();controller.current=null;};
 },[fingerprint]);
 async function translate(){
   if(disabled||!positive.trim()||controller.current)return;
   const active=new AbortController(),requestEpoch=++epoch.current,submitted=fingerprint;
   controller.current=active;setBusy(true);setError("");setPreview(null);
   const current=()=>!active.signal.aborted&&epoch.current===requestEpoch&&input.current===submitted;
   try{
     const result=await apiRequest<DirectPromptPreview>("/api/v3/direct-prompt/preview",{method:"POST",signal:active.signal,body:JSON.stringify({positive_prompt:positive,negative_prompt:negative})});
     if(!Array.isArray(result.positive_tokens)||!Array.isArray(result.negative_tokens)||typeof result.chinese_positive!=="string"||typeof result.chinese_negative!=="string")throw new Error("中文对照记录不完整，请重试。");
     if(current())setPreview(result);
   }catch(caught){if(current())setError((caught as Error).message);}
   finally{if(current())setBusy(false);if(controller.current===active)controller.current=null;}
 }
 return <details className="prompt-translation-preview"><summary>中英标签对照</summary>
   <p>按逗号整词匹配，查看本地词典与中文回译。</p>
   <button type="button" disabled={disabled||busy||!positive.trim()} onClick={()=>void translate()}>{busy?"正在读取中文对照…":"查看中文对照"}</button>
   {error&&<p role="alert">{error}</p>}
   {preview&&<section aria-label="中文对照预览">
     <p>{preview.matched_count} 个已对照中文标签 · {preview.unmatched_count} 个未入词典{preview.translation_engine?` · ${preview.translation_engine}`:""}</p>
     <p className="direct-chinese">{preview.chinese_positive||"（正向为空）"}</p>
     {preview.chinese_negative&&<p className="direct-chinese is-negative">排除：{preview.chinese_negative}</p>}
     <TokenTable title="正向" tokens={preview.positive_tokens}/>
     {preview.negative_tokens.length>0&&<TokenTable title="反向" tokens={preview.negative_tokens}/>}
   </section>}
 </details>;
}

function TokenTable({title,tokens}:{title:string;tokens:DirectPromptPreview["positive_tokens"]}){
 return <div className="direct-token-table"><strong>{title}</strong><ul>{tokens.map((token,index)=><li key={`${title}-${index}`}><code>{token.original}</code><span>{token.zh}</span><small>{token.matched?token.canonical_tag?.replaceAll("_"," "):"未匹配，保留原词"}</small></li>)}</ul></div>;
}
