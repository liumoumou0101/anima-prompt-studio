import type {LocalConversation} from "./conversation";

export type EditKind = "ai" | "manual" | "parameter" | "restore" | "import" | "save" | "generation";
export interface EditOperation {
  id:string; kind:EditKind; scope:string[]; before:Record<string,unknown>; after:Record<string,unknown>;
  label:string; createdAt:number; baseRevision:number; editorEpoch:number;
  opinion:string; snapshot:LocalConversation; beforeSnapshot:LocalConversation;
  documentId?:string;
}
export interface EditorJournal {
  schemaVersion:1; workspaceId:string; documentId:string; cursor:number; entries:EditOperation[];
  archived:EditOperation[]; outbox:EditOperation[]; baseFingerprint:string; editorEpoch:number;
  pendingRestore?:{operationId:string;body:string;rejected?:boolean};
}
const copy=<T,>(value:T):T=>structuredClone(value);
const same=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b);
export function createJournal(workspaceId:string,documentId:string):EditorJournal {
 return {schemaVersion:1,workspaceId,documentId,cursor:0,entries:[],archived:[],outbox:[],baseFingerprint:"",editorEpoch:0};
}
function plainObject(value:unknown):value is Record<string,unknown>{return Boolean(value)&&typeof value==="object"&&!Array.isArray(value);}
function diffFields(before:unknown,after:unknown,prefix:string,left:Record<string,unknown>,right:Record<string,unknown>){
 if(same(before,after))return;
 // An optional object appearing/disappearing is one field. Leaf-wise deletion
 // would leave an invalid empty configuration or schema behind during undo.
 if(plainObject(before)&&plainObject(after)){
   for(const key of new Set([...Object.keys(before),...Object.keys(after)]))diffFields(before[key],after[key],prefix?`${prefix}.${key}`:key,left,right);
 }else{left[prefix]=before;right[prefix]=after;}
}
export function operationBetween(before:LocalConversation,after:LocalConversation,kind:EditKind,label:string,editorEpoch:number):EditOperation|null {
 const left:Record<string,unknown>={},right:Record<string,unknown>={};diffFields(before,after,"",left,right);
 const scopedRestore=kind==="restore"||kind==="import";
 const scope=[...new Set([...Object.keys(left),...Object.keys(right)])].filter(key=>key!=="baseRevision"&&(scopedRestore||!["delta","restoredFrom"].includes(key))&&!same(left[key],right[key]));
 if(!scope.length)return null;
 return {id:crypto.randomUUID(),kind,scope,before:Object.fromEntries(scope.map(key=>[key,copy(left[key])])),after:Object.fromEntries(scope.map(key=>[key,copy(right[key])])),label,createdAt:Date.now(),baseRevision:before.baseRevision,editorEpoch,opinion:before.delta,snapshot:copy(after),beforeSnapshot:copy(before)};
}
export function appendOperation(journal:EditorJournal,operation:EditOperation):EditorJournal {
 const discarded=journal.entries.slice(journal.cursor),entries=[...journal.entries.slice(0,journal.cursor),operation];
 const evicted=entries.splice(0,Math.max(0,entries.length-50));
 return {...journal,entries,cursor:entries.length,archived:[...journal.archived,...discarded,...evicted],outbox:[...journal.outbox,operation]};
}
export function replayOperation(value:LocalConversation,operation:EditOperation,direction:"undo"|"redo"):LocalConversation {
 const next=copy(value),fields=direction==="undo"?operation.before:operation.after;
 for(const path of operation.scope){if(path==="delta")continue;const keys=path.split(".");let parent=next as unknown as Record<string,unknown>;for(const key of keys.slice(0,-1)){if(!parent[key]||typeof parent[key]!=="object")parent[key]={};parent=parent[key] as Record<string,unknown>;} const key=keys.at(-1)!;if(fields[path]===undefined)delete parent[key];else parent[key]=copy(fields[path]);}
 if(direction==="undo" && operation.kind==="ai" && !value.delta)next.delta=operation.opinion;
 if(operation.kind==="restore"||operation.kind==="import"){
   const from=direction==="undo"?operation.snapshot:operation.beforeSnapshot,to=direction==="undo"?operation.beforeSnapshot:operation.snapshot;
   if(value.delta===from.delta)next.delta=to.delta;
 }
 return next;
}
export function validJournal(value:unknown,workspaceId:string):value is EditorJournal {
 if(!value||typeof value!=="object")return false;const item=value as EditorJournal;
 return item.schemaVersion===1&&item.workspaceId===workspaceId&&typeof item.documentId==="string"&&Number.isInteger(item.cursor)&&Array.isArray(item.entries)&&item.cursor>=0&&item.cursor<=item.entries.length&&Array.isArray(item.archived)&&Array.isArray(item.outbox)&&[...item.entries,...item.archived,...item.outbox].every(op=>typeof op.id==="string"&&Array.isArray(op.scope)&&op.before&&op.after&&op.snapshot&&op.beforeSnapshot);
}
