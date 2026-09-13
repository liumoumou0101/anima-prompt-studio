import {useState} from "react";
import {act, cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {apiRequest} from "../lib/api";
import {cleanRequirements, emptyRequirements, type RequirementsEdit} from "../lib/conversation";
import {applySceneChoices, parseSceneAdvice, sceneChoice, undoSceneChoices} from "../lib/sceneDesign";
import {SceneDesignControls, type SceneDesignControlsProps} from "./SceneDesignControls";

vi.mock("../lib/api", () => ({apiRequest: vi.fn()}));
beforeEach(() => vi.mocked(apiRequest).mockReset());
afterEach(cleanup);
function Harness({initial = emptyRequirements()}: {initial?: RequirementsEdit}) {
  const [requirements, setRequirements] = useState(initial);
  return <><SceneDesignControls requirements={requirements} onChange={setRequirements} workspaceId="workspace_test" workspaceRevision={1} delta="女孩在窗边" positive="my prompt" negative="" /><output data-testid="requirements">{JSON.stringify(requirements)}</output></>;
}
function current(): RequirementsEdit {return JSON.parse(screen.getByTestId("requirements").textContent || "{}");}

it("leaves all five fields unspecified and makes no automatic requests", () => {
  render(<Harness />);
  for (const label of ["景别", "构图布局", "相机机位", "人物视线", "氛围"]) expect(screen.getByLabelText(label)).toHaveValue("");
  expect(apiRequest).not.toHaveBeenCalled();
  expect(cleanRequirements(current())).toEqual(emptyRequirements());
});

it("switches one choice, clears without deleting prose, and can undo", () => {
  const initial = emptyRequirements(); initial.layers.composition.text = "留白中放标题"; initial.layers.exclusions.global = ["hat"];
  render(<Harness initial={initial} />);
  fireEvent.change(screen.getByLabelText("景别"), {target: {value: "半身"}});
  fireEvent.change(screen.getByLabelText("景别"), {target: {value: "全身"}});
  expect(current().layers.composition.design).toEqual({shot: {value: "全身", source: "user"}});
  fireEvent.click(screen.getByRole("button", {name: "清除景别"}));
  expect(current().layers.composition.design).toBeUndefined();
  expect(current().layers.composition.text).toBe("留白中放标题");
  expect(current().layers.exclusions.global).toEqual(["hat"]);
  fireEvent.click(screen.getByRole("button", {name: "撤销画面调整"}));
  expect(sceneChoice(current(), "shot")?.value).toBe("全身");
  expect(apiRequest).not.toHaveBeenCalled();
});

it("requires confirmation before replacing an existing freeform shot and undo restores it", () => {
  const initial = emptyRequirements(); initial.layers.composition.shot = "脚部特写";
  render(<Harness initial={initial} />);
  fireEvent.change(screen.getByLabelText("景别"), {target: {value: "半身"}});
  expect(current().layers.composition.shot).toBe("脚部特写");
  expect(current().layers.composition.design).toBeUndefined();
  fireEvent.click(screen.getByRole("button", {name: "替换原景别"}));
  expect(current().layers.composition.shot).toBe("");
  expect(sceneChoice(current(), "shot")?.value).toBe("半身");
  fireEvent.click(screen.getByRole("button", {name: "撤销画面调整"}));
  expect(current().layers.composition.shot).toBe("脚部特写");
  expect(current().layers.composition.design).toBeUndefined();
});

it("requires gaze ownership and supports custom intent without a tag mapping", () => {
  render(<Harness />);
  fireEvent.change(screen.getByLabelText("人物视线"), {target: {value: "看向远方"}});
  expect(screen.getByRole("alert")).toHaveTextContent("作用的人物");
  expect(sceneChoice(current(), "gaze")).toBeNull();
  fireEvent.change(screen.getByLabelText("视线作用人物"), {target: {value: "右侧男孩"}});
  fireEvent.change(screen.getByLabelText("人物视线"), {target: {value: "__custom"}});
  fireEvent.change(screen.getByLabelText("自定义人物视线"), {target: {value: "看向左侧女孩手中的信封"}});
  fireEvent.click(screen.getByRole("button", {name: "确定"}));
  expect(sceneChoice(current(), "gaze")).toEqual({value: "看向左侧女孩手中的信封", source: "user", target: "右侧男孩"});
});

it("keeps successful advice separate until explicitly adopted, then labels its source", async () => {
  vi.mocked(apiRequest).mockResolvedValue({suggestions: [{title: "安静的留白", reason: "让环境更突出", choices: {layout: {value: "保留明显留白"}}}], extracted: []});
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", {name: "给我建议"}));
  const adopt = await screen.findByRole("button", {name: "采用“安静的留白”"});
  expect(sceneChoice(current(), "layout")).toBeNull();
  const body = JSON.parse(String(vi.mocked(apiRequest).mock.calls[0][1]?.body));
  expect(body).toMatchObject({delta: "女孩在窗边", positive: "my prompt", negative: "", workspace_id: "workspace_test"});
  fireEvent.click(adopt);
  expect(sceneChoice(current(), "layout")).toEqual({value: "保留明显留白", source: "suggestion"});
  expect(screen.getByText("建议 · 已采用")).toBeInTheDocument();
  expect(apiRequest).toHaveBeenCalledTimes(1);
});

it("preserves the draft on network failure and on invalid advice", async () => {
  vi.mocked(apiRequest).mockRejectedValueOnce(new Error("网络暂时不可用")).mockResolvedValueOnce({suggestions: [{choices: {negative: "bad"}}], extracted: []});
  render(<Harness />);
  fireEvent.change(screen.getByLabelText("氛围"), {target: {value: "宁静日常"}});
  const before = current();
  fireEvent.click(screen.getByRole("button", {name: "给我建议"}));
  await screen.findByText("网络暂时不可用");
  expect(current()).toEqual(before);
  fireEvent.click(screen.getByRole("button", {name: "给我建议"}));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("格式有误"));
  expect(current()).toEqual(before);
});

