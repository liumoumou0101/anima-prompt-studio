import {useState} from "react";
import {fireEvent,render,screen} from "@testing-library/react";
import {expect,it,vi} from "vitest";
import {GenerationSettingsPanel} from "./GenerationSettingsPanel";
import {configurationFromSettings,configurationToGenerationPayload,resolveConfiguration} from "../lib/creationConfiguration";
import {defaultGenerationSettings} from "../lib/generationSettings";
import {basicWorkflowSchema} from "../lib/workflowParameterSchema";
import type {GenerationRecipe, RequirementLora} from "../lib/types";
function confirmParameters() {fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));}
function Harness({model="anima"}:{model?:string}) {
  const [configuration,setConfiguration] = useState(configurationFromSettings(defaultGenerationSettings(),model));
  const [pending,setPending] = useState(false);
  const schema = basicWorkflowSchema("flow");
  const resolved=resolveConfiguration(configuration,schema);
  return <><GenerationSettingsPanel configuration={configuration} schema={schema} onChange={setConfiguration} onPendingChange={setPending}/><output aria-label="生成请求">{JSON.stringify(resolved.valid?configurationToGenerationPayload(configuration,schema):resolved)}</output><button disabled={pending||!resolved.valid}>提交测试任务</button></>;
}
it.each(["anima_base_v1","moss_image_sft_int8"])("allows manual random seed entry for %s and keeps incomplete input invalid",model=>{
  render(<Harness model={model}/>);
  const seed=screen.getByLabelText("Seed");
  expect(seed).toBeEnabled();
  fireEvent.change(seed,{target:{value:"-"}});
  expect(seed).toHaveValue("-");
  expect(screen.getByRole("button",{name:"提交测试任务"})).toBeDisabled();
  fireEvent.change(seed,{target:{value:"-1"}});
  fireEvent.blur(seed);
  expect(seed).toHaveValue("-1");
  expect(screen.getByLabelText("种子模式")).toHaveValue("random");
  confirmParameters();
  expect(screen.getByRole("button",{name:"提交测试任务"})).toBeEnabled();
  expect(JSON.parse(screen.getByLabelText("生成请求").textContent!)).toMatchObject({seed:"-1",workflow_parameter_overrides:{seed:"-1"}});
  fireEvent.change(seed,{target:{value:"8798399215689017476"}});
  expect(screen.getByLabelText("种子模式")).toHaveValue("fixed");
  confirmParameters();
  expect(JSON.parse(screen.getByLabelText("生成请求").textContent!).seed).toBe("8798399215689017476");
  fireEvent.change(seed,{target:{value:"-1"}});
  expect(seed).toHaveValue("-1");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
it.each(["-2","-1.5",""])("keeps invalid seed draft %j visible and prevents submission",value=>{
  render(<Harness/>);
  fireEvent.change(screen.getByLabelText("Seed"),{target:{value}});
  expect(screen.getByLabelText("Seed")).toHaveValue(value);
  expect(screen.getByRole("button",{name:"提交测试任务"})).toBeDisabled();
});
it("keeps the random selector and restoring the recommended random seed usable",()=>{
  render(<Harness/>);
  fireEvent.change(screen.getByLabelText("Seed"),{target:{value:"42"}});
  fireEvent.change(screen.getByLabelText("种子模式"),{target:{value:"random"}});
  expect(screen.getByLabelText("Seed")).toHaveValue("-1");
  confirmParameters();
  expect(screen.getByRole("button",{name:"提交测试任务"})).toBeEnabled();
  fireEvent.change(screen.getByLabelText("种子模式"),{target:{value:"fixed"}});
  expect(screen.getByLabelText("Seed")).toHaveValue("42");
  fireEvent.click(screen.getByRole("button",{name:"恢复 Seed"}));
  expect(screen.getByLabelText("Seed")).toHaveValue("-1");
  expect(screen.getByLabelText("种子模式")).toHaveValue("random");
  confirmParameters();
  expect(screen.getByRole("button",{name:"提交测试任务"})).toBeEnabled();
});
it("keeps blank numeric input and reports validation without coercing to zero",()=>{
  render(<Harness/>);
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:""}});
  fireEvent.blur(screen.getByLabelText("Steps"));
  expect(screen.getByLabelText("Steps")).toHaveValue("");
  expect(screen.getByRole("alert")).toHaveTextContent("请输入数值");
});
it("keeps maximum seed as text and supports a single field reset",()=>{
  render(<Harness/>);
  fireEvent.change(screen.getByLabelText("种子模式"),{target:{value:"fixed"}});
  fireEvent.change(screen.getByLabelText("Seed"),{target:{value:"9223372036854775807"}});
  expect(screen.getByLabelText("Seed")).toHaveValue("9223372036854775807");
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:"22"}});
  fireEvent.click(screen.getByRole("button",{name:"恢复 Steps"}));
  expect(screen.getByLabelText("Steps")).toHaveValue("35");
});
it("previews recipe changes without applying until the explicit action",()=>{
  const onChange=vi.fn();
  const configuration=configurationFromSettings({...defaultGenerationSettings(),steps:22,cfg:3.2},"anima");
  const recipes=[{id:"fast",display_name:"快速",parameters:{steps:10,cfg:1,sampler:"euler",scheduler:"normal"}}] as GenerationRecipe[];
  render(<GenerationSettingsPanel configuration={configuration} schema={basicWorkflowSchema("flow")} onChange={onChange} recipes={recipes}/>);
  fireEvent.click(screen.getByText(/^配方：/, {selector:"summary"}));
  fireEvent.change(screen.getByLabelText("推荐配方"),{target:{value:"fast"}});
  expect(screen.getByRole("list",{name:"配方改变项"})).toHaveTextContent("Steps：22 → 10");
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"应用配方"}));
  expect(onChange).not.toHaveBeenCalled();
  confirmParameters();
  expect(onChange).toHaveBeenCalledTimes(1);
  expect(onChange.mock.calls[0][0].baseRecipeId).toBe("fast");
});

