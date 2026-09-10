// Public LLM workbench regression tests. Historical concept/candidate UI cases are
// preserved in docs/v3/audits/2026-09-09-conversational-workbench/LEGACY_WORKBENCH_TESTS.tsx.txt.
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {resetDirectImportForTests, storeDirectImport} from "../lib/directPrompt";
import {WorkbenchPage} from "./WorkbenchPage";

const settings = {services: [], current:{service:"",model:""}};
let writes: {url:string; body:Record<string,any>}[];
let saved: Record<string,any> | null;
let saveConflict: boolean;
let modelFailure: boolean;
let targets: Record<string,any>[];

beforeEach(() => {
  localStorage.clear(); sessionStorage.setItem("anima-v3-session","test"); resetDirectImportForTests();
  writes=[]; saved=null; saveConflict=false; modelFailure=false; targets=[];
  vi.spyOn(globalThis,"fetch").mockImplementation(async (input,init) => {
    const url=String(input), body=init?.body ? JSON.parse(String(init.body)) : null;
    if(body) writes.push({url,body});
    if(url.endsWith("/llm/settings")) return new Response(JSON.stringify(settings));
    if(url.endsWith("/workbench/prompt")) return modelFailure
      ? new Response(JSON.stringify({error:{code:"llm_generation_failed",message:"模型暂不可用"}}),{status:502})
      : new Response(JSON.stringify({positive:"a crane beside a pond",negative:body.excluded_text ? "text" : "",warnings:[],rule_id:body.mode}));
    if(url.includes("/workspaces") && body) {
      if(saveConflict) return new Response(JSON.stringify({error:{code:"workspace_revision_conflict",message:"conflict"}}),{status:409});
      saved={id:"workspace_test",title:body.title,draft:body.draft,candidate_snapshot:body.candidate_snapshot,
        revision:(body.revision || 0)+1,created_at:"2026-09-10T00:00:00Z",updated_at:"2026-09-10T00:00:00Z"};
      return new Response(JSON.stringify(saved));
    }
    if(url.endsWith("/workspaces")) return new Response(JSON.stringify({items:saved ? [saved] : []}));
    if(url.endsWith("/generation-targets")) return new Response(JSON.stringify({items:targets}));
    throw new Error(`Unexpected request: ${url}`);
  });
});
afterEach(() => {cleanup();vi.restoreAllMocks();});

function mount(path="/workbench") {
  return render(<MemoryRouter initialEntries={[path]}><WorkbenchPage /></MemoryRouter>);
}
function describe(text="池边的一只白鹤") {
  fireEvent.change(screen.getByLabelText("描述你想生成的画面"),{target:{value:text}});
}
async function compile() {
  fireEvent.click(screen.getByRole("button",{name:"生成提示词（LLM 小助手内核）"}));
  await screen.findByLabelText("最终正向提示词");
}

it("imports unique supermarket tags into the visible description without calling a model",() => {
  mount("/workbench?tag=maid&tag=twintails&tag=maid");
  const text=(screen.getByLabelText("描述你想生成的画面") as HTMLTextAreaElement).value;
  expect(text.match(/maid/g)).toHaveLength(1);
  expect(text).toContain("twintails");
  expect(writes).toEqual([]);
});

it("imports the passthrough Chinese gloss and exclusions without rewriting",() => {
  storeDirectImport({positive_text:"水墨白鹤",excluded_text:"文字",english_positive:"crane",english_negative:"text"});
  mount("/workbench?from=direct");
  expect(screen.getByLabelText("描述你想生成的画面")).toHaveValue("水墨白鹤");
  expect(screen.getByLabelText("明确排除（可选）")).toHaveValue("文字");
  expect(writes).toEqual([]);
});

it("undoes and restores description edits",() => {
  mount(); describe("first"); describe("second");
  fireEvent.click(screen.getByRole("button",{name:"撤销"}));
  expect(screen.getByLabelText("描述你想生成的画面")).toHaveValue("first");
  fireEvent.click(screen.getByRole("button",{name:"恢复"}));
  expect(screen.getByLabelText("描述你想生成的画面")).toHaveValue("second");
});

it("sends explicit source and exclusions to the LLM only after clicking",async () => {
  mount(); describe();
  fireEvent.change(screen.getByLabelText("明确排除（可选）"),{target:{value:"文字"}});
  expect(writes).toEqual([]); await compile();
  expect(writes).toEqual([{url:"/api/v3/workbench/prompt",body:{source_text:"池边的一只白鹤",excluded_text:"文字",mode:"faithful"}}]);
  expect(screen.getByLabelText("最终负向提示词")).toHaveValue("text");
});

it("does not invent a negative prompt and leaves generation disabled offline",async () => {
  mount();describe();await compile();
  expect(screen.getByLabelText("最终负向提示词")).toHaveValue("");
  expect(screen.getByRole("button",{name:"用此提示词远程生图"})).toBeDisabled();
  expect(writes.filter(item => item.url.endsWith("/runs"))).toHaveLength(0);
});

