import {useRef,useState} from "react";
import {appendOperation,createJournal,operationBetween,replayOperation,type EditKind,type EditorJournal} from "./editorHistory";
import type {LocalConversation} from "./conversation";
export function useEditorHistory(){
 const journal=useRef<EditorJournal|null>(null);const [,render]=useState(0);
 function initialize(workspaceId:string,documentId:string,recovered?:EditorJournal){
   if(recovered)for(const operation of [...recovered.entries,...recovered.archived,...recovered.outbox])operation.documentId ||= recovered.documentId;
   journal.current=recovered?{...recovered,documentId}:createJournal(workspaceId,documentId);render(value=>value+1);
 }
 function record(before:LocalConversation,after:LocalConversation,kind:EditKind,label:string){if(!journal.current)return;const operation=operationBetween(before,after,kind,label,journal.current.editorEpoch);if(operation){operation.documentId=journal.current.documentId;journal.current=appendOperation(journal.current,operation);render(value=>value+1);}return operation;}
 function travel(value:LocalConversation,redo=false){const current=journal.current;if(!current)return null;const index=redo?current.cursor:current.cursor-1,operation=current.entries[index];if(!operation)return null;journal.current={...current,cursor:current.cursor+(redo?1:-1),editorEpoch:current.editorEpoch+1};render(value=>value+1);return {value:replayOperation(value,operation,redo?"redo":"undo"),label:operation.label};}
 return {journal,initialize,record,travel,canUndo:Boolean(journal.current?.cursor),canRedo:Boolean(journal.current&&journal.current.cursor<journal.current.entries.length),refresh:()=>render(value=>value+1)};
}