it.each(["custom","stable_baseline"])("allows adopting unchanged recipe values to clear carried overrides from %s",baseRecipeId=>{
  const configuration=configurationFromSettings(defaultGenerationSettings(),"anima");
  configuration.baseRecipeId=baseRecipeId;
  configuration.parameterOverrides={steps:35,cfg:4.5,sampler:"euler",scheduler:"normal",width:768,seed:"9223372036854775807"};
  const recipes=[{id:"stable_baseline",display_name:"稳定基线",parameters:{steps:35,cfg:4.5,sampler:"euler",scheduler:"normal"}}] as GenerationRecipe[];
  const onChange=vi.fn();
  render(<GenerationSettingsPanel configuration={configuration} schema={basicWorkflowSchema("flow")} recipes={recipes} onChange={onChange}/>);
  fireEvent.click(screen.getByText(/^配方：/,{selector:"summary"}));
  expect(screen.queryByRole("list",{name:"配方改变项"})).not.toBeInTheDocument();
  expect(screen.getByText("应用后采用所选配方，并清除其中参数的手动覆盖。")).toBeVisible();
  const apply=screen.getByRole("button",{name:"应用配方"});
  expect(apply).toBeEnabled();
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.click(apply);
  expect(onChange).not.toHaveBeenCalled();
  confirmParameters();
  expect(onChange).toHaveBeenCalledTimes(1);
  expect(onChange.mock.calls[0][0]).toMatchObject({baseRecipeId:"stable_baseline",recipeValues:{steps:35,cfg:4.5,sampler:"euler",scheduler:"normal"},parameterOverrides:{width:768,seed:"9223372036854775807"}});
  expect(Object.keys(onChange.mock.calls[0][0].parameterOverrides).sort()).toEqual(["seed","width"]);
  expect(configuration.parameterOverrides.steps).toBe(35);
});

