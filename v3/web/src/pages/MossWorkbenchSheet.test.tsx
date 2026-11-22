import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MossWorkbenchPage } from "./MossWorkbenchPage";

const original = "少女手持写着“春天”的卡片";
const negative = "不要水印，保留画面内的“春天”";
const suggestion = {
  positive: "少女手持写着“春天”的卡片，柔和光线",
  negative: "辅助服务返回的排除内容，不应替换草稿",
  changes: ["整理顺序"],
  warnings: [],
  mode: "polish",
  engine: "test",
};
const profiles = [{ id: "moss_image_sft_int8", family: "moss", display_name: "MOSS INT8", variant: "moss" }];
let requests: { url: string; body: any }[];
let dialogMethods: { name: string; descriptor?: PropertyDescriptor }[];

beforeEach(() => {
  localStorage.clear();
  requests = [];
  // Match the shared Sheet tests: jsdom needs the native dialog lifecycle.
  dialogMethods = ["showModal", "close"].map(name => ({ name, descriptor: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, name) }));
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, writable: true, value: function (this: HTMLDialogElement) { this.open = true; } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, writable: true, value: function (this: HTMLDialogElement) {
    if (!this.open) return;
    this.open = false;
    this.dispatchEvent(new Event("close"));
  } });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url, options) => {
    const path = String(url);
    requests.push({ url: path, body: options?.body ? JSON.parse(String(options.body)) : null });
    if (path.endsWith("/generation-targets")) return new Response(JSON.stringify({ items: [{
      remote_profile_id: "cloud", remote_display_name: "测试云",
      workflow_profile_id: "v3_moss_image_sft_int8", workflow_display_name: "MOSS",
      compatible_model_profiles: ["moss_image_sft_int8"], template_revision: "rev-1",
    }] }));
    if (path.includes("prompt-assist")) return new Response(JSON.stringify(suggestion));
    if (path.endsWith("/direct-prompt/runs")) return new Response(JSON.stringify({ id: "moss-sheet-run", state: "draft", status_message: "已接受" }));
    return new Response(JSON.stringify({ status: "unavailable", items: [] }));
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  document.body.style.removeProperty("overflow");
  dialogMethods.forEach(({ name, descriptor }) => {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name);
  });
});

function mount() {
  return render(<MemoryRouter><MossWorkbenchPage modelProfiles={profiles} remoteEnabled /></MemoryRouter>);
}

function enterDraft() {
  fireEvent.change(screen.getByRole("textbox", { name: "原文" }), { target: { value: original } });
  editNegative(negative);
}

function editNegative(value: string) {
  const toggle = screen.getByRole("button", { name: /负向提示词（可选）/ });
  if (toggle.getAttribute("aria-expanded") !== "true") fireEvent.click(toggle);
  fireEvent.change(screen.getByRole("textbox", { name: "负向提示词" }), { target: { value } });
}

async function reviewSuggestion(mode = "只整理润色") {
  fireEvent.click(screen.getByLabelText(mode));
  fireEvent.click(screen.getByRole("button", { name: "获取建议" }));
  const dialog = await screen.findByRole("dialog", { name: "创作辅助" });
  await waitFor(() => expect(within(dialog).getByRole("tab", { name: "辅助建议" })).toHaveAttribute("aria-selected", "true"));
  await within(dialog).findByRole("textbox", { name: "建议文本" });
  return dialog;
}

function generationRequests() {
  return requests.filter(request => request.url.endsWith("/direct-prompt/runs") || request.url.endsWith("/generation-intents"));
}

