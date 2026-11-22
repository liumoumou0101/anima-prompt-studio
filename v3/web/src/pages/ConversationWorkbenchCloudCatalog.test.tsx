import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, expect, it, vi} from "vitest";
import {ConversationWorkbenchPage} from "./ConversationWorkbenchPage";
import {emptyRequirements, type ConversationRecord} from "../lib/conversation";
import {defaultGenerationSettings} from "../lib/generationSettings";
import {basicWorkflowSchema} from "../lib/workflowParameterSchema";
import {readConversationDraft} from "../lib/conversationDrafts";
import type {GenerationTarget} from "../lib/types";

afterEach(()=>{cleanup();vi.restoreAllMocks();});
it("uses bootstrap models and applies suggestions through the workbench draft while refresh preserves all creative edits",async()=>{
  localStorage.clear();sessionStorage.clear();sessionStorage.setItem("anima-v3-session","test");
  const schema=basicWorkflowSchema("v3_wai_anima_v1_0","rev1");
  schema.fields.find(field=>field.key==="sampler")!.enum=["euler","dpmpp_2m"];
  schema.fields.find(field=>field.key==="scheduler")!.enum=["normal","karras"];
  const settings={...defaultGenerationSettings(),aspect:"custom" as const,width:768,height:1024,steps:22,cfg:3,seed:"9223372036854775807",batch_size:2,
    workflow_profile_id:"v3_wai_anima_v1_0",execution_policy:{mode:"pinned" as const,environmentId:"cloud-a"}};
  const workspace:ConversationRecord={id:"cloud-workspace",title:"云端模型测试",revision:1,created_at:"2026-10-27",updated_at:"2026-10-27",draft:{positive_text:"",excluded_text:"",model_profile:"wai_anima_v1_0",mode:"faithful",
    requirements:{...emptyRequirements(),contract:"anima-requirements/1",revision:1},generation_settings:settings,compiled:{positive:"cat in blue",negative:"blur",compiled_token:"token",source:"user"},compile_state:"fresh",conversation_events:[]}};
  localStorage.setItem("anima-conversation-active",JSON.stringify(workspace.id));
  const target:GenerationTarget={remote_profile_id:"cloud-a",remote_display_name:"测试云端",connection_type:"http",remote_http_base_url:"https://cloud.example.test",remote_comfy_host:"127.0.0.1",workflow_profile_id:"v3_wai_anima_v1_0",workflow_display_name:"WAI 工作流",workflow_kind:"text_to_image",template_revision:"rev1",parameter_schema:schema,
    compatible_model_profiles:["wai_anima_v1_0"],host_fingerprint_ready:true,auth_type:"agent",private_key_passphrase_configured:false};
  const writes:{url:string;body:any}[]=[];
  vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
    const url=String(input),body=init?.body?JSON.parse(String(init.body)):null;
    if(body)writes.push({url,body});
    let response:unknown={items:[]};
    if(url.endsWith("/generation-targets"))response={items:[target]};
    else if(url.endsWith("/llm/settings"))response={current:{service:"test",model:"small",thinking:{mode:"switchable",message:""}},services:[]};
    else if(url.includes("/model-catalog"))response={remote_profile_id:"cloud-a",session_id:"session",environment_epoch:1,status:"ready",checked_at:1720000000,runtime_id:"runtime",message:"",items:[{id:"wai_anima_v1_0",display_name:"WAI Anima",family:"anima",supported:true,ready:true,selected_for_startup:true,suggested_defaults:{steps:28,cfg:5,sampler:"dpmpp_2m",scheduler:"karras"},assets:[],workflow_mappings:[]}]};
    else if(url.includes("/workspaces?"))response={items:[workspace]};
    else if(url.endsWith("/proposal"))response={proposal:null};
    else if(url.endsWith(`/workspaces/${workspace.id}`))response=workspace;
    else if(url.endsWith("/editor-context"))response={token:"context"};
    return new Response(JSON.stringify(response));
  });
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled modelProfiles={[{id:"wai_anima_v1_0",display_name:"WAI registered",variant:"community"}]}/></MemoryRouter>);
  await screen.findByLabelText("正向提示词");
  fireEvent.click(screen.getByRole("button",{name:"生成参数"}));
  await screen.findByText("文件齐全");
  expect(screen.getByRole("option",{name:"测试云端 · https://cloud.example.test"})).toBeInTheDocument();
  expect(screen.getByLabelText("模型")).toHaveValue("wai_anima_v1_0");
  expect(screen.getByLabelText("模型").querySelectorAll("option")).toHaveLength(1);
  fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"edited cat in green"}});
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:"19"}});
  fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
  fireEvent.click(screen.getByRole("button",{name:"刷新云端目录"}));
  await waitFor(()=>expect(screen.getByRole("button",{name:"刷新云端目录"})).toBeEnabled());
  expect(screen.getByLabelText("Steps")).toHaveValue("19");
  expect(screen.getByLabelText("正向提示词")).toHaveValue("edited cat in green");
  fireEvent.click(screen.getByRole("button",{name:"应用云端建议参数"}));
  await waitFor(()=>expect(readConversationDraft(workspace.id)?.local?.settings.steps).toBe(28));
  const draft=readConversationDraft(workspace.id)!.local!;
  expect(draft.settings).toMatchObject({width:768,height:1024,seed:"9223372036854775807",batch_size:2,steps:28,cfg:5,sampler:"dpmpp_2m",scheduler:"karras"});
  expect(draft.positive).toBe("edited cat in green");expect(draft.negative).toBe("blur");
  expect(draft.model).toBe("wai_anima_v1_0");
  expect(writes.filter(write=>write.url.endsWith(`/workspaces/${workspace.id}`))).toHaveLength(0);
});