it("allows changing only the recipe identity when its values are already in effect",()=>{
  const configuration=configurationFromSettings(defaultGenerationSettings(),"anima");
  const recipes=[{id:"another",display_name:"另一基线",parameters:{steps:35,cfg:4.5,sampler:"euler",scheduler:"normal"}}] as GenerationRecipe[];
  const onChange=vi.fn();
  render(<GenerationSettingsPanel configuration={configuration} schema={basicWorkflowSchema("flow")} recipes={recipes} onChange={onChange}/>);
  fireEvent.click(screen.getByText(/^配方：/,{selector:"summary"}));
  expect(screen.getByRole("button",{name:"应用配方"})).toBeEnabled();
  fireEvent.click(screen.getByRole("button",{name:"应用配方"}));
  confirmParameters();
  expect(onChange.mock.calls[0][0].baseRecipeId).toBe("another");
});

it("keeps applying an identical recipe disabled when no value or provenance changes",()=>{
  const configuration=configurationFromSettings(defaultGenerationSettings(),"anima");
  const recipes=[{id:"stable_baseline",display_name:"稳定基线",parameters:{steps:35,cfg:4.5,sampler:"euler",scheduler:"normal"}}] as GenerationRecipe[];
  const onChange=vi.fn();
  render(<GenerationSettingsPanel configuration={configuration} schema={basicWorkflowSchema("flow")} recipes={recipes} onChange={onChange}/>);
  fireEvent.click(screen.getByText(/^配方：/,{selector:"summary"}));
  expect(screen.getByRole("button",{name:"应用配方"})).toBeDisabled();
  expect(onChange).not.toHaveBeenCalled();
});

it("shows the current workflow recommendation instead of a carried historical baseline",()=>{
  const schema=basicWorkflowSchema("turbo","v2");
  schema.fields=schema.fields.map(field=>field.key==="steps"?{...field,default:10}:field.key==="cfg"?{...field,default:1}:field);
  const configuration=configurationFromSettings({...defaultGenerationSettings(),steps:42},"anima_turbo_v1_1");
  const recipes=[{id:"preview",display_name:"预览",parameters:{steps:8,cfg:1,sampler:"euler",scheduler:"normal"}},
    {id:"turbo",display_name:"Turbo 基线",parameters:{steps:10,cfg:1,sampler:"euler",scheduler:"normal"}}] as GenerationRecipe[];
  const onChange=vi.fn();
  render(<GenerationSettingsPanel configuration={configuration} schema={schema} recipes={recipes} defaultRecipeId="turbo" onChange={onChange}/>);
  const field=screen.getByLabelText("Steps").closest(".generation-parameter-field")!;
  expect(field).toHaveTextContent("推荐值：10");
  expect(field).not.toHaveTextContent("推荐值：35");
  fireEvent.click(screen.getByRole("button",{name:"恢复 Steps"}));
  expect(onChange).not.toHaveBeenCalled();
  confirmParameters();
  expect(resolveConfiguration(onChange.mock.calls[0][0],schema).values.steps).toBe(10);
  expect(onChange.mock.calls[0][0].parameterOverrides.steps).toBeUndefined();
  expect(configuration.parameterOverrides.steps).toBe(42);
});

it("keeps edits out of the generation payload until confirmation and reports the applied values",()=>{
  render(<Harness/>);
  fireEvent.click(screen.getByRole("button",{name:"方图"}));
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:"22"}});
  expect(screen.getByLabelText("已应用参数")).toHaveTextContent("896 × 1152");
  expect(screen.getByLabelText("已应用参数")).toHaveTextContent("Steps 35");
  expect(JSON.parse(screen.getByLabelText("生成请求").textContent!)).toMatchObject({width:896,height:1152,steps:35});
  expect(screen.getByRole("button",{name:"提交测试任务"})).toBeDisabled();
  confirmParameters();
  expect(JSON.parse(screen.getByLabelText("生成请求").textContent!)).toMatchObject({width:1024,height:1024,steps:22});
  expect(screen.getByLabelText("已应用参数")).toHaveTextContent("1024 × 1024");
  expect(screen.getByText("参数已应用，将用于下一次生成")).toBeVisible();
  expect(screen.getByRole("button",{name:"提交测试任务"})).toBeEnabled();
});

