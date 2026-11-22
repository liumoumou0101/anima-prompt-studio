import {act, cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {useState} from "react";
import {CloudModelCatalogPanel} from "./CloudModelCatalogPanel";
import {configurationFromSettings, resolveConfiguration, settingsFromConfiguration} from "../lib/creationConfiguration";
import {defaultGenerationSettings} from "../lib/generationSettings";
import {basicWorkflowSchema} from "../lib/workflowParameterSchema";
import type {GenerationTarget} from "../lib/types";

const schema = basicWorkflowSchema("flow", "rev1");
schema.fields.find(field=>field.key==="sampler")!.enum=["euler","dpmpp_2m"];
schema.fields.find(field=>field.key==="scheduler")!.enum=["normal","karras"];
const target:GenerationTarget={remote_profile_id:"cloud-a",remote_display_name:"测试环境",workflow_profile_id:"flow",workflow_display_name:"测试工作流",
  workflow_kind:"txt2img_basic",compatible_model_profiles:["wai_anima_v1_0"],host_fingerprint_ready:true,auth_type:"agent",private_key_passphrase_configured:false,
  template_revision:"rev1",parameter_schema:schema};
function catalog(remote="cloud-a") {
  return {remote_profile_id:remote,session_id:"session-a",environment_epoch:4,status:"ready",checked_at:1720000000,runtime_id:"runtime-a",message:"",
    items:[{id:"wai_anima_v1_0",display_name:"WAI Anima",family:"anima",supported:true,ready:true,selected_for_startup:true,
      suggested_defaults:{steps:28,cfg:5,sampler:"dpmpp_2m",scheduler:"karras"},assets:[{path:"diffusion_models/wai.safetensors",category:"diffusion_models",filename:"wai.safetensors",ready:true}],
      workflow_mappings:[{workflow_profile_id:"flow",revision:"rev1",mapping:{checkpoint:"wai.safetensors"},errors:[]}]}]};
}
const initial=()=>configurationFromSettings({...defaultGenerationSettings(),preset_id:"custom",aspect:"custom",steps:22,cfg:3,width:768,height:1024,seed:"9223372036854775807",batch_size:2,workflow_profile_id:"flow"},"wai_anima_v1_0",target);
function Harness({environmentId="cloud-a",model="wai_anima_v1_0",onMapped=vi.fn()}:{environmentId?:string|null;model?:string;onMapped?:()=>void}) {
  const [configuration,setConfiguration]=useState(initial);
  const config={...configuration,modelProfile:model};
  return <><CloudModelCatalogPanel environmentId={environmentId} environmentName="测试环境" configuration={config} schema={schema} onChange={setConfiguration} onMappingApplied={onMapped}/>
    <button onClick={()=>setConfiguration(value=>({...value,parameterOverrides:{...value.parameterOverrides,steps:19}}))}>手动编辑</button>
    <output data-testid="settings">{JSON.stringify(settingsFromConfiguration(config,{...defaultGenerationSettings(),width:768,height:1024,seed:"9223372036854775807",batch_size:2},schema))}</output>
    <output data-testid="values">{JSON.stringify(resolveConfiguration(config,schema).values)}</output></>;
}
let server:ReturnType<typeof catalog>;
let requests:{url:string;method:string;body:unknown;contentType:string|null}[];
beforeEach(()=>{
  sessionStorage.setItem("anima-v3-session","test");server=catalog();requests=[];
  vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
    requests.push({url:String(input),method:init?.method||"GET",body:init?.body?JSON.parse(String(init.body)):null,contentType:new Headers(init?.headers).get("Content-Type")});
    return new Response(JSON.stringify(server));
  });
});
afterEach(()=>{cleanup();vi.restoreAllMocks();});
it("loads current environment files and previews suggestions without changing settings until explicitly applied",async()=>{
  render(<Harness/>);
  expect(screen.getByText("正在读取云端模型目录…")).toBeInTheDocument();
  await screen.findByText("文件齐全");
  expect(screen.getByRole("region",{name:"云端模型目录"})).toHaveTextContent("测试环境");
  expect(screen.getByRole("list",{name:"建议参数改动"})).toHaveTextContent("Steps：22 → 28");
  expect(JSON.parse(screen.getByTestId("values").textContent!).steps).toBe(22);
  fireEvent.click(screen.getByRole("button",{name:"应用云端建议参数"}));
  const values=JSON.parse(screen.getByTestId("values").textContent!);
  expect(values).toMatchObject({steps:28,cfg:5,sampler:"dpmpp_2m",scheduler:"karras",width:768,height:1024,batch_size:2,seed:"9223372036854775807"});
  expect(requests).toHaveLength(1);
});
it("refreshes without resetting manual edits or applying mapping",async()=>{
  render(<Harness/>);await screen.findByText("文件齐全");
  fireEvent.click(screen.getByText("手动编辑"));
  fireEvent.click(screen.getByRole("button",{name:"刷新云端目录"}));
  await waitFor(()=>expect(requests).toHaveLength(2));
  await waitFor(()=>expect(screen.getByRole("button",{name:"刷新云端目录"})).toBeEnabled());
  expect(JSON.parse(screen.getByTestId("values").textContent!).steps).toBe(19);
  expect(requests[1]).toMatchObject({url:"/api/v3/settings/remote-profiles/cloud-a/model-catalog/refresh",method:"POST",body:{},contentType:"application/json"});
});
it("requires a definite environment in auto mode",()=>{
  render(<Harness environmentId={null}/>);
  expect(screen.getByText(/请先选择固定执行环境/)).toBeInTheDocument();expect(requests).toHaveLength(0);
});
it("displays missing files and unknown models without enabling apply actions",async()=>{
  server.items[0].ready=false;server.items[0].assets[0].ready=false;
  const {rerender}=render(<Harness/>);await screen.findByText("缺少文件");
  expect(screen.getByRole("button",{name:"应用当前工作流文件映射"})).toBeDisabled();
  rerender(<Harness model="moss"/>);await screen.findByText("当前模型未列入此云端目录，尚未适配。");
  expect(screen.queryByRole("button",{name:"应用云端建议参数"})).not.toBeInTheDocument();
});
it("rejects illegal suggestions and a mapping for another workflow revision",async()=>{
  server.items[0].suggested_defaults.sampler="unsupported";server.items[0].workflow_mappings[0].revision="old";
  render(<Harness/>);await screen.findByText("文件齐全");
  expect(screen.getByRole("button",{name:"应用云端建议参数"})).toBeDisabled();
  expect(screen.getByRole("button",{name:"应用当前工作流文件映射"})).toBeDisabled();
});
it("applies only current model mapping with catalog identity and reports success",async()=>{
  const onMapped=vi.fn();render(<Harness onMapped={onMapped}/>);await screen.findByText("文件齐全");
  fireEvent.click(screen.getByRole("button",{name:"应用当前工作流文件映射"}));
  await screen.findByText("当前工作流文件映射已保存。");
  expect(requests[1]).toEqual({url:"/api/v3/settings/remote-profiles/cloud-a/model-catalog/apply-mapping",method:"POST",contentType:"application/json",body:{model_id:"wai_anima_v1_0",workflow_profile_id:"flow",session_id:"session-a",environment_epoch:4}});
  expect(onMapped).toHaveBeenCalledOnce();
});
it("clears ready actions after refresh failure and hides raw connection errors",async()=>{
  render(<Harness/>);await screen.findByText("文件齐全");
  vi.mocked(fetch).mockRejectedValue(new Error("https://secret.example/?token=private"));
  fireEvent.click(screen.getByRole("button",{name:"刷新云端目录"}));
  await screen.findByRole("alert");
  expect(screen.queryByText("文件齐全")).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).not.toHaveTextContent("secret");
  expect(screen.queryByRole("button",{name:"应用云端建议参数"})).not.toBeInTheDocument();
});
it("invalidates stale catalog after mapping conflict",async()=>{
  render(<Harness/>);await screen.findByText("文件齐全");
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({error:{code:"cloud_catalog_conflict",message:"token=private"}}),{status:409}));
  fireEvent.click(screen.getByRole("button",{name:"应用当前工作流文件映射"}));
  await screen.findByRole("alert");expect(screen.getByRole("alert")).toHaveTextContent("请刷新目录后重试");
  expect(screen.queryByText("文件齐全")).not.toBeInTheDocument();
});
it("ignores late responses from the previous environment for the same model",async()=>{
  let finish!:(response:Response)=>void;
  vi.mocked(fetch).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  const {rerender,unmount}=render(<Harness/>);
  server=catalog("cloud-b");server.items[0].ready=false;
  rerender(<Harness environmentId="cloud-b"/>);
  await screen.findByText("缺少文件");
  await act(async()=>finish(new Response(JSON.stringify(catalog()))));
  expect(screen.queryByText("文件齐全")).not.toBeInTheDocument();
  expect(screen.getByRole("button",{name:"应用当前工作流文件映射"})).toBeDisabled();
  unmount();
});
it("ignores a late mapping completion after the panel unmounts",async()=>{
  const onMapped=vi.fn();const {unmount}=render(<Harness onMapped={onMapped}/>);
  await screen.findByText("文件齐全");
  let finish!:(response:Response)=>void;
  vi.mocked(fetch).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  fireEvent.click(screen.getByRole("button",{name:"应用当前工作流文件映射"}));
  unmount();await act(async()=>finish(new Response(JSON.stringify({saved:true}))));
  expect(onMapped).not.toHaveBeenCalled();
});
it.each(["unsupported","unavailable","unchecked"])("shows safe service guidance for an empty %s catalog without claiming the selected model is unsupported",async(status)=>{
  server.status=status;server.items=[];server.message="此服务未提供云端模型目录，可继续使用现有工作流检测。";
  render(<Harness/>);
  await screen.findByText(server.message);
  expect(screen.queryByText("当前模型尚未适配云端目录")).not.toBeInTheDocument();
  expect(screen.queryByText("当前模型未列入此云端目录，尚未适配。")).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"应用云端建议参数"})).not.toBeInTheDocument();
});
it("qualifies a stale snapshot's ready files as previous evidence and keeps application disabled",async()=>{
  server.status="stale";server.message="目录或节点能力已过期，请重新刷新。";
  render(<Harness/>);
  await screen.findByText(server.message);
  expect(screen.getByText("上次检查文件齐全，当前未确认")).toBeInTheDocument();
  expect(screen.queryByText("文件齐全")).not.toBeInTheDocument();
  expect(screen.getByRole("button",{name:"应用当前工作流文件映射"})).toBeDisabled();
  expect(screen.getByRole("button",{name:"应用云端建议参数"})).toBeDisabled();
});
it("identifies an explicitly unsupported model item without offering suggestions",async()=>{
  server.items[0].supported=false;
  render(<Harness/>);
  await screen.findByText("当前模型尚未适配云端目录");
  expect(screen.queryByRole("button",{name:"应用云端建议参数"})).not.toBeInTheDocument();
});
