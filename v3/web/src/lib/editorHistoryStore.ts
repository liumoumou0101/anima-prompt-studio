import type {LocalConversation} from "./conversation";
import {validJournal,type EditorJournal} from "./editorHistory";
export interface EditorBundle {schemaVersion:1; workspaceId:string;documentId:string;local:LocalConversation;base?:LocalConversation|null;journal:EditorJournal;savedAt:number}
let database:Promise<IDBDatabase>|undefined;
function openDatabase(){return database ||= new Promise<IDBDatabase>((resolve,reject)=>{
 const request=indexedDB.open("anima-editor-history",1);
 request.onupgradeneeded=()=>{request.result.createObjectStore("documents",{keyPath:"key"});};request.onsuccess=()=>resolve(request.result);request.onerror=()=>{database=undefined;reject(request.error);};
});}
/** Draft, operation snapshots and checkpoint outbox commit as one record in one transaction. */
export async function saveEditorBundle(bundle:EditorBundle):Promise<void>{
 const frozen=structuredClone(bundle);
 const db=await openDatabase();await new Promise<void>((resolve,reject)=>{const transaction=db.transaction("documents","readwrite");transaction.objectStore("documents").put({...frozen,key:`${frozen.workspaceId}:${frozen.documentId}`});transaction.oncomplete=()=>resolve();transaction.onerror=()=>reject(transaction.error);transaction.onabort=()=>reject(transaction.error||new Error("草稿保存已中止"));});
}
export async function readEditorBundle(workspaceId:string,documentId:string):Promise<EditorBundle|null>{
 const db=await openDatabase();return new Promise((resolve,reject)=>{const request=db.transaction("documents","readonly").objectStore("documents").get(`${workspaceId}:${documentId}`);request.onsuccess=()=>{const value=request.result;if(value && (value.schemaVersion!==1||value.workspaceId!==workspaceId||value.documentId!==documentId||!value.local||typeof value.local.positive!=="string"||typeof value.local.negative!=="string"||!validJournal(value.journal,workspaceId))){reject(new Error("编辑日志损坏，原始记录已保留"));return;}resolve(value||null);};request.onerror=()=>reject(request.error);});
}
/** Only the supplied document lineage is eligible; never adopt another window's latest cursor. */
export async function readLatestEditorBundle(workspaceId:string,documentIds:readonly string[],reader:typeof readEditorBundle=readEditorBundle):Promise<EditorBundle|null>{
 for(const documentId of [...new Set(documentIds)]){const bundle=await reader(workspaceId,documentId);if(bundle)return bundle;}
 return null;
}