it("discards invalid input without changing applied parameters",()=>{
  render(<Harness/>);
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:""}});
  expect(screen.getByRole("button",{name:"确认应用参数"})).toBeDisabled();
  expect(JSON.parse(screen.getByLabelText("生成请求").textContent!).steps).toBe(35);
  fireEvent.click(screen.getByRole("button",{name:"放弃修改"}));
  expect(screen.getByLabelText("Steps")).toHaveValue("35");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("button",{name:"提交测试任务"})).toBeEnabled();
});

it("validates model-specific dimensions before allowing confirmation",()=>{
  const onChange=vi.fn();
  render(<GenerationSettingsPanel configuration={configurationFromSettings(defaultGenerationSettings(),"moss")} schema={basicWorkflowSchema("flow")}
    onChange={onChange} validateApply={values=>Number(values.width)%16?"宽度必须是 16 的倍数":undefined}/>);
  fireEvent.change(screen.getByLabelText("宽度"),{target:{value:"1001"}});
  expect(screen.getByRole("alert")).toHaveTextContent("宽度必须是 16 的倍数");
  expect(screen.getByRole("button",{name:"确认应用参数"})).toBeDisabled();
  confirmParameters();
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("宽度"),{target:{value:"1024"}});
  confirmParameters();
  expect(onChange.mock.calls[0][0].parameterOverrides.width).toBe(1024);
});

it.each(["baseline","model","workflow","schema"])("clears pending edits when the %s changes",change=>{
  const configuration=configurationFromSettings(defaultGenerationSettings(),"anima");
  const schema=basicWorkflowSchema("flow","v1");
  const onChange=vi.fn(),onPendingChange=vi.fn();
  const {rerender}=render(<GenerationSettingsPanel configuration={configuration} schema={schema} onChange={onChange} onPendingChange={onPendingChange}/>);
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:"22"}});
  expect(onPendingChange).toHaveBeenLastCalledWith(true);
  const next=change==="baseline"?{...configuration,parameterOverrides:{steps:10}}:change==="model"?{...configuration,modelProfile:"turbo"}:change==="workflow"?{...configuration,workflow:{id:"new-flow",revision:"v2"}}:configuration;
  rerender(<GenerationSettingsPanel configuration={next} schema={change==="schema"?{...schema,templateRevision:"v2"}:schema} onChange={onChange} onPendingChange={onPendingChange}/>);
  expect(screen.getByLabelText("Steps")).toHaveValue(change==="baseline"?"10":"35");
  expect(onPendingChange).toHaveBeenLastCalledWith(false);
  expect(screen.getByRole("button",{name:"确认应用参数"})).toBeDisabled();
  expect(screen.getByText("工作流或已应用参数已变化，请重新核对。")).toBeVisible();
  expect(onChange).not.toHaveBeenCalled();
});

it("preserves pending edits across hide/show and new LoRA resources, then applies with the latest resources",()=>{
  const configuration=configurationFromSettings(defaultGenerationSettings(),"anima");
  const schema=basicWorkflowSchema("flow");
  const onChange=vi.fn(),onPendingChange=vi.fn();
  const {rerender}=render(<div><GenerationSettingsPanel configuration={configuration} schema={schema} onChange={onChange} onPendingChange={onPendingChange}/></div>);
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:"22"}});
  const lora:RequirementLora={logical_id:"new",file_name:"new.safetensors",weight:0.8,trigger_words:[],required:true,source:{kind:"user"}};
  const next={...configuration,resourceRequirements:[lora]};
  rerender(<div hidden><GenerationSettingsPanel configuration={next} schema={schema} onChange={onChange} onPendingChange={onPendingChange}/></div>);
  expect(onPendingChange).toHaveBeenLastCalledWith(true);
  rerender(<div><GenerationSettingsPanel configuration={next} schema={schema} onChange={onChange} onPendingChange={onPendingChange}/></div>);
  expect(screen.getByLabelText("Steps")).toHaveValue("22");
  confirmParameters();
  expect(onChange.mock.calls[0][0]).toMatchObject({parameterOverrides:{steps:22},resourceRequirements:[lora]});
  expect(onPendingChange).toHaveBeenLastCalledWith(false);
});