it("disables adopting a suggestion for a locked layer while allowing deliberate manual editing", async () => {
  const initial = emptyRequirements(); initial.layers.composition.locked = true;
  vi.mocked(apiRequest).mockResolvedValue({suggestions: [{title: "远景", reason: "看到环境", choices: {shot: {value: "远景"}}}], extracted: []});
  render(<Harness initial={initial} />);
  fireEvent.click(screen.getByRole("button", {name: "给我建议"}));
  expect(await screen.findByRole("button", {name: "采用“远景”"})).toBeDisabled();
  fireEvent.change(screen.getByLabelText("景别"), {target: {value: "半身"}});
  expect(sceneChoice(current(), "shot")?.value).toBe("半身");
  expect(current().layers.composition.locked).toBe(true);
});

it("discards delayed advice after the draft has changed", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(apiRequest).mockReturnValue(new Promise(resolve => {finish = resolve;}));
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", {name: "给我建议"}));
  fireEvent.change(screen.getByLabelText("景别"), {target: {value: "半身"}});
  await act(async () => finish({suggestions: [{title: "旧方向", reason: "旧内容", choices: {layout: {value: "居中构图"}}}], extracted: []}));
  expect(screen.queryByText("助手建议 · 旧方向")).not.toBeInTheDocument();
  expect(sceneChoice(current(), "shot")?.value).toBe("半身");
});

it("undo does not erase later edits to other fields or a subsequently replaced choice", () => {
  const before = emptyRequirements();
  const after = applySceneChoices(before, {shot: {value: "半身", source: "user"}});
  const later = applySceneChoices(after, {shot: {value: "全身", source: "user"}, mood: {value: "宁静", source: "user"}});
  later.layers.subject.text = "后续写的文字";
  expect(undoSceneChoices(later, before, after)).toEqual(later);
});

it("normalizes server defaults so saving a scene choice does not leave a false dirty state", () => {
  const local = applySceneChoices(emptyRequirements(), {shot: {value: "半身", source: "user"}});
  const saved = structuredClone(local);
  saved.layers.composition.design!.shot = {value: "半身", source: "user", target: "", evidence: ""};
  saved.layers.composition.design!.gaze = null;
  saved.layers.lighting.mood = null;
  expect(cleanRequirements(saved)).toEqual(cleanRequirements(local));
});

it("cancels an older freeform replacement when a later selection changes the intent", () => {
  const initial = emptyRequirements(); initial.layers.composition.shot = "脚部特写";
  render(<Harness initial={initial} />);
  fireEvent.change(screen.getByLabelText("景别"), {target: {value: "半身"}});
  expect(screen.getByRole("button", {name: "替换原景别"})).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("景别"), {target: {value: ""}});
  expect(screen.queryByRole("button", {name: "替换原景别"})).not.toBeInTheDocument();
  expect(current().layers.composition.shot).toBe("脚部特写");
  expect(sceneChoice(current(), "shot")).toBeNull();
});

it("does not resurrect superseded freeform text when undo follows a later shot edit", () => {
  const before = emptyRequirements(); before.layers.composition.shot = "脚部特写";
  const after = applySceneChoices(before, {shot: {value: "半身", source: "user"}});
  after.layers.composition.shot = "";
  const later = applySceneChoices(after, {shot: {value: "全身", source: "user"}});
  expect(undoSceneChoices(later, before, after)).toEqual(later);
});

it("preserves confirmed provenance while adopting a suggestion's additional fields", async () => {
  const initial = applySceneChoices(emptyRequirements(), {layout: {value: "三分法", source: "extracted", evidence: "女孩在画面左侧三分之一处"}});
  vi.mocked(apiRequest).mockResolvedValue({suggestions: [{title: "舒展环境", reason: "保留构图，明确气氛", choices: {layout: {value: "三分法"}, mood: {value: "宁静日常"}}}], extracted: []});
  render(<Harness initial={initial} />);
  fireEvent.click(screen.getByRole("button", {name: "给我建议"}));
  fireEvent.click(await screen.findByRole("button", {name: "采用“舒展环境”"}));
  expect(sceneChoice(current(), "layout")).toEqual(sceneChoice(initial, "layout"));
  expect(sceneChoice(current(), "mood")).toEqual({value: "宁静日常", source: "suggestion"});
  fireEvent.click(screen.getByRole("button", {name: "撤销画面调整"}));
  expect(current()).toEqual(initial);
});