it("keeps parameter edits pending across Sheet closes and submits only the confirmed values after reload", async () => {
  let view = mount();
  enterDraft();
  await screen.findByRole("option", { name: "测试云" });
  fireEvent.change(screen.getByRole("combobox", { name: "执行环境" }), { target: { value: "cloud" } });
  const savedConfiguration = JSON.parse(localStorage.getItem("moss-workbench-v1")!).configuration;
  fireEvent.click(screen.getByRole("button", { name: /^生成参数/ }));
  fireEvent.change(screen.getByLabelText("Steps", { exact: true }), { target: { value: "37" } });
  fireEvent.change(screen.getByLabelText("CFG", { exact: true }), { target: { value: "3.1" } });
  fireEvent.change(screen.getByLabelText("宽度", { exact: true }), { target: { value: "768" } });
  fireEvent.change(screen.getByLabelText("Seed", { exact: true }), { target: { value: "8798399215689017476" } });
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).configuration).toEqual(savedConfiguration);
  expect(view.container.querySelector(".moss-condition-summary")).toHaveTextContent("1024 × 1024 · 1 张 · 25 步 · CFG 2.5");
  expect(screen.getByRole("button", { name: "生成图像" })).toBeDisabled();
  expect(screen.getByLabelText("本次出图文本", { exact: true })).toHaveValue(original);
  fireEvent.click(screen.getByRole("button", { name: "关闭辅助设置" }));
  expect(screen.getByText("生成参数有修改待确认")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "确认生成参数" }));
  expect(screen.getByRole("tab", { name: "生成参数" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByLabelText("Steps", { exact: true })).toHaveValue("37");
  expect(screen.getByLabelText("Seed", { exact: true })).toHaveValue("8798399215689017476");
  const writesBeforeConfirmation = requests.filter(request => request.body !== null);
  fireEvent.click(screen.getByRole("button", { name: "确认应用参数" }));
  expect(screen.getByRole("button", { name: "生成图像" })).toBeEnabled();
  expect(view.container.querySelector(".moss-condition-summary")).toHaveTextContent("768 × 1024 · 1 张 · 37 步 · CFG 3.1");
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).configuration).toMatchObject({
    seedMode: "fixed", parameterOverrides: { steps: 37, cfg: 3.1, width: 768, seed: "8798399215689017476" },
  });
  expect(generationRequests()).toEqual([]);
  expect(requests.filter(request => request.body !== null)).toEqual(writesBeforeConfirmation);

  view.unmount();
  view = mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "生成图像" })).toBeEnabled());
  expect(screen.queryByRole("button", { name: "确认生成参数" })).toBeNull();
  expect(view.container.querySelector(".moss-condition-summary")).toHaveTextContent("768 × 1024 · 1 张 · 37 步 · CFG 3.1");
  fireEvent.click(screen.getByRole("button", { name: "生成图像" }));
  await waitFor(() => expect(generationRequests()).toHaveLength(1));
  expect(generationRequests()[0].body).toMatchObject({positive_prompt: original, negative_prompt: negative,
    settings: {width: 768, height: 1024, steps: 37, cfg: 3.1, seed: "8798399215689017476",
      workflow_parameter_overrides: {width: 768, height: 1024, steps: 37, cfg: 3.1, seed: "8798399215689017476"}},
  });
});

it("requires MOSS dimensions divisible by sixteen before confirming parameter edits", async () => {
  mount();
  enterDraft();
  await screen.findByRole("option", { name: "测试云" });
  fireEvent.change(screen.getByRole("combobox", { name: "执行环境" }), { target: { value: "cloud" } });
  fireEvent.click(screen.getByRole("button", { name: /^生成参数/ }));
  fireEvent.change(screen.getByLabelText("宽度", { exact: true }), { target: { value: "1000" } });
  expect(screen.getByRole("button", { name: "确认应用参数" })).toBeDisabled();
  expect(screen.getByText("宽高必须为 16 的倍数。")).toBeVisible();
  expect(screen.getByRole("button", { name: "生成图像" })).toBeDisabled();
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).configuration.parameterOverrides).toEqual({});
  fireEvent.change(screen.getByLabelText("宽度", { exact: true }), { target: { value: "1008" } });
  fireEvent.click(screen.getByRole("button", { name: "确认应用参数" }));
  expect(screen.getByRole("button", { name: "生成图像" })).toBeEnabled();
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).configuration.parameterOverrides.width).toBe(1008);
  expect(generationRequests()).toEqual([]);
});

it("persists the visible negative verbatim and submits an explicitly cleared negative", async () => {
  const text = "  水印，\n\n  裁掉茶壶  ";
  let view = mount();
  fireEvent.change(screen.getByRole("textbox", { name: "原文" }), { target: { value: "窗边的陶瓷茶壶" } });
  editNegative(text);
  await screen.findByRole("option", { name: "测试云" });
  fireEvent.change(screen.getByRole("combobox", { name: "执行环境" }), { target: { value: "cloud" } });
  view.unmount();
  view = mount();
  expect(screen.getByRole("textbox", { name: "负向提示词" })).toHaveValue(text);
  const generate = screen.getByRole("button", { name: "生成图像" });
  await waitFor(() => expect(generate).toBeEnabled());
  fireEvent.click(generate);
  await waitFor(() => expect(generationRequests()).toHaveLength(1));
  expect(generationRequests()[0].body.negative_prompt).toBe(text);
  await waitFor(() => expect(screen.getByRole("tab", { name: "生成结果" })).toHaveAttribute("aria-selected", "true"));
  editNegative("");
  expect(screen.getByRole("tab", { name: "生成结果" })).toHaveAttribute("aria-selected", "true");
  await waitFor(() => expect(generate).toBeEnabled());
  fireEvent.click(generate);
  await waitFor(() => expect(generationRequests()).toHaveLength(2));
  expect(generationRequests()[1].body.negative_prompt).toBe("");
  view.unmount();
  mount();
  editNegative("");
  expect(screen.getByRole("textbox", { name: "负向提示词" })).toHaveValue("");
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).negative).toBe("");
});