it("clears the pending notification on unmount",()=>{
  const onPendingChange=vi.fn();
  const {unmount}=render(<GenerationSettingsPanel configuration={configurationFromSettings(defaultGenerationSettings(),"anima")} schema={basicWorkflowSchema("flow")} onChange={vi.fn()} onPendingChange={onPendingChange}/>);
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:"22"}});
  expect(onPendingChange).toHaveBeenLastCalledWith(true);
  unmount();
  expect(onPendingChange).toHaveBeenLastCalledWith(false);
});

it("resets a field to the locally selected recipe before confirmation",()=>{
  const onChange=vi.fn();
  const recipes=[{id:"stable_baseline",display_name:"稳定基线",parameters:{steps:35,cfg:4.5,sampler:"euler",scheduler:"normal"}},
    {id:"fast",display_name:"快速",parameters:{steps:10,cfg:1,sampler:"euler",scheduler:"normal"}}] as GenerationRecipe[];
  render(<GenerationSettingsPanel configuration={configurationFromSettings(defaultGenerationSettings(),"anima")} schema={basicWorkflowSchema("flow")} recipes={recipes} onChange={onChange}/>);
  fireEvent.click(screen.getByText(/^配方：/,{selector:"summary"}));
  fireEvent.change(screen.getByLabelText("推荐配方"),{target:{value:"fast"}});
  fireEvent.click(screen.getByRole("button",{name:"应用配方"}));
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:"12"}});
  fireEvent.click(screen.getByRole("button",{name:"恢复 Steps"}));
  expect(screen.getByLabelText("Steps")).toHaveValue("10");
  expect(onChange).not.toHaveBeenCalled();
  confirmParameters();
  expect(onChange.mock.calls[0][0]).toMatchObject({baseRecipeId:"fast",recipeValues:{steps:10},parameterOverrides:{}});
});

it("keeps pending edits across equivalent props and disables applying or discarding while busy",()=>{
  const configuration=configurationFromSettings(defaultGenerationSettings(),"anima");
  const onChange=vi.fn(),onPendingChange=vi.fn();
  const {rerender}=render(<GenerationSettingsPanel configuration={configuration} schema={basicWorkflowSchema("flow")} onChange={onChange} onPendingChange={onPendingChange}/>);
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:"22"}});
  rerender(<GenerationSettingsPanel configuration={structuredClone(configuration)} schema={basicWorkflowSchema("flow")} onChange={onChange} onPendingChange={onPendingChange} disabled/>);
  expect(screen.getByLabelText("Steps")).toHaveValue("22");
  expect(screen.getByLabelText("Steps")).toBeDisabled();
  expect(screen.getByRole("button",{name:"确认应用参数"})).toBeDisabled();
  expect(screen.getByRole("button",{name:"放弃修改"})).toBeDisabled();
  confirmParameters();
  fireEvent.click(screen.getByRole("button",{name:"放弃修改"}));
  expect(onChange).not.toHaveBeenCalled();
  expect(onPendingChange).toHaveBeenLastCalledWith(true);
});

it("reports success only after the applied props reflect confirmation and removes it for a different baseline",()=>{
  const configuration=configurationFromSettings(defaultGenerationSettings(),"anima");
  const schema=basicWorkflowSchema("flow"),onChange=vi.fn();
  const {rerender}=render(<GenerationSettingsPanel configuration={configuration} schema={schema} onChange={onChange}/>);
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:"22"}});
  confirmParameters();
  expect(screen.queryByText("参数已应用，将用于下一次生成")).not.toBeInTheDocument();
  const confirmed=onChange.mock.calls[0][0];
  rerender(<GenerationSettingsPanel configuration={confirmed} schema={schema} onChange={onChange}/>);
  expect(screen.getByText("参数已应用，将用于下一次生成")).toBeVisible();
  rerender(<GenerationSettingsPanel configuration={configuration} schema={schema} onChange={onChange}/>);
  expect(screen.queryByText("参数已应用，将用于下一次生成")).not.toBeInTheDocument();
});

