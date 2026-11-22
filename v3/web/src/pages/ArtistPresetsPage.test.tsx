import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {createMemoryRouter, RouterProvider} from "react-router-dom";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {ArtistPresetsPage} from "./ArtistPresetsPage";
import {artistPresetsApi, type ArtistPreset} from "../lib/artistPresets";

vi.mock("../lib/artistPresets", async importOriginal => {
  const actual = await importOriginal<typeof import("../lib/artistPresets")>();
  return {...actual, artistPresetsApi: Object.fromEntries(Object.keys(actual.artistPresetsApi).map(key => [key, vi.fn()]))};
});
const preset = (overrides: Partial<ArtistPreset> = {}): ArtistPreset => ({id: "preset-1", revision: 1, name: "双画师", positive: "(@poco \\(asahi age\\):1.2), @aoi tori", negative: "", model_family: "anima", model_label: "anima-base-v1.0", syntax: "comfy", source_url: "https://example.org/source", source_author: "", notes: "", favorite: false, content_hash: "hash-1", created_at: "2026-10-25", updated_at: "2026-10-25", samples: [], ready: false, ...overrides});
function mount(url = "/artists/presets") {return render(<RouterProvider router={createMemoryRouter([{path: "*", element: <ArtistPresetsPage />}], {initialEntries: [url]})} />);}
beforeEach(() => {vi.clearAllMocks(); vi.mocked(artistPresetsApi.list).mockResolvedValue({items: [preset(), preset({id: "nai", name: "NAI 组合", model_family: "novelai", model_label: "V4.5"})]}); vi.mocked(artistPresetsApi.suggestions).mockResolvedValue({items: []});});
afterEach(() => vi.restoreAllMocks());
describe("artist preset library", () => {
  it("defaults to Anima and makes other model families explicitly discoverable", async () => {
    mount(); expect(await screen.findByRole("button", {name: /查看 双画师/})).toBeInTheDocument();
    expect(screen.queryByRole("button", {name: /查看 NAI 组合/})).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("模型筛选"), {target: {value: "all"}});
    expect(screen.getByRole("button", {name: /查看 NAI 组合/})).toHaveTextContent("NovelAI · V4.5");
  });
  it("saves literal weighted text without normalizing whitespace or escaping", async () => {
    const raw = "  (@poco \\(asahi age\\):1.2),\n@aoi tori  ";
    vi.mocked(artistPresetsApi.update).mockResolvedValue(preset({positive: raw, revision: 2}));
    mount(); fireEvent.click(await screen.findByRole("button", {name: /查看 双画师/}));
    fireEvent.change(screen.getByLabelText("正向画师串原文"), {target: {value: raw}});
    fireEvent.click(screen.getByRole("button", {name: "保存画师串"}));
    await waitFor(() => expect(artistPresetsApi.update).toHaveBeenCalledWith("preset-1", expect.objectContaining({positive: raw}), 1));
  });
  it("keeps draft visible after a revision conflict", async () => {
    vi.mocked(artistPresetsApi.update).mockRejectedValue(new Error("条目已在其他窗口更新，请刷新后重试。"));
    mount(); fireEvent.click(await screen.findByRole("button", {name: /查看 双画师/}));
    fireEvent.change(screen.getByLabelText("正向画师串原文"), {target: {value: "my unsaved @artist"}});
    fireEvent.click(screen.getByRole("button", {name: "保存画师串"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("其他窗口");
    expect(screen.getByLabelText("正向画师串原文")).toHaveValue("my unsaved @artist");
  });
  it("does not label an old sample as current, and shows full prompt provenance", async () => {
    vi.mocked(artistPresetsApi.list).mockResolvedValue({items: [preset({samples: [{id: "sample", content_hash: "old", image_url: "/sample.jpg", width: 800, height: 1200, model_label: "Anima preview", source_url: "", caption: "来源图", full_positive: "full prompt @old", full_negative: "bad anatomy", parameters: {steps: 28}, source_kind: "reference", source_id: "reference", created_at: "today"}]})]});
    mount(); fireEvent.click(await screen.findByRole("button", {name: /查看 双画师/}));
    expect(screen.getByText("旧版样品")).toBeInTheDocument();
    expect(screen.getByText("full prompt @old")).toBeInTheDocument();
    expect(screen.getAllByText("待补样品").length).toBeGreaterThan(0);
    expect(screen.queryByText("已验证")).not.toBeInTheDocument();
  });
  it("imports references by immutable reference ID, not lossy artist metadata", async () => {
    vi.mocked(artistPresetsApi.suggestions).mockResolvedValue({items: [{reference_id: "ref-1", name: "原图组合", positive: "@a, @b", model_label: "Anima base", source_url: "https://example.org", thumbnail_url: "/ref.jpg", notes: "种子未提供"}]});
    vi.mocked(artistPresetsApi.fromReference).mockResolvedValue(preset({name: "原图组合"}));
    mount(); fireEvent.click(await screen.findByRole("button", {name: "收藏 原图组合"}));
    await waitFor(() => expect(artistPresetsApi.fromReference).toHaveBeenCalledWith("ref-1"));
    expect(await screen.findByLabelText("名称")).toHaveValue("原图组合");
  });
  it("opens the requested preset and its actual model family from a workbench link", async () => {
    mount("/artists/presets?selected=nai");
    expect(await screen.findByLabelText("名称")).toHaveValue("NAI 组合");
    expect(screen.getByLabelText("模型筛选")).toHaveValue("novelai");
  });
  it("blocks malformed sample parameters and uploads the full raw prompt with valid metadata", async () => {
    vi.mocked(artistPresetsApi.uploadSample).mockResolvedValue(preset({revision: 2}));
    mount(); fireEvent.click(await screen.findByRole("button", {name: /查看 双画师/}));
    fireEvent.click(screen.getByText("添加一张样品"));
    fireEvent.click(screen.getByText("补充原图完整提示词和参数"));
    const file = new File(["pixels"], "image.png", {type: "image/png"});
    fireEvent.change(screen.getByLabelText("样品图片"), {target: {files: [file]}});
    fireEvent.change(screen.getByLabelText("生成参数（JSON，可留空）"), {target: {value: "[]"}});
    fireEvent.submit(screen.getByRole("button", {name: "保存样品"}).closest("form")!);
    expect(screen.getByRole("alert")).toHaveTextContent("JSON 对象");
    expect(artistPresetsApi.uploadSample).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("生成参数（JSON，可留空）"), {target: {value: '{"seed":18446744073709551615}'}});
    fireEvent.submit(screen.getByRole("button", {name: "保存样品"}).closest("form")!);
    expect(screen.getByRole("alert")).toHaveTextContent("双引号");
    expect(artistPresetsApi.uploadSample).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("生成参数（JSON，可留空）"), {target: {value: '{"seed":"18446744073709551615","steps":28}'}});
    fireEvent.change(screen.getByLabelText("样品完整正向提示词"), {target: {value: "character,\n  @artist  "}});
    fireEvent.submit(screen.getByRole("button", {name: "保存样品"}).closest("form")!);
    await waitFor(() => expect(artistPresetsApi.uploadSample).toHaveBeenCalledWith("preset-1", file, expect.objectContaining({full_positive: "character,\n  @artist  ", parameters: {seed: "18446744073709551615", steps: 28}}), 1));
  });
  it("preserves an unfinished sample when card navigation or a content-changing save is canceled", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    mount(); fireEvent.click(await screen.findByRole("button", {name: /查看 双画师/}));
    fireEvent.click(screen.getByText("添加一张样品"));
    fireEvent.click(screen.getByText("补充原图完整提示词和参数"));
    const file = new File(["pixels"], "image.png", {type: "image/png"});
    fireEvent.change(screen.getByLabelText("样品图片"), {target: {files: [file]}});
    fireEvent.change(screen.getByLabelText("样品完整正向提示词"), {target: {value: "unfinished full prompt"}});
    fireEvent.change(screen.getByLabelText("模型筛选"), {target: {value: "all"}});
    fireEvent.click(screen.getByRole("button", {name: /查看 NAI 组合/}));
    expect(confirm).toHaveBeenCalled();
    expect(screen.getByLabelText("名称")).toHaveValue("双画师");
    expect(screen.getByLabelText("样品完整正向提示词")).toHaveValue("unfinished full prompt");
    expect((screen.getByLabelText("样品图片") as HTMLInputElement).files?.[0]).toBe(file);
    fireEvent.change(screen.getByLabelText("正向画师串原文"), {target: {value: "@different"}});
    fireEvent.click(screen.getByRole("button", {name: "保存画师串"}));
    expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining("样品"));
    expect(artistPresetsApi.update).not.toHaveBeenCalled();
    expect(screen.getByLabelText("样品完整正向提示词")).toHaveValue("unfinished full prompt");
  });
  it("keeps failed upload drafts protected and clears them only after a successful upload", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    vi.mocked(artistPresetsApi.uploadSample).mockRejectedValueOnce(new Error("样品上传失败")).mockResolvedValueOnce(preset({revision: 2}));
    mount(); fireEvent.click(await screen.findByRole("button", {name: /查看 双画师/}));
    fireEvent.click(screen.getByText("添加一张样品"));
    const file = new File(["pixels"], "image.png", {type: "image/png"});
    fireEvent.change(screen.getByLabelText("样品图片"), {target: {files: [file]}});
    fireEvent.change(screen.getByLabelText("样品说明"), {target: {value: "keep this draft"}});
    fireEvent.submit(screen.getByRole("button", {name: "保存样品"}).closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("样品上传失败");
    fireEvent.click(screen.getByRole("button", {name: "关闭编辑"}));
    expect(confirm).toHaveBeenCalledOnce();
    expect(screen.getByLabelText("样品说明")).toHaveValue("keep this draft");
    fireEvent.submit(screen.getByRole("button", {name: "保存样品"}).closest("form")!);
    await waitFor(() => expect(screen.getByLabelText("样品说明")).toHaveValue(""));
    fireEvent.click(screen.getByRole("button", {name: "关闭编辑"}));
    expect(screen.queryByLabelText("名称")).not.toBeInTheDocument();
    expect(confirm).toHaveBeenCalledOnce();
  });
});