it("opens the same main negative editor from the Sheet without a second input", () => {
  mount();
  fireEvent.click(screen.getByRole("button", { name: /^排除内容/ }));
  const dialog = screen.getByRole("dialog", { name: "创作辅助" });
  expect(within(dialog).queryByRole("textbox", { name: "负向提示词" })).toBeNull();
  fireEvent.click(within(dialog).getByRole("button", { name: "在正文区编辑负向提示词" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  const input = screen.getByRole("textbox", { name: "负向提示词" });
  expect(input).toBeVisible();
  expect(input).toHaveFocus();
  fireEvent.change(input, { target: { value: "水印，模糊" } });
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).negative).toBe("水印，模糊");
});

it.each([["只整理润色","正文"],["创意扩写","正文"],["只整理润色","建议"]])("%s keeps edits from %s when editing exclusions, reopening and generating",async(mode,field)=>{
  const view=mount();
  enterDraft();
  await screen.findByRole("option",{name:"测试云"});
  fireEvent.change(screen.getByRole("combobox",{name:"执行环境"}),{target:{value:"cloud"}});
  const dialog=await reviewSuggestion(mode);
  const positive="  成年女性在花园读书，全身入镜。\n书页写着『晨光』。  ";
  const exclusion="  模糊，裁掉双脚  ";
  if(field==="建议")fireEvent.change(within(dialog).getByRole("textbox",{name:"建议文本"}),{target:{value:positive}});
  fireEvent.click(within(dialog).getByRole("button",{name:"采用建议"}));
  if(field==="正文"){
    fireEvent.change(screen.getByLabelText("本次出图文本",{exact:true}),{target:{value:positive}});
    expect(screen.getByRole("status",{name:"本次出图文本状态"})).toHaveTextContent("已手动编辑");
  }
  editNegative(exclusion);
  expect(screen.getByLabelText("本次出图文本",{exact:true})).toHaveValue(positive);
  view.unmount();mount();
  expect(screen.getByRole("radio",{name:mode})).toBeChecked();
  expect(screen.getByLabelText("原文")).toHaveValue(original);
  expect(screen.getByLabelText("本次出图文本",{exact:true})).toHaveValue(positive);
  const generate=screen.getByRole("button",{name:"生成图像"});
  await waitFor(()=>expect(generate).toBeEnabled());
  fireEvent.click(generate);
  await waitFor(()=>expect(generationRequests()).toHaveLength(1));
  expect(generationRequests()[0].body).toMatchObject({positive_prompt:positive,negative_prompt:exclusion});
  expect(requests.filter(request=>request.url.includes("prompt-assist"))).toHaveLength(1);
});

it("keeps the raw Chinese draft and generation controls in the main view while auxiliary sections use one Sheet", () => {
  mount();
  fireEvent.change(screen.getByRole("textbox", { name: "原文" }), { target: { value: original } });
  expect(screen.getByRole("textbox", { name: "本次出图文本" })).toHaveValue(original);
  expect(screen.getByRole("status", { name: "本次出图文本状态" })).toHaveTextContent("使用中文原文");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

  const mainControls = [
    screen.getByRole("textbox", { name: "原文" }),
    screen.getByRole("textbox", { name: "本次出图文本" }),
    screen.getByRole("combobox", { name: "执行环境" }),
    screen.getByRole("button", { name: "获取建议" }),
    screen.getByRole("button", { name: "生成图像" }),
  ];
  for (const label of ["排除内容", "生成参数", "云端资源", "辅助建议"]) {
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${label}`) }));
    const dialog = screen.getByRole("dialog", { name: "创作辅助" });
    expect(within(dialog).getByRole("tab", { name: label })).toHaveAttribute("aria-selected", "true");
    for (const control of mainControls) expect(dialog).not.toContainElement(control);
    fireEvent.click(within(dialog).getByRole("button", { name: "关闭辅助设置" }));
  }
  expect(requests.some(request => request.url.includes("prompt-assist"))).toBe(false);
  expect(generationRequests()).toEqual([]);
});

it("auto-opens pending assistance and preserves an edited suggestion through cancel, close and reopen without adoption", async () => {
  mount();
  enterDraft();
  const dialog = await reviewSuggestion();
  const edited = "审阅中：保留“春天”，手持卡片的少女";
  fireEvent.change(within(dialog).getByRole("textbox", { name: "建议文本" }), { target: { value: edited } });
  fireEvent(dialog, new Event("cancel", { cancelable: true }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("status", { name: "本次出图文本状态" })).toHaveTextContent("建议待采用");
  expect(screen.getByRole("textbox", { name: "本次出图文本" })).toHaveValue("");

  fireEvent.click(screen.getByRole("button", { name: /^辅助建议/ }));
  expect(screen.getByRole("textbox", { name: "建议文本" })).toHaveValue(edited);
  fireEvent.click(screen.getByRole("button", { name: "关闭辅助设置" }));
  fireEvent.click(screen.getByRole("button", { name: /^辅助建议/ }));
  expect(screen.getByRole("textbox", { name: "建议文本" })).toHaveValue(edited);
  fireEvent.click(screen.getByRole("button", { name: "返回提示词" }));
  expect(screen.getByRole("status", { name: "本次出图文本状态" })).toHaveTextContent("建议待采用");
  expect(screen.getByRole("textbox", { name: "原文" })).toHaveValue(original);
  expect(generationRequests()).toEqual([]);
});

it("adopts exactly the edited positive text, closes the Sheet and submits only on Generate with the original negative draft", async () => {
  mount();
  enterDraft();
  await screen.findByRole("option", { name: "测试云" });
  fireEvent.change(screen.getByRole("combobox", { name: "执行环境" }), { target: { value: "cloud" } });
  const dialog = await reviewSuggestion();
  const edited = "  少女手持写着“春天”的卡片\n中文文字保持原样，柔和光线  ";
  fireEvent.change(within(dialog).getByRole("textbox", { name: "建议文本" }), { target: { value: edited } });
  expect(screen.getByLabelText("本次出图文本", { exact: true })).toHaveValue("");
  fireEvent.click(within(dialog).getByRole("button", { name: "采用建议" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "本次出图文本" })).toHaveValue(edited);
  expect(screen.getByRole("status", { name: "本次出图文本状态" })).toHaveTextContent("已采用辅助建议");
  expect(screen.getByRole("textbox", { name: "原文" })).toHaveValue(original);
  expect(generationRequests()).toEqual([]);

  fireEvent.click(screen.getByRole("button", { name: "生成图像" }));
  await waitFor(() => expect(generationRequests()).toHaveLength(1));
  expect(generationRequests()[0]).toMatchObject({ url: "/api/v3/direct-prompt/runs", body: {
    positive_prompt: edited, negative_prompt: negative,
    model_profile: "moss_image_sft_int8", remote_profile_id: "cloud", workflow_profile_id: "v3_moss_image_sft_int8",
  } });
  await screen.findByText(/moss-sheet-run/);
});

it("keeps an adopted positive when the negative changes and can still return to the original source", async () => {
  mount();
  enterDraft();
  await reviewSuggestion();
  fireEvent.click(screen.getByRole("button", { name: "采用建议" }));
  expect(screen.getByRole("status", { name: "本次出图文本状态" })).toHaveTextContent("已采用辅助建议");
  editNegative("不要水印，不要边框");
  expect(screen.getByRole("textbox", { name: "本次出图文本" })).toHaveValue(suggestion.positive);
  expect(screen.getByRole("status", { name: "本次出图文本状态" })).not.toHaveTextContent("已采用辅助建议");
  expect(requests.filter(request => request.url.includes("prompt-assist"))).toHaveLength(1);
  expect(screen.getByRole("textbox", { name: "负向提示词" })).toHaveValue("不要水印，不要边框");

  fireEvent.click(screen.getByLabelText("原文直接出图"));
  expect(screen.getByRole("textbox", { name: "本次出图文本" })).toHaveValue(original);
  expect(screen.getByRole("status", { name: "本次出图文本状态" })).toHaveTextContent("使用中文原文");
  expect(generationRequests()).toEqual([]);
});

it("reopens assistance review from the main view after visiting another Sheet section", async () => {
  mount();
  enterDraft();
  await reviewSuggestion();
  fireEvent.click(screen.getByRole("button", { name: "关闭辅助设置" }));
  fireEvent.click(screen.getByRole("button", { name: /^生成参数/ }));
  expect(screen.getByRole("tab", { name: "生成参数" })).toHaveAttribute("aria-selected", "true");
  fireEvent.click(screen.getByRole("button", { name: "返回提示词" }));

  fireEvent.click(screen.getByRole("button", { name: "审阅辅助建议" }));
  const dialog = screen.getByRole("dialog", { name: "创作辅助" });
  await waitFor(() => expect(within(dialog).getByRole("tab", { name: "辅助建议" })).toHaveAttribute("aria-selected", "true"));
  expect(within(dialog).getByRole("textbox", { name: "建议文本" })).toHaveValue(suggestion.positive);
});
