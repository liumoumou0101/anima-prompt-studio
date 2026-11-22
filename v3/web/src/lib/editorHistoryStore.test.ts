import {expect,it,vi} from "vitest";
import {readLatestEditorBundle,type EditorBundle} from "./editorHistoryStore";
import {createJournal} from "./editorHistory";
import {emptyRequirements} from "./conversation";
import {defaultGenerationSettings} from "./generationSettings";
const bundle=(id:string):EditorBundle=>({schemaVersion:1,workspaceId:"workspace",documentId:id,savedAt:1,base:null,local:{baseRevision:1,delta:"unsent",positive:"recovered",negative:"",mode:"faithful",model:"anima",requirements:emptyRequirements(),settings:defaultGenerationSettings()},journal:createJournal("workspace",id)});
it("recovers only this document's persisted lineage and never another window's newest cursor",async()=>{
 const original=bundle("ancestor");const reader=vi.fn(async(_workspace:string,id:string)=>id==="ancestor"?original:null);
 expect(await readLatestEditorBundle("workspace",["current","ancestor"],reader)).toEqual(original);expect(reader.mock.calls).toEqual([["workspace","current"],["workspace","ancestor"]]);
});
it("prefers current own bundle and returns null for an empty lineage instead of global workspace search",async()=>{
 const current=bundle("current"),reader=vi.fn(async()=>current);expect(await readLatestEditorBundle("workspace",["current","ancestor"],reader)).toEqual(current);expect(reader).toHaveBeenCalledTimes(1);reader.mockClear();expect(await readLatestEditorBundle("workspace",[],reader)).toBeNull();expect(reader).not.toHaveBeenCalled();
});
