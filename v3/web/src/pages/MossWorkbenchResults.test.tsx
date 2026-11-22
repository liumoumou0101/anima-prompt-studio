import {act, cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {Link, MemoryRouter, Route, Routes} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {MossWorkbenchPage} from "./MossWorkbenchPage";
import {MossGenerationResults} from "../components/MossGenerationResults";
import {GalleryWorkspaceButton} from "../components/GalleryWorkspaceButton";
import {basicWorkflowSchema} from "../lib/workflowParameterSchema";
import {defaultGenerationSettings} from "../lib/generationSettings";
import type {GenerationRunRecord} from "../lib/types";
const MODEL="moss_image_sft_int8", FLOW="v3_moss_image_sft_int8", KEY="moss-workbench-v1";
const profiles=[{id:MODEL,family:"moss",display_name:"MOSS",variant:"moss"}];
const configuration={modelProfile:MODEL,workflow:{id:FLOW,revision:"rev"},baseRecipeId:"custom",
  recipeValues:{width:1024,height:1024,steps:25,cfg:2.5,sampler:"er_sde",scheduler:"simple",seed:"42",batch_size:1},
  parameterOverrides:{},resourceRequirements:[],seedMode:"fixed"};
function task(id:string,state="completed",count=1):GenerationRunRecord{return {id,state,progress:state==="completed"?1:.4,
  status_message:state==="failed"?"云端显存不足":"已就绪",artifact_count:count,source:{model_profile:MODEL,positive_prompt:"一把茶壶",negative_prompt:"文字",settings:{}},
  workflow_profile_id:FLOW,created_at:"2026-11-01T00:00:00Z",error:state==="failed"?{code:"oom",message:"云端显存不足"}:null} as GenerationRunRecord;}
let posts:string[], requests:string[], readCount:number;
beforeEach(()=>{
  localStorage.clear();posts=[];requests=[];readCount=0;
  localStorage.setItem(KEY,JSON.stringify({source:"一把茶壶",negative:"文字",mode:"raw",environment:"cloud",configuration,unconfirmed:[]}));
  vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
    const url=String(input);requests.push(url);if(init?.method==="POST")posts.push(url);
    let result:unknown={items:[]};
    if(url.endsWith("/generation-targets"))result={items:[{remote_profile_id:"cloud",remote_display_name:"测试环境",workflow_profile_id:FLOW,
      compatible_model_profiles:[MODEL],template_revision:"rev",parameter_schema:basicWorkflowSchema(FLOW,"rev")}]};
    else if(url.endsWith("/direct-prompt/runs"))result=task("new-run","queued",0);
    else if(url.endsWith("/generation-runs/new-run"))result=++readCount===1?task("new-run","running",0):task("new-run");
    else if(url.endsWith("/generation-runs/new-run/artifacts"))result={items:[{id:"picture",path:"out.png",thumbnail_url:"/thumb.png",content_url:"/original.png",removed:false}]};
    return new Response(JSON.stringify(result));
  });
});
afterEach(()=>{cleanup();vi.restoreAllMocks();});
function mount(){return render(<MemoryRouter><MossWorkbenchPage modelProfiles={profiles} remoteEnabled/></MemoryRouter>);}
it("previews a direct result in the workbench, opens the original and restores the selected result after reload",async()=>{
  const view=mount();
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"生成图像"}));
  expect(await screen.findByRole("tab",{name:"生成结果"})).toHaveAttribute("aria-selected","true");
  expect(await screen.findByAltText("MOSS 生成结果 1",{}, {timeout:4000})).toHaveAttribute("src","/original.png");
  fireEvent.click(screen.getByRole("button",{name:"放大结果图片 1"}));
  expect(await screen.findByRole("dialog")).toBeVisible();
  fireEvent.keyDown(document,{key:"Escape"});
  const count=posts.length;view.unmount();mount();
  expect(await screen.findByAltText("MOSS 生成结果 1")).toBeVisible();
  expect(posts).toHaveLength(count);
});
it("shows a failed task's error in the result pane",async()=>{
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({items:[]})));
  const original=vi.mocked(fetch).getMockImplementation()!;
  localStorage.setItem(KEY,JSON.stringify({source:"一把茶壶",negative:"",mode:"raw",environment:"cloud",configuration,unconfirmed:[],lastRunId:"failed-run"}));
  vi.mocked(fetch).mockImplementation(async(input,init)=>String(input).endsWith("/generation-runs/failed-run")
    ?new Response(JSON.stringify(task("failed-run","failed",0))):original(input,init));
  mount();expect(await screen.findByText("云端显存不足")).toBeVisible();
});
it("recovers only recent MOSS results for an older standalone draft",async()=>{
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const url=String(input);
    if(url==="/api/v3/generation-runs?limit=30")return new Response(JSON.stringify({items:[{...task("anima"),source:{model_profile:"anima_base_v1"}},task("new-run")]}));
    return original(input,init);
  });
  mount();expect(await screen.findByAltText("MOSS 生成结果 1",{}, {timeout:4000})).toBeVisible();
  expect(requests).not.toContain("/api/v3/generation-runs/anima");
  expect(posts).toEqual([]);
});

