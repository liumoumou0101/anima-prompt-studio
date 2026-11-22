import type {WorkbenchGenerationSettings} from "./types";
export const DIRECT_IMPORT_KEY = "anima-v3-direct-import";
export const LEGACY_DIRECT_DRAFT_KEY="anima-v3-direct-prompt-draft";
export const DIRECT_MIGRATION_RECEIPT_KEY="anima-v3-direct-migration-receipt";
export async function legacyDirectImportId(raw:string):Promise<string>{
 const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(raw));
 return "legacy-direct-v1-"+Array.from(new Uint8Array(digest),value=>value.toString(16).padStart(2,"0")).join("");
}

export interface DirectWorkbenchImport {
  import_id?: string;
  positive_text: string;
  excluded_text: string;
  english_positive: string;
  english_negative: string;
  title?:string;
  model_profile?:string;
  generation_settings?:Partial<WorkbenchGenerationSettings>;
  legacy_source_raw?:string;
  allow_empty?:boolean;
}

let consumedImport: DirectWorkbenchImport | null | undefined;

export function storeDirectImport(payload: DirectWorkbenchImport): void {
  const durable={...payload,import_id:payload.import_id||crypto.randomUUID()};
  sessionStorage.setItem(DIRECT_IMPORT_KEY, JSON.stringify(durable));
  consumedImport = durable;
}

/** Non-destructive handoff read. A successful draft commit must precede acknowledgement. */
export function readDirectImport(): DirectWorkbenchImport | null {
  const raw=sessionStorage.getItem(DIRECT_IMPORT_KEY);if(!raw)return null;
  const value=JSON.parse(raw) as Partial<DirectWorkbenchImport>;
  if(typeof value.english_positive!=="string"||!value.english_positive.trim()&&value.allow_empty!==true||typeof value.positive_text!=="string")throw new Error("原文导入记录不完整；原始记录已保留，请返回原文编辑重新导入。");
  if(value.generation_settings!==undefined&&(!value.generation_settings||typeof value.generation_settings!=="object"||Array.isArray(value.generation_settings)))throw new Error("原文导入参数记录不完整，原始记录已保留。");
  return {positive_text:value.positive_text,excluded_text:typeof value.excluded_text==="string"?value.excluded_text:"",english_positive:value.english_positive,english_negative:typeof value.english_negative==="string"?value.english_negative:"",import_id:value.import_id,
    ...(typeof value.title==="string"?{title:value.title}:{}),...(typeof value.model_profile==="string"?{model_profile:value.model_profile}:{}),
    ...(value.generation_settings?{generation_settings:value.generation_settings}:{}),...(typeof value.legacy_source_raw==="string"?{legacy_source_raw:value.legacy_source_raw}:{}),...(value.allow_empty===true?{allow_empty:true}:{})};
}
export function acknowledgeDirectImport(payload:DirectWorkbenchImport,workspaceId?:string):void {
 const current=readDirectImport();if(!current||JSON.stringify(current)!==JSON.stringify(payload))return;
 if(payload.legacy_source_raw!==undefined)localStorage.setItem(DIRECT_MIGRATION_RECEIPT_KEY,JSON.stringify({raw:payload.legacy_source_raw,workspaceId:workspaceId||null,importId:payload.import_id,appliedAt:Date.now()}));
 sessionStorage.setItem("anima-v3-direct-import-receipt",JSON.stringify({import_id:payload.import_id||null,workspace_id:workspaceId||null,appliedAt:Date.now()}));
 sessionStorage.removeItem(DIRECT_IMPORT_KEY);consumedImport=null;
}

export function consumeDirectImport(): DirectWorkbenchImport | null {
  if (consumedImport !== undefined) return consumedImport;
  try {
    const raw = sessionStorage.getItem(DIRECT_IMPORT_KEY);
    if (!raw) {
      consumedImport = null;
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<DirectWorkbenchImport>;
    if (!parsed.positive_text || typeof parsed.positive_text !== "string") {
      consumedImport = null;
      return null;
    }
    consumedImport = {
      positive_text: parsed.positive_text,
      excluded_text: typeof parsed.excluded_text === "string" ? parsed.excluded_text : "",
      english_positive: typeof parsed.english_positive === "string" ? parsed.english_positive : "",
      english_negative: typeof parsed.english_negative === "string" ? parsed.english_negative : "",
    };
    sessionStorage.removeItem(DIRECT_IMPORT_KEY);
    return consumedImport;
  } catch {
    consumedImport = null;
    return null;
  }
}

export function resetDirectImportForTests(): void {
  consumedImport = undefined;
  sessionStorage.removeItem(DIRECT_IMPORT_KEY);
}