it("keeps source text when the model fails",async () => {
  modelFailure=true; mount();describe();
  fireEvent.click(screen.getByRole("button",{name:"生成提示词（LLM 小助手内核）"}));
  expect(await screen.findByText("模型暂不可用")).toBeInTheDocument();
  expect(screen.getByLabelText("描述你想生成的画面")).toHaveValue("池边的一只白鹤");
  expect(writes).toHaveLength(1);
});

it.each(["描述你想生成的画面","明确排除（可选）"])("marks compiled output stale when %s changes",async label => {
  mount();describe();await compile();
  fireEvent.change(screen.getByLabelText(label),{target:{value:"changed"}});
  expect(screen.getByText(/输入、排除项或处理方式已改变/)).toBeInTheDocument();
  expect(screen.getByLabelText("最终正向提示词")).toHaveValue("a crane beside a pond");
});

it("copies the edited positive prompt",async () => {
  const writeText=vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText}});
  mount();describe();await compile();
  fireEvent.change(screen.getByLabelText("最终正向提示词"),{target:{value:"reviewed crane prompt"}});
  fireEvent.click(screen.getByRole("button",{name:"复制正向提示词"}));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("reviewed crane prompt"));
});

it("saves, restores and updates a workspace with its server revision",async () => {
  mount();describe("saved scene");
  fireEvent.change(screen.getByLabelText("工作台名称"),{target:{value:"我的工作台"}});
  fireEvent.click(screen.getByRole("button",{name:"保存工作台"}));
  await screen.findByText("已保存 revision 1");
  describe("unsaved edit");
  fireEvent.click(screen.getByRole("button",{name:"打开"}));
  fireEvent.click(await screen.findByRole("button",{name:/我的工作台.*r1/}));
  expect(screen.getByLabelText("描述你想生成的画面")).toHaveValue("saved scene");
  describe("updated scene");
  fireEvent.click(screen.getByRole("button",{name:"保存工作台"}));
  await screen.findByText("已保存 revision 2");
  expect(writes.at(-1)?.body.revision).toBe(1);
  expect(writes.at(-1)?.body.draft.natural_text).toBe("updated scene");
});

it("retains unsaved edits after a revision conflict without retrying",async () => {
  mount();describe();fireEvent.click(screen.getByRole("button",{name:"保存工作台"}));
  await screen.findByText("已保存 revision 1");
  saveConflict=true;describe("my local edit");
  fireEvent.click(screen.getByRole("button",{name:"保存工作台"}));
  await screen.findByText(/另一个标签页已更新/);
  expect(screen.getByLabelText("描述你想生成的画面")).toHaveValue("my local edit");
  expect(writes).toHaveLength(2);
});

it.each(["unchecked","stale","connection_failed","invalid_inputs"])("keeps target controls editable when availability is %s",async availability => {
  targets=[{remote_profile_id:"cloud",remote_display_name:"测试云主机",workflow_profile_id:"workflow",workflow_display_name:"测试工作流",
    workflow_kind:"txt2img_basic",compatible_model_profiles:["anima_aesthetic_v1"],host_fingerprint_ready:true,availability,
    default_recipe_id:"stable_baseline",generation_recipes:[{id:"stable_baseline",display_name:"稳定基线",objective:"baseline",
      parameters:{steps:30,cfg:4,sampler:"er_sde",scheduler:"simple"},notes:"test",evidence:"workflow_template"}]}];
  render(<MemoryRouter><WorkbenchPage remoteEnabled /></MemoryRouter>);
  await screen.findByRole("option",{name:/测试工作流/});
  expect(screen.getByLabelText("远程工作流")).toBeEnabled();
  expect(screen.getByLabelText("云主机连接")).toBeEnabled();
  expect(screen.getByLabelText("模型配置")).toBeEnabled();
  expect(writes).toHaveLength(0);
});

it("preserves an existing candidate snapshot when reopening and saving a workspace",async () => {
  const snapshot={intent:{source_text:"雨中的女仆",source_language:"zh",translated_text:"A maid in the rain",scene_plan_en:"A maid in the rain",
    scene_negative_en:[],graph:{elements:[],edges:[]},warnings:[]},candidates:[],validation:{valid:true,candidate_reports:[],issues:[]},
    data_pack_id:"pack-r1",scene_draft:{source_text:"雨中的女仆",translated_text:"A maid in the rain",entities:[],relations:[],
      confirmed:[],exclusions:[],suggestions:[],unresolved:[],risk_notes:[]}};
  saved={id:"workspace_old",title:"旧候选工作台",revision:7,created_at:"2026-09-10",updated_at:"2026-09-10",
    draft:{natural_text:"雨中的女仆",positive_text:"",excluded_text:"",input_mode:"natural",model_profile:"anima_aesthetic_v1"},candidate_snapshot:snapshot};
  mount();fireEvent.click(screen.getByRole("button",{name:"打开"}));
  fireEvent.click(await screen.findByRole("button",{name:/旧候选工作台.*r7/}));
  expect(screen.getByLabelText("描述你想生成的画面")).toHaveValue("雨中的女仆");
  fireEvent.click(screen.getByRole("button",{name:"保存工作台"}));
  await screen.findByText("已保存 revision 8");
  expect(writes.at(-1)?.body.candidate_snapshot).toMatchObject(snapshot);
});