it("rechecks a completed task while its images are still being registered",async()=>{
  let count=0;
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>String(input).endsWith("/generation-runs/new-run")
    ?new Response(JSON.stringify(task("new-run","completed",++count===1?0:1))):original(input,init));
  render(<MemoryRouter><MossGenerationResults runId="new-run"/></MemoryRouter>);
  expect(await screen.findByAltText("MOSS 生成结果 1",{}, {timeout:4000})).toBeVisible();
  expect(count).toBe(2);
});

it("does not display an unrelated task restored from a stale local id",async()=>{
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({...task("other"),workflow_profile_id:"anima_base",source:null})));
  render(<MemoryRouter><MossGenerationResults runId="other"/></MemoryRouter>);
  expect(await screen.findByRole("alert")).toHaveTextContent("没有找到匹配的 MOSS 任务");
  expect(requests.some(url=>url.endsWith("/artifacts"))).toBe(false);
});

it("opens a matching workspace source image and previews an automatically routed submission",async()=>{
  const schema=basicWorkflowSchema(FLOW,"rev");
  const record={id:"workspace_moss",title:"茶壶",revision:1,draft:{model_profile:MODEL,mode:"faithful",compiled:{positive:"茶壶",negative:"文字",source:"user",compiled_token:"token"},
    generation_settings:{...defaultGenerationSettings(),...configuration.recipeValues,workflow_profile_id:FLOW,parameter_schema:schema,
      execution_policy:{mode:"auto",preferredEnvironmentIds:["cloud"]},creation_configuration:configuration},
    generation_source:{run_id:"source-run",model_profile:MODEL,workflow_profile_id:FLOW,remote_profile_id:"cloud"}}};
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const url=String(input);
    if(init?.method==="POST")posts.push(url);
    if(url==="/api/v3/workspaces/workspace_moss")return new Response(JSON.stringify(record));
    if(url.endsWith("/generation-intents"))return new Response(JSON.stringify({id:"intent",state:"accepted",response:task("auto-run","queued",0),run_id:"auto-run",candidate_progress:{checked:{}}}));
    if(url.endsWith("/generation-runs/source-run") || url.endsWith("/generation-runs/auto-run"))return new Response(JSON.stringify(task(url.endsWith("/auto-run")?"auto-run":"source-run")));
    if(url.endsWith("/artifacts"))return new Response(JSON.stringify({items:[{id:url,path:"result.png",removed:false,content_url:url.includes("source-run")?"/source-original.png":"/auto-original.png",thumbnail_url:url.includes("source-run")?"/source.png":"/auto.png"}]}));
    return original(input,init);
  });
  render(<MemoryRouter initialEntries={["/moss?workspace=workspace_moss"]}><MossWorkbenchPage modelProfiles={profiles} remoteEnabled/></MemoryRouter>);
  expect(await screen.findByAltText("MOSS 生成结果 1")).toHaveAttribute("src","/source-original.png");
  expect(posts).toEqual([]);
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"生成图像"}));
  await waitFor(()=>expect(screen.getByAltText("MOSS 生成结果 1")).toHaveAttribute("src","/auto-original.png"));
  expect(posts.filter(url=>url.endsWith("/generation-intents"))).toHaveLength(1);
});

