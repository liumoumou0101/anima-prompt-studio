import {useState} from "react";
import {act,cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach,expect,it,vi} from "vitest";
import {LoraResources} from "./LoraResources";
import {notifyLoraEnvironmentChanged,useLoraPreparation,type LibraryLora} from "../lib/loraLibrary";
import type {RequirementLora} from "../lib/types";

const sha="a".repeat(64), other="b".repeat(64);
const asset:LibraryLora={id:sha,sha256:sha,name:"墨线",file_name:`anima_library/${sha}.safetensors`,relative_path:"墨线.safetensors",family:"anima",model_profiles:[],weight:.75,clip_weight:null,trigger_words:["ink"],present:true,valid:true,error:"",size_bytes:100};
const manual:RequirementLora={logical_id:"old",file_name:"old.safetensors",weight:1,trigger_words:[],required:true,source:{kind:"user"}};
function Harness({remote}:{remote:string}){
  const [items,setItems]=useState<RequirementLora[]>([manual]);
  const prep=useLoraPreparation(remote,items);
  return <MemoryRouter><LoraResources items={items} onChange={setItems} model="anima_turbo_v1_1" family="anima" preparation={prep}/><button type="button" onClick={()=>void prep.verifyCurrent().catch(()=>{})}>生成前复核</button><output aria-label="选中数据">{JSON.stringify(items)}</output></MemoryRouter>;
}
afterEach(()=>{cleanup();vi.restoreAllMocks();});
const idlePreparation={state:"idle" as const,blocked:false,message:"",retry:vi.fn(),verifyCurrent:async()=>{}};
it("offers template switching inside the frozen resource area without unlocking fields until the parent detaches it",()=>{
  const switchTemplate=vi.fn();
  const props={items:[manual],model:"anima_turbo_v1_1",family:"anima" as const,preparation:idlePreparation,onChange:vi.fn(),frozen:true};
  const view=render(<MemoryRouter><LoraResources {...props} onEditSnapshot={switchTemplate}/></MemoryRouter>);
  const switchButton=screen.getByRole("button",{name:"切换模板并编辑 LoRA"});
  expect(screen.getByRole("button",{name:"从库中选择"})).toBeDisabled();
  fireEvent.click(switchButton);
  expect(switchTemplate).toHaveBeenCalledOnce();
  expect(screen.getByRole("checkbox",{name:"启用 old.safetensors"})).toBeDisabled();
  view.rerender(<MemoryRouter><LoraResources {...props} onEditSnapshot={switchTemplate} disabled/></MemoryRouter>);
  expect(switchButton).toBeDisabled();
  view.rerender(<MemoryRouter><LoraResources {...props}/></MemoryRouter>);
  expect(screen.getByRole("button",{name:"切换模板并编辑 LoRA"})).toBeDisabled();
  expect(screen.getByText(/没有可用的兼容模板/)).toBeVisible();
});
it("keeps model strength visible while manual filenames, trigger words and optional text-encoder weight stay in details",()=>{
  const props={items:[manual],model:"anima_turbo_v1_1",family:"anima" as const,preparation:idlePreparation,onChange:vi.fn()};
  const view=render(<MemoryRouter><LoraResources {...props}/></MemoryRouter>);
  expect(screen.getByRole("spinbutton",{name:"权重"})).toBeVisible();
  const disclosure=screen.getByText("高级设置").closest("details")!;
  expect(disclosure.open).toBe(false);
  expect(disclosure).toContainElement(screen.getByLabelText("文本编码器权重"));
  expect(disclosure).toContainElement(screen.getByLabelText("文件名"));
  expect(disclosure).toContainElement(screen.getByLabelText("触发词（每行一项）"));
  view.rerender(<MemoryRouter><LoraResources {...props} family="moss"/></MemoryRouter>);
  expect(screen.queryByLabelText("文本编码器权重")).toBeNull();
});
it("prepares only enabled library files, preserves manual rows and rechecks a changed environment",async()=>{
  const posts:{url:string;body:unknown}[]=[];
  vi.spyOn(globalThis,"fetch").mockImplementation(async(input,options)=>{
    const url=String(input);
    if(url.endsWith("/sync")){posts.push({url,body:JSON.parse(String(options?.body))});return Response.json({id:"job",state:"queued"});}
    if(url.endsWith("/jobs/job"))return Response.json({id:"job",state:"completed",environment_signature:"sig",results:[{sha256:sha,cached:true,installed:true}]});
    return Response.json({root_path:"loras",items:[asset,{...asset,id:other,sha256:other,family:"moss",name:"MOSS 专用"}]});
  });
  const view=render(<Harness remote="first"/>);
  fireEvent.click(screen.getByRole("button",{name:"从库中选择"}));
  fireEvent.click(await screen.findByRole("button",{name:"添加 墨线"}));
  await screen.findByText(/当前环境已就绪/);
  expect(posts.map(p=>p.body)).toEqual([{sha256s:[sha]}]);
  expect(screen.queryByRole("button",{name:"添加 MOSS 专用"})).toBeNull();
  fireEvent.click(screen.getByRole("button",{name:"上移 墨线"}));
  expect(JSON.parse(screen.getByRole("status",{name:"选中数据"}).textContent!)[0]).toMatchObject({logical_id:"library:"+sha,weight:.75});
  fireEvent.click(screen.getByRole("checkbox",{name:"启用 墨线"}));
  view.rerender(<Harness remote="second"/>);
  expect(posts).toHaveLength(1);
  fireEvent.click(screen.getByRole("checkbox",{name:"启用 墨线"}));
  await waitFor(()=>expect(posts[1]?.url).toContain("/second/sync"));
  expect(JSON.parse(screen.getByRole("status",{name:"选中数据"}).textContent!)[1]).toEqual(manual);
});
it("lets the user retry a failed preparation and rechecks an enabled item on reconnect",async()=>{
  let attempts=0;
  vi.spyOn(globalThis,"fetch").mockImplementation(async input=>{
    const url=String(input);
    if(url.endsWith("/sync")){
      attempts++;
      return Response.json(attempts===1 ? {id:"job1",state:"failed",error:"运行时断开",results:[{sha256:sha,cached:true,installed:true}]} : {id:"ready",state:"completed",environment_signature:"sig",results:[{sha256:sha,cached:true,installed:true}]});
    }
    return Response.json({root_path:"loras",items:[asset]});
  });
  render(<Harness remote="same-address"/>);
  fireEvent.click(screen.getByRole("button",{name:"从库中选择"}));
  fireEvent.click(await screen.findByRole("button",{name:"添加 墨线"}));
  await screen.findByText(/运行时断开/);
  expect(screen.queryByText(/当前环境可用/)).toBeNull();
  fireEvent.click(screen.getByRole("button",{name:"重试准备"}));
  await screen.findByText(/当前环境已就绪/);
  fireEvent(window,new Event("online"));
  await waitFor(()=>expect(attempts).toBe(3));
});
it.each(["same-tab","other-tab"])("discards an older job after %s settings replace a session under the same profile ID",async origin=>{
  let old:((r:Response)=>void)|undefined, attempts=0;
  vi.spyOn(globalThis,"fetch").mockImplementation(async input=>{
    const url=String(input);
    if(url.endsWith("/sync"))return Response.json({id:++attempts===1?"old":"new",state:"queued"});
    if(url.endsWith("/jobs/old"))return new Promise(resolve=>{old=resolve;});
    if(url.endsWith("/jobs/new"))return Response.json({id:"new",state:"failed",error:"新环境没有缓存",results:[{sha256:sha,cached:true,installed:true}]});
    return Response.json({root_path:"loras",items:[asset]});
  });
  render(<Harness remote="same-address"/>);
  fireEvent.click(screen.getByRole("button",{name:"从库中选择"}));
  fireEvent.click(await screen.findByRole("button",{name:"添加 墨线"}));
  await waitFor(()=>expect(old).toBeDefined());
  if(origin==="same-tab")act(()=>notifyLoraEnvironmentChanged("same-address"));
  else fireEvent(window,new StorageEvent("storage",{key:"anima-lora-connection-changed",newValue:JSON.stringify(["same-address","new"])}));
  await screen.findByText(/新环境没有缓存/);
  await act(async()=>old!(Response.json({id:"old",state:"completed",environment_signature:"old",results:[{sha256:sha,cached:true,installed:true}]})));
  expect(screen.queryByText(/当前环境已就绪|当前环境可用/)).toBeNull();
  expect(attempts).toBe(2);
});
it("rechecks the signature on focus and before submit, preparing only when the instance changed",async()=>{
  let signature="original", checks=0, attempts=0;
  vi.spyOn(globalThis,"fetch").mockImplementation(async input=>{
    const url=String(input);
    if(url.endsWith("/identity")){checks++;return Response.json({signature});}
    if(url.endsWith("/sync")){attempts++;return Response.json({id:"job",state:"completed",environment_signature:signature,results:[{sha256:sha,cached:true,installed:true}]});}
    return Response.json({root_path:"loras",items:[asset]});
  });
  render(<Harness remote="same-address"/>);
  fireEvent.click(screen.getByRole("button",{name:"从库中选择"}));
  fireEvent.click(await screen.findByRole("button",{name:"添加 墨线"}));
  await screen.findByText(/当前环境已就绪/);
  fireEvent(window,new Event("focus"));
  await waitFor(()=>expect(checks).toBe(1));
  expect(attempts).toBe(1);
  signature="replacement";
  fireEvent.click(screen.getByRole("button",{name:"生成前复核"}));
  await waitFor(()=>expect(attempts).toBe(2));
});
