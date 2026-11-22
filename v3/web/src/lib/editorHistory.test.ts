import {describe, expect, it} from "vitest";
import {appendOperation, createJournal, replayOperation, operationBetween} from "./editorHistory";
import {emptyRequirements, type LocalConversation} from "./conversation";
import {defaultGenerationSettings} from "./generationSettings";
const local = (): LocalConversation => ({baseRevision:1,delta:"warm light",mode:"faithful",positive:"first",negative:"",model:"anima",settings:defaultGenerationSettings(),requirements:emptyRequirements()});
describe("scoped editor journal", () => {
  it("undoes AI content while preserving later execution settings and fresh opinion", () => {
    const before=local(), after={...before,positive:"second",delta:""};
    const operation=operationBetween(before,after,"ai","warm light",1)!;
    const latest={...after,delta:"new request",settings:{...after.settings,steps:22}};
    const restored=replayOperation(latest,operation,"undo");
    expect(restored.positive).toBe("first"); expect(restored.settings.steps).toBe(22); expect(restored.delta).toBe("new request");
    expect(replayOperation(after,operation,"undo").delta).toBe("warm light");
  });
  it("archives before limiting shortcuts and keeps discarded redo snapshots", () => {
    let journal=createJournal("w","d"); let before=local();
    for(let i=0;i<53;i++){const after={...before,positive:String(i)};journal=appendOperation(journal,operationBetween(before,after,"manual","edit",i)!);before=after;}
    expect(journal.entries).toHaveLength(50); expect(journal.outbox).toHaveLength(53); expect(journal.archived).toHaveLength(3);
    journal={...journal,cursor:48}; const next=appendOperation(journal,operationBetween(before,{...before,negative:"bad"},"manual","branch",99)!);
    expect(next.archived).toHaveLength(5); expect(next.outbox).toHaveLength(54);
  });
  it("does not create an operation for unchanged AI output",()=>{const value=local();expect(operationBetween(value,{...value,delta:""},"ai","unchanged",1)).toBeNull();});
  it("records individual settings keys",()=>{const before=local(),after={...before,settings:{...before.settings,steps:22}};const op=operationBetween(before,after,"parameter","steps",1)!;expect(op.scope).toEqual(["settings.steps"]);expect(replayOperation({...after,settings:{...after.settings,cfg:3.2}},op,"undo").settings.cfg).toBe(3.2);});
  it("round trips optional objects atomically without leaving malformed empty configuration",()=>{
    const before=local();
    const after={...before,creation_configuration:{workflow:{id:"workflow",revision:2},parameterOverrides:{steps:22}},workflow_parameter_schema:{version:1,fields:[{key:"steps",type:"integer"}]}};
    const operation=operationBetween(before,after,"parameter","configure",1)!;
    expect(operation.scope).toEqual(["creation_configuration","workflow_parameter_schema"]);
    const undo=replayOperation(after,operation,"undo");expect(undo).toEqual(before);expect("creation_configuration" in undo).toBe(false);
    const persisted=JSON.parse(JSON.stringify(operation));expect(replayOperation(before,persisted,"redo")).toEqual(after);
    const remove=operationBetween(after,before,"parameter","remove",2)!;expect(replayOperation(before,remove,"undo")).toEqual(after);
  });
  it("undoes restore's displaced opinion only when no new opinion was typed",()=>{
    const before=local(),after={...before,positive:"restored",delta:"",restoredFrom:"V2"};const operation=operationBetween(before,after,"restore","restore",1)!;
    const undo=replayOperation(after,operation,"undo");expect(undo.delta).toBe("warm light");expect(undo.restoredFrom).toBeUndefined();
    expect(replayOperation({...after,delta:"new opinion"},operation,"undo").delta).toBe("new opinion");
    expect(replayOperation(undo,operation,"redo").delta).toBe("");expect(replayOperation({...undo,delta:"new opinion"},operation,"redo").delta).toBe("new opinion");
  });
});