it("opens the selected gallery image and its exact parameters on each MOSS transfer",async()=>{
  const original=vi.mocked(fetch).getMockImplementation()!;
  const records=[
    {id:"workspace_a",path:"batch-a/04.png",width:896,height:1152,steps:50,seed:"7022100410040317100"},
    {id:"workspace_b",path:"batch-b/03.png",width:1024,height:1024,steps:45,seed:"7122526663535432030"},
  ].map(({id,path,width,height,steps,seed})=>{
    const values={...configuration.recipeValues,width,height,steps,seed,batch_size:4};
    return {id,title:`来自 ${path}`,revision:1,draft:{model_profile:MODEL,mode:"faithful",
      compiled:{positive:`来源 ${path}`,negative:"文字",source:"user",compiled_token:id},
      generation_settings:{...defaultGenerationSettings(),...values,workflow_profile_id:FLOW,
        parameter_schema:basicWorkflowSchema(FLOW,"rev"),creation_configuration:{...configuration,parameterOverrides:values}},
      generation_source:{run_id:"run-"+id,model_profile:MODEL,workflow_profile_id:FLOW,remote_profile_id:"cloud"},
      gallery_source:{path,name:path.split("/").at(-1),mode:"generation"}}};
  });
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const url=String(input);
    if(url.endsWith("/gallery/assets/workspace")){
      const {path}=JSON.parse(String(init?.body));
      return Response.json(records.find(record=>record.draft.gallery_source.path===path));
    }
    const record=records.find(item=>url===`/api/v3/workspaces/${item.id}`);
    return record?Response.json(record):original(input,init);
  });
  render(<MemoryRouter initialEntries={["/gallery/0"]}><Link to="/gallery/1">打开另一张图片</Link><Routes>
    {records.map((record,index)=><Route key={record.id} path={`/gallery/${index}`} element={<GalleryWorkspaceButton
      key={record.id} path={record.draft.gallery_source.path} hasPrompt disabled={false}/>}/>)}
    <Route path="/moss" element={<MossWorkbenchPage modelProfiles={profiles} remoteEnabled/>}/>
  </Routes></MemoryRouter>);
  for(const [index,record] of records.entries()){
    if(index)fireEvent.click(screen.getByRole("link",{name:"打开另一张图片"}));
    fireEvent.click(screen.getByRole("button",{name:"转入工作台"}));
    const source=record.draft.gallery_source;
    expect(await screen.findByRole("img",{name:source.name})).toHaveAttribute("src",`/api/v3/gallery/assets/content?path=${encodeURIComponent(source.path)}`);
    expect(screen.getByLabelText("原文")).toHaveValue(record.draft.compiled.positive);
    fireEvent.click(screen.getByRole("button",{name:/^生成参数/}));
    const values=record.draft.generation_settings;
    for(const [label,value] of [["宽度",values.width],["高度",values.height],["Steps",values.steps],["Seed",values.seed],["张数",values.batch_size]])
      expect(screen.getByLabelText(String(label),{exact:true})).toHaveValue(String(value));
    fireEvent.click(screen.getByRole("button",{name:"返回提示词"}));
  }
  expect(posts.some(url=>/\/(generation-intents|direct-prompt\/runs)$/.test(url))).toBe(false);
});

it("uses the new workspace source instead of a result id saved against an older revision",async()=>{
  localStorage.setItem(`${KEY}:workspace:workspace_moss`,JSON.stringify({workspaceRevision:1,lastRunId:"old-run",source:"旧茶壶",negative:"",mode:"raw",configuration,unconfirmed:[]}));
  const record={id:"workspace_moss",title:"新的来源",revision:2,draft:{model_profile:MODEL,mode:"faithful",
    compiled:{positive:"新茶壶",negative:"文字",source:"user",compiled_token:"new-token"},
    generation_settings:{...defaultGenerationSettings(),...configuration.recipeValues,workflow_profile_id:FLOW,
      parameter_schema:basicWorkflowSchema(FLOW,"rev"),creation_configuration:configuration},
    generation_source:{run_id:"new-run",model_profile:MODEL,workflow_profile_id:FLOW,remote_profile_id:"cloud"}}};
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const url=String(input);
    if(url==="/api/v3/workspaces/workspace_moss")return new Response(JSON.stringify(record));
    return original(input,init);
  });
  render(<MemoryRouter initialEntries={["/moss?workspace=workspace_moss"]}><MossWorkbenchPage modelProfiles={profiles} remoteEnabled/></MemoryRouter>);
  expect(await screen.findByAltText("MOSS 生成结果 1",{}, {timeout:4000})).toHaveAttribute("src","/original.png");
  expect(screen.getByLabelText("原文")).toHaveValue("新茶壶");
  expect(requests).not.toContain("/api/v3/generation-runs/old-run");
  expect(posts).toEqual([]);
});