it("rejects an entire suggestion that would overwrite a selected person's gaze", async () => {
  const initial = applySceneChoices(emptyRequirements(), {gaze: {value: "看向远方", source: "user", target: "左侧女孩"}});
  vi.mocked(apiRequest).mockResolvedValue({suggestions: [{title: "交换视线", reason: "调整关系", choices: {mood: {value: "宁静日常"}, gaze: {value: "看向远方", target: "右侧男孩"}}}], extracted: []});
  render(<Harness initial={initial} />);
  fireEvent.click(screen.getByRole("button", {name: "给我建议"}));
  fireEvent.click(await screen.findByRole("button", {name: "采用“交换视线”"}));
  expect(screen.getByRole("alert")).toHaveTextContent("已指定的人物视线");
  expect(current()).toEqual(initial);
});

it("adopts a confirmed extraction with its original evidence and exact gaze owner", async () => {
  vi.mocked(apiRequest).mockResolvedValue({suggestions: [], extracted: [{field: "gaze", value: "注视右侧男孩", target: "左侧女孩", evidence: "左侧女孩注视右侧男孩"}]});
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", {name: "给我建议"}));
  fireEvent.click(await screen.findByRole("button", {name: "确认这项提取"}));
  expect(sceneChoice(current(), "gaze")).toEqual({value: "注视右侧男孩", target: "左侧女孩", evidence: "左侧女孩注视右侧男孩", source: "extracted"});
  expect(screen.getByLabelText("视线作用人物")).toHaveValue("左侧女孩");
});

it("avoids a paid advice request when both layers are locked", () => {
  const initial = emptyRequirements(); initial.layers.composition.locked = true; initial.layers.lighting.locked = true;
  render(<Harness initial={initial} />);
  expect(screen.getByRole("button", {name: "给我建议"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button", {name: "给我建议"}));
  expect(apiRequest).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("氛围"), {target: {value: "宁静日常"}});
  expect(sceneChoice(current(), "mood")?.value).toBe("宁静日常");
});

it.each([
  {delta: "新的多人描述"}, {positive: "manually edited positive"}, {negative: "manual exclusions"},
  {workspaceId: "workspace_other"}, {workspaceRevision: 2},
])("discards delayed advice after context changes: %j", async changed => {
  let finish!: (value: unknown) => void;
  vi.mocked(apiRequest).mockReturnValue(new Promise(resolve => {finish = resolve;}));
  const props: SceneDesignControlsProps = {requirements: emptyRequirements(), onChange: vi.fn(), workspaceId: "workspace_test", workspaceRevision: 1};
  const view = render(<SceneDesignControls {...props} />);
  fireEvent.click(screen.getByRole("button", {name: "给我建议"}));
  view.rerender(<SceneDesignControls {...props} {...changed} />);
  await act(async () => finish({suggestions: [{title: "旧方向", reason: "旧内容", choices: {layout: {value: "居中构图"}}}], extracted: []}));
  expect(screen.queryByText("助手建议 · 旧方向")).not.toBeInTheDocument();
  expect(props.onChange).not.toHaveBeenCalled();
});

it.each(["视线作用人物", "自定义人物视线"])("discards delayed advice after an unconfirmed %s draft changes", async label => {
  let finish!: (value: unknown) => void;
  vi.mocked(apiRequest).mockReturnValue(new Promise(resolve => {finish = resolve;}));
  render(<Harness />);
  if (label.startsWith("自定义")) fireEvent.change(screen.getByLabelText("人物视线"), {target: {value: "__custom"}});
  fireEvent.click(screen.getByRole("button", {name: "给我建议"}));
  fireEvent.change(screen.getByLabelText(label), {target: {value: "左侧女孩"}});
  await act(async () => finish({suggestions: [{title: "旧方向", reason: "旧内容", choices: {layout: {value: "居中构图"}}}], extracted: []}));
  expect(screen.queryByText("助手建议 · 旧方向")).not.toBeInTheDocument();
  expect(sceneChoice(current(), "gaze")).toBeNull();
});

it("requires a named gaze target in both suggestions and extractions", () => {
  expect(() => parseSceneAdvice({suggestions: [{title: "两人", reason: "视线关系", choices: {gaze: {value: "看向远方", target: "  "}}}], extracted: []})).toThrow("格式有误");
  expect(() => parseSceneAdvice({suggestions: [], extracted: [{field: "gaze", value: "看向远方", evidence: "女孩看向远方"}]})).toThrow("格式有误");
});

it("does not copy unexpected response properties into adopted requirements", () => {
  const advice = parseSceneAdvice({suggestions: [{title: "留白", reason: "环境", choices: {layout: {value: "保留明显留白", negative: "unsolicited", source: "user"}}}], extracted: []});
  expect(advice.suggestions[0].choices.layout).toEqual({value: "保留明显留白"});
});