it("requires a nonnegative seed after selecting fixed mode, including subsequent parameter edits",()=>{
  const onChange=vi.fn();
  render(<GenerationSettingsPanel configuration={configurationFromSettings(defaultGenerationSettings(),"anima")} schema={basicWorkflowSchema("flow")} onChange={onChange}/>);
  fireEvent.change(screen.getByLabelText("种子模式"),{target:{value:"fixed"}});
  expect(screen.getByLabelText("Seed")).toHaveValue("-1");
  expect(screen.getByRole("button",{name:"确认应用参数"})).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:"22"}});
  expect(screen.getByLabelText("Seed")).toHaveAttribute("aria-invalid","true");
  confirmParameters();
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Seed"),{target:{value:"0"}});
  confirmParameters();
  expect(onChange.mock.calls[0][0]).toMatchObject({seedMode:"fixed",parameterOverrides:{steps:22,seed:"0"}});
});

it("preserves a loaded legacy fixed random seed until the user explicitly reselects fixed mode",()=>{
  const configuration={...configurationFromSettings(defaultGenerationSettings(),"anima"),seedMode:"fixed" as const};
  const onChange=vi.fn();
  render(<GenerationSettingsPanel configuration={configuration} schema={basicWorkflowSchema("flow")} onChange={onChange}/>);
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:"22"}});
  confirmParameters();
  expect(onChange.mock.calls[0][0]).toMatchObject({seedMode:"fixed",parameterOverrides:{steps:22}});
  fireEvent.change(screen.getByLabelText("种子模式"),{target:{value:"random"}});
  fireEvent.change(screen.getByLabelText("种子模式"),{target:{value:"fixed"}});
  expect(screen.getByRole("button",{name:"确认应用参数"})).toBeDisabled();
  expect(screen.getByRole("button",{name:"放弃修改"})).toBeEnabled();
  expect(screen.getByLabelText("Seed")).toHaveAttribute("aria-invalid","true");
  fireEvent.click(screen.getByRole("button",{name:"放弃修改"}));
  expect(screen.getByLabelText("Seed")).toHaveAttribute("aria-invalid","false");
});

it("resynchronizes the recipe picker on model or workflow change without applying it",()=>{
  const onChange=vi.fn();
  const first=configurationFromSettings(defaultGenerationSettings(),"base");
  const base=[{id:"stable_baseline",display_name:"普通基线",parameters:{steps:35,cfg:4.5,sampler:"euler",scheduler:"normal"}}] as GenerationRecipe[];
  const {rerender}=render(<GenerationSettingsPanel configuration={first} schema={basicWorkflowSchema("base")} recipes={base} defaultRecipeId="stable_baseline" onChange={onChange}/>);
  const next={...first,modelProfile:"turbo",workflow:{id:"turbo",revision:"v1"}};
  const recipes=[{id:"preview",display_name:"预览",parameters:{steps:8,cfg:1,sampler:"euler",scheduler:"normal"}},
    {id:"turbo",display_name:"Turbo 基线",parameters:{steps:10,cfg:1,sampler:"euler",scheduler:"normal"}}] as GenerationRecipe[];
  rerender(<GenerationSettingsPanel configuration={next} schema={basicWorkflowSchema("turbo","v1")} recipes={recipes} defaultRecipeId="turbo" onChange={onChange}/>);
  expect(screen.getByLabelText("推荐配方")).toHaveValue("turbo");
  expect(screen.getByRole("list",{name:"配方改变项"})).toHaveTextContent("Steps：35 → 10");
  expect(onChange).not.toHaveBeenCalled();
});