it("ignores the late response from a previously selected task",async()=>{
  let release!:(value:Response)=>void;
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>String(input).endsWith("/generation-runs/old-run")
    ?new Promise(resolve=>{release=resolve;}):original(input,init));
  const view=render(<MemoryRouter><MossGenerationResults runId="old-run"/></MemoryRouter>);
  await waitFor(()=>expect(release).toBeTypeOf("function"));
  view.rerender(<MemoryRouter><MossGenerationResults runId="new-run"/></MemoryRouter>);
  expect(await screen.findByAltText("MOSS 生成结果 1",{}, {timeout:4000})).toHaveAttribute("src","/original.png");
  await act(async()=>release(new Response(JSON.stringify(task("old-run")))));
  expect(screen.getByAltText("MOSS 生成结果 1")).toHaveAttribute("src","/original.png");
  expect(requests).not.toContain("/api/v3/generation-runs/old-run/artifacts");
});

it("stops task polling when the results pane is unmounted",async()=>{
  let reads=0;
  vi.mocked(fetch).mockImplementation(async()=>{reads++;return new Response(JSON.stringify(task("new-run","running",0)));});
  const view=render(<MemoryRouter><MossGenerationResults runId="new-run"/></MemoryRouter>);
  await screen.findByRole("progressbar",{name:"生成进度"});
  view.unmount();
  await act(()=>new Promise(resolve=>setTimeout(resolve,1600)));
  expect(reads).toBe(1);
});

function resultPictures(count:number,prefix="batch") {
  return Array.from({length:count},(_,index)=>({id:`${prefix}-${index+1}`,path:`${index+1}.png`,removed:false,
    thumbnail_url:`/${prefix}-${index+1}-thumb.png`,content_url:`/${prefix}-${index+1}-original.png`}));
}

it("shows one large batch image at a time and opens the selected original in the full batch viewer",async()=>{
  vi.mocked(fetch).mockImplementation(async input=>new Response(JSON.stringify(String(input).endsWith("/artifacts")
    ?{items:resultPictures(3)}:task("batch-run","completed",3))));
  render(<MemoryRouter><MossGenerationResults runId="batch-run"/></MemoryRouter>);
  expect(await screen.findByAltText("MOSS 生成结果 1")).toHaveAttribute("src","/batch-1-original.png");
  expect(screen.getAllByRole("img")).toHaveLength(1);
  expect(screen.getByText("第 1 张 / 共 3 张")).toBeVisible();
  expect(screen.getByRole("button",{name:"上一张"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"下一张"}));
  expect(screen.queryByAltText("MOSS 生成结果 1")).not.toBeInTheDocument();
  expect(screen.getByAltText("MOSS 生成结果 2")).toHaveAttribute("src","/batch-2-original.png");
  fireEvent.click(screen.getByRole("button",{name:"放大结果图片 2"}));
  expect(await screen.findByRole("dialog")).toBeVisible();
  expect(screen.getByText("2 / 3 · MOSS 生成结果 2")).toBeVisible();
  fireEvent.click(screen.getByRole("button",{name:"图片信息"}));
  expect(screen.getByRole("link",{name:"在新标签页打开原图"})).toHaveAttribute("href","/batch-2-original.png");
  fireEvent.click(screen.getByRole("button",{name:"关闭预览"}));
  await waitFor(()=>expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole("button",{name:"下一张"}));
  expect(screen.getByAltText("MOSS 生成结果 3")).toBeVisible();
  expect(screen.getByText("第 3 张 / 共 3 张")).toBeVisible();
  expect(screen.getByRole("button",{name:"下一张"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"上一张"}));
  expect(screen.getByAltText("MOSS 生成结果 2")).toBeVisible();
});

it("resets batch selection for a new task and hides navigation for a single result",async()=>{
  vi.mocked(fetch).mockImplementation(async input=>{
    const url=String(input), single=url.includes("single-run"), id=single?"single-run":url.includes("next-run")?"next-run":"batch-run";
    return new Response(JSON.stringify(url.endsWith("/artifacts")
      ?{items:resultPictures(single?1:3,id).map(picture=>({...picture,content_url:single?null:picture.content_url}))}
      :task(id,"completed",single?1:3)));
  });
  const view=render(<MemoryRouter><MossGenerationResults runId="batch-run"/></MemoryRouter>);
  await screen.findByAltText("MOSS 生成结果 1");
  fireEvent.click(screen.getByRole("button",{name:"下一张"}));
  fireEvent.click(screen.getByRole("button",{name:"下一张"}));
  expect(screen.getByAltText("MOSS 生成结果 3")).toBeVisible();
  view.rerender(<MemoryRouter><MossGenerationResults runId="next-run"/></MemoryRouter>);
  expect(await screen.findByAltText("MOSS 生成结果 1")).toHaveAttribute("src","/next-run-1-original.png");
  expect(screen.getByText("第 1 张 / 共 3 张")).toBeVisible();
  view.rerender(<MemoryRouter><MossGenerationResults runId="single-run"/></MemoryRouter>);
  expect(await screen.findByAltText("MOSS 生成结果 1")).toHaveAttribute("src","/single-run-1-thumb.png");
  expect(screen.getByRole("button",{name:"放大结果图片 1"})).toBeDisabled();
  expect(screen.queryByRole("button",{name:"上一张"})).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"下一张"})).not.toBeInTheDocument();
  expect(screen.queryByText(/第 .* 张 \/ 共/)).not.toBeInTheDocument();
});

it("keeps the selected image in range when a task's artifact list shrinks",async()=>{
  let reads=0;
  vi.mocked(fetch).mockImplementation(async input=>new Response(JSON.stringify(String(input).endsWith("/artifacts")
    ?{items:resultPictures(reads===1?3:2)}:task("batch-run",++reads===1?"running":"completed",reads===1?3:2))));
  render(<MemoryRouter><MossGenerationResults runId="batch-run"/></MemoryRouter>);
  await screen.findByAltText("MOSS 生成结果 1");
  fireEvent.click(screen.getByRole("button",{name:"下一张"}));
  fireEvent.click(screen.getByRole("button",{name:"下一张"}));
  expect(screen.getByAltText("MOSS 生成结果 3")).toBeVisible();
  expect(await screen.findByText("第 2 张 / 共 2 张",{}, {timeout:3000})).toBeVisible();
  expect(screen.getAllByRole("img")).toHaveLength(1);
  expect(screen.getByAltText("MOSS 生成结果 2")).toBeVisible();
  expect(screen.getByRole("button",{name:"下一张"})).toBeDisabled();
});

it("navigates the entire batch beyond three images in both directions",async()=>{
  vi.mocked(fetch).mockImplementation(async input=>new Response(JSON.stringify(String(input).endsWith("/artifacts")
    ?{items:resultPictures(12)}:task("batch-run","completed",12))));
  render(<MemoryRouter><MossGenerationResults runId="batch-run"/></MemoryRouter>);
  await screen.findByAltText("MOSS 生成结果 1");
  for(let index=1;index<=12;index++) {
    expect(screen.getAllByRole("img")).toHaveLength(1);
    expect(screen.getByAltText(`MOSS 生成结果 ${index}`)).toHaveAttribute("src",`/batch-${index}-original.png`);
    expect(screen.getByText(`第 ${index} 张 / 共 12 张`)).toBeVisible();
    if(index<12)fireEvent.click(screen.getByRole("button",{name:"下一张"}));
  }
  expect(screen.getByRole("button",{name:"下一张"})).toBeDisabled();
  for(let index=11;index>=1;index--) {
    fireEvent.click(screen.getByRole("button",{name:"上一张"}));
    expect(screen.getByAltText(`MOSS 生成结果 ${index}`)).toHaveAttribute("src",`/batch-${index}-original.png`);
    expect(screen.getByText(`第 ${index} 张 / 共 12 张`)).toBeVisible();
  }
  expect(screen.getByRole("button",{name:"上一张"})).toBeDisabled();
});
