import {fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import {createMemoryRouter, RouterProvider} from "react-router-dom";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {PersonalTagsPage} from "./PersonalTagsPage";
import {personalTagsApi, type CategoryRecord, type TagRecord} from "../lib/personalTags";
import {readPersonalPromptTransfer} from "../lib/personalPromptTransfer";

vi.mock("../lib/personalTags", async importOriginal => {
  const original = await importOriginal<typeof import("../lib/personalTags")>();
  return {...original, personalTagsApi: Object.fromEntries(Object.keys(original.personalTagsApi).map(key => [key, vi.fn()]))};
});

const category = (id: string, name: string, parent_id: string | null = null): CategoryRecord => ({id, name, parent_id, position: 0, revision: 1, created_at: "", updated_at: "", deleted_at: null, source_key: null, source_id: null, source_metadata: {}, needs_review: []});
const tag = (id: string, display_name: string, content: string, category_id = "child"): TagRecord => ({id, display_name, content, category_id, aliases: [], kind: "tag", notes: "", default_weight: 1, revision: 1, created_at: "", updated_at: "", deleted_at: null, source_key: null, source_id: null, source_metadata: {}, needs_review: []});
const categories = [category("root", "人物"), category("child", "头发", "root"), category("grand", "长发", "child")];
const tags = [tag("one", "长发", "long hair"), tag("two", "短发", "short hair")];
const api = personalTagsApi as unknown as Record<string, ReturnType<typeof vi.fn>>;
function mount(initialEntries = ["/personal-tags"], initialIndex = initialEntries.length - 1) {
  const router = createMemoryRouter([
    {path: "/personal-tags", element: <PersonalTagsPage />},
    {path: "/workbench", element: <p>工作台内容</p>},
  ], {initialEntries, initialIndex});
  render(<RouterProvider router={router} />);
  return router;
}
beforeEach(() => {
  localStorage.clear(); vi.clearAllMocks();
  vi.stubGlobal("confirm", vi.fn(() => true));
  api.listCategories.mockResolvedValue(categories);
  api.listTags.mockResolvedValue({items: tags, total: 2, offset: 0, limit: 40, has_more: false});
  api.getDraft.mockResolvedValue({items: [], revision: 1, updated_at: ""});
  api.saveDraft.mockImplementation(async (items: unknown[]) => ({items, revision: 2, updated_at: ""}));
  api.listCombinations.mockResolvedValue([]);
  api.findSimilar.mockResolvedValue([]);
});
afterEach(() => vi.unstubAllGlobals());

describe("personal tag market", () => {
  it("shows and clears visible negative-only selection feedback", async () => {
    mount();
    const negative = await screen.findByRole("button", {name: "加入负向 长发"});
    fireEvent.click(negative);
    expect(negative).toHaveAttribute("aria-pressed", "true");
    expect(negative).toHaveTextContent("已选");
    expect(screen.getByRole("button", {name: "加入正向 长发"})).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", {name: "移除 长发"}));
    expect(negative).toHaveAttribute("aria-pressed", "false");
    expect(negative).not.toHaveTextContent("已选");
  });
  it("appends_exact_personal_prompt_after_flushing_latest_selection_without_clearing_source", async () => {
    let finishSave!: (value: unknown) => void;
    api.saveDraft.mockImplementationOnce(() => new Promise(resolve => {finishSave = resolve;}));
    api.listTags.mockResolvedValue({items: [tag("one", "原文片段", " Portrait,\nBlue_Sky "), tag("two", "负向片段", "BAD_hands, blur")], total: 2, offset: 0, limit: 40, has_more: false});
    const router = mount();
    fireEvent.click(await screen.findByRole("button", {name: "加入正向 原文片段"}));
    fireEvent.click(screen.getByRole("button", {name: "追加到工作台"}));
    expect(router.state.location.pathname).toBe("/personal-tags");
    expect(screen.getByRole("button", {name: "追加到工作台"})).toBeDisabled();
    expect(Object.keys(localStorage).filter(key => key.startsWith("anima-personal-prompt-transfer:"))).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", {name: "加入负向 负向片段"}));
    finishSave({items: [], revision: 2, updated_at: ""});
    await screen.findByText("工作台内容");
    const id = new URLSearchParams(router.state.location.search).get("personal_transfer")!;
    expect(id).toBeTruthy();
    expect(router.state.location.search).not.toContain("Portrait");
    expect(readPersonalPromptTransfer(id)).toMatchObject({positive: " Portrait,\nBlue_Sky ", negative: "BAD_hands, blur"});
    expect(Object.keys(localStorage).filter(key => key.startsWith("anima-personal-prompt-transfer:"))).toHaveLength(1);
    const saved = api.saveDraft.mock.calls.at(-1)![0];
    expect(saved).toHaveLength(2);
    expect(saved.map((item: {content: string}) => item.content)).toEqual([" Portrait,\nBlue_Sky ", "BAD_hands, blur"]);
    api.getDraft.mockResolvedValue({items: saved, revision: 3, updated_at: ""});
    await router.navigate("/personal-tags");
    expect(await screen.findByRole("button", {name: "移除 原文片段"})).toBeInTheDocument();
    expect(screen.getByRole("button", {name: "移除 负向片段"})).toBeInTheDocument();
  });
  it("retains_source_and_does_not_create_transfer_or_navigate_when_append_flush_fails", async () => {
    api.saveDraft.mockRejectedValue(new Error("save unavailable"));
    const router = mount();
    fireEvent.click(await screen.findByRole("button", {name: "加入正向 长发"}));
    fireEvent.click(screen.getByRole("button", {name: "追加到工作台"}));
    await screen.findByText("组合草稿尚未保存，请重试或处理保存错误");
    expect(router.state.location.pathname).toBe("/personal-tags");
    expect(screen.getByRole("button", {name: "移除 长发"})).toBeInTheDocument();
    expect(Object.keys(localStorage).filter(key => key.startsWith("anima-personal-prompt-transfer:"))).toHaveLength(0);
  });
  it("retains_source_on_transfer_storage_failure_and_allows_negative_only_retry", async () => {
    const router = mount();
    fireEvent.click(await screen.findByRole("button", {name: "加入负向 长发"}));
    const original = Storage.prototype.setItem;
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(function(this: Storage, key: string, value: string) {
      if (key.startsWith("anima-personal-prompt-transfer:")) throw new Error("传递记录无法写入");
      original.call(this, key, value);
    });
    fireEvent.click(screen.getByRole("button", {name: "追加到工作台"}));
    await screen.findByText("传递记录无法写入");
    expect(router.state.location.pathname).toBe("/personal-tags");
    expect(screen.getByRole("button", {name: "移除 长发"})).toBeInTheDocument();
    spy.mockRestore();
    fireEvent.click(screen.getByRole("button", {name: "追加到工作台"}));
    await screen.findByText("工作台内容");
    const id = new URLSearchParams(router.state.location.search).get("personal_transfer")!;
    expect(readPersonalPromptTransfer(id)).toMatchObject({positive: "", negative: "long hair"});
  });
  it("browses_descendants_and_searches_aliases", async () => {
    mount(); fireEvent.click(await screen.findByRole("button", {name: "展开分类 人物"}));
    fireEvent.click(screen.getByRole("button", {name: "选择分类 头发"}));
    await waitFor(() => expect(api.listTags).toHaveBeenCalledWith(expect.objectContaining({category_id: "child", include_descendants: true})));
    fireEvent.change(screen.getByRole("searchbox", {name: "搜索标签"}), {target: {value: "longhair"}});
    await waitFor(() => expect(api.listTags).toHaveBeenCalledWith(expect.objectContaining({q: "longhair"})));
  });
  it("keeps_selection_across_modes_and_refresh", async () => {
    mount(); fireEvent.click(await screen.findByRole("button", {name: "加入正向 长发"}));
    fireEvent.click(screen.getByRole("button", {name: "管理词库"}));
    expect(await screen.findByText(/已选 1 项/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {name: "挑选标签"}));
    expect(await screen.findByRole("button", {name: "移除 长发"})).toBeInTheDocument();
  });
  it("edits_and_restores_without_changing_composition_snapshot", async () => {
    let edited = tags[0]; let deleted = false;
    api.listTags.mockImplementation(async ({trash}: {trash?: boolean}) => ({items: Boolean(trash) === deleted ? [edited] : [], total: Boolean(trash) === deleted ? 1 : 0, offset: 0, limit: 40, has_more: false}));
    api.updateTag.mockImplementation(async (_id: string, value: TagRecord) => {edited = {...edited, ...value, revision: 2}; return edited;});
    api.deleteTag.mockImplementation(async () => {deleted = true; edited = {...edited, deleted_at: "now", revision: 3}; return edited;});
    api.restoreTag.mockImplementation(async () => {deleted = false; edited = {...edited, deleted_at: null, revision: 4}; return edited;});
    mount(); fireEvent.click(await screen.findByRole("button", {name: "加入正向 长发"}));
    fireEvent.click(screen.getByRole("button", {name: "管理词库"}));
    fireEvent.click(screen.getByRole("button", {name: "编辑 长发"}));
    fireEvent.change(await screen.findByRole("textbox", {name: "英文原文"}), {target: {value: "longer hair"}});
    fireEvent.click(screen.getByRole("button", {name: "保存修改"}));
    await waitFor(() => expect(api.updateTag).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByRole("region", {name: "编辑标签"})).not.toBeInTheDocument());
    fireEvent.click(await screen.findByRole("button", {name: "编辑 长发"}));
    fireEvent.click(await screen.findByRole("button", {name: "移入回收站"}));
    await waitFor(() => expect(api.deleteTag).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("checkbox", {name: "回收站"}));
    fireEvent.click(await screen.findByRole("button", {name: "编辑 长发"}));
    fireEvent.click(await screen.findByRole("button", {name: "恢复标签"}));
    await waitFor(() => expect(api.restoreTag).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", {name: "挑选标签"}));
    expect(await screen.findByRole("button", {name: "移除 长发"})).toBeInTheDocument();
    expect(within(screen.getByRole("region", {name: "已选组合"})).getByText("long hair", {selector: "small"})).toBeInTheDocument();
  });
  it("ignores_stale_search_responses", async () => {
    let resolveOld!: (value: unknown) => void;
    api.listTags.mockImplementation(({q}: {q?: string}) => q === "old" ? new Promise(resolve => {resolveOld = resolve;}) : Promise.resolve({items: q === "new" ? [tag("new", "新", "new")] : tags, total: 1, offset: 0, limit: 40, has_more: false}));
    mount(); const search = screen.getByRole("searchbox", {name: "搜索标签"});
    fireEvent.change(search, {target: {value: "old"}});
    await waitFor(() => expect(api.listTags).toHaveBeenCalledWith(expect.objectContaining({q: "old"})));
    fireEvent.change(search, {target: {value: "new"}});
    await screen.findByText("新");
    resolveOld({items: [tag("old", "旧", "old")], total: 1, offset: 0, limit: 40, has_more: false});
    await waitFor(() => expect(screen.queryByText("旧")).not.toBeInTheDocument());
  });
  it("previews_import_options_before_commit", async () => {
    api.previewImport.mockImplementation(async (_document: unknown, options: {use_legacy_weights?: boolean}) => ({digest: options.use_legacy_weights ? "with-weight" : "plain", library_revision: 7, counts: {new: 1, existing: 0, invalid: 0, similar: 0, unmapped: 0, fragment_candidates: 0, legacy_weights: 1}, issues: []}));
    api.commitImport.mockResolvedValue({counts: {new: 1, existing: 0}, issues: [], library_revision: 8});
    mount(); fireEvent.click(screen.getByRole("button", {name: /导入 JSON/}));
    const file = new File([JSON.stringify({format: "anima-personal-tags", version: 1})], "sample.json", {type: "application/json"});
    Object.defineProperty(file, "text", {value: async () => JSON.stringify({format: "anima-personal-tags", version: 1})});
    fireEvent.change(screen.getByLabelText("选择本地 JSON 文件"), {target: {files: [file]}});
    await waitFor(() => expect(api.previewImport).toHaveBeenCalledWith(expect.any(Object), {use_legacy_weights: false, fragment_ids: []}));
    fireEvent.click(screen.getByRole("checkbox", {name: "将有效旧权重用作个人默认权重"}));
    await waitFor(() => expect(api.previewImport).toHaveBeenCalledWith(expect.any(Object), {use_legacy_weights: true, fragment_ids: []}));
    await screen.findByRole("button", {name: "确认导入"}); fireEvent.click(screen.getByRole("button", {name: "确认导入"}));
    await waitFor(() => expect(api.commitImport).toHaveBeenCalledWith(expect.any(Object), expect.objectContaining({use_legacy_weights: true}), "with-weight", 7));
  });
  it("uses_only_the_latest_selected_file_for_import_preview_and_commit", async () => {
    let finishOld!: (value: string) => void;
    api.previewImport.mockImplementation(async (document: {source_key: string}) => ({digest: document.source_key, library_revision: 4, counts: {new: 1, existing: 0, invalid: 0, similar: 0, unmapped: 0, fragment_candidates: 0, legacy_weights: 0}, issues: []}));
    api.commitImport.mockResolvedValue({counts: {new: 1, existing: 0}, issues: [], library_revision: 5});
    mount(); fireEvent.click(screen.getByRole("button", {name: /导入 JSON/}));
    const oldFile = new File(["{}"], "old.json", {type: "application/json"});
    const newFile = new File(["{}"], "new.json", {type: "application/json"});
    Object.defineProperty(oldFile, "text", {value: () => new Promise(resolve => {finishOld = resolve;})});
    Object.defineProperty(newFile, "text", {value: async () => JSON.stringify({source_key: "new"})});
    const chooser = screen.getByLabelText("选择本地 JSON 文件");
    fireEvent.change(chooser, {target: {files: [oldFile]}});
    fireEvent.change(chooser, {target: {files: [newFile]}});
    await waitFor(() => expect(api.previewImport).toHaveBeenCalledWith({source_key: "new"}, expect.any(Object)));
    finishOld(JSON.stringify({source_key: "old"}));
    await waitFor(() => expect(screen.getByText("文件：new.json")).toBeInTheDocument());
    expect(api.previewImport).not.toHaveBeenCalledWith({source_key: "old"}, expect.any(Object));
    fireEvent.click(await screen.findByRole("button", {name: "确认导入"}));
    await waitFor(() => expect(api.commitImport).toHaveBeenCalledWith({source_key: "new"}, expect.any(Object), "new", 4));
  });
  it("copies_exact_positive_and_negative_text", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {value: {writeText}, configurable: true});
    api.listTags.mockResolvedValue({items: [tag("one", "片段", "portrait,\nsoft_light")], total: 1, offset: 0, limit: 40, has_more: false});
    mount(); fireEvent.click(await screen.findByRole("button", {name: "加入正向 片段"}));
    fireEvent.click(screen.getByRole("button", {name: "加入负向 片段"}));
    fireEvent.click(screen.getByRole("button", {name: "复制完整提示词"}));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("Positive: portrait,\nsoft_light\nNegative: portrait,\nsoft_light"));
  });
  it("renders_imported_html_as_text", async () => {
    api.listTags.mockResolvedValue({items: [tag("html", "<img src=x onerror=alert(1)>", "<script>alert(1)</script>")], total: 1, offset: 0, limit: 40, has_more: false});
    mount(); expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(document.querySelector("img[src='x']")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
  });
  it("supports_category_cycle_error_and_failed_save_recovery", async () => {
    api.updateTag.mockRejectedValueOnce(new Error("revision_conflict"));
    api.updateTag.mockImplementation(async (_id: string, value: TagRecord) => ({...tags[0], ...value, revision: 2}));
    mount(); fireEvent.click(await screen.findByRole("button", {name: "管理词库"}));
    await screen.findByRole("table");
    fireEvent.click(await screen.findByRole("button", {name: "编辑 长发"}));
    fireEvent.change(await screen.findByRole("textbox", {name: "英文原文"}), {target: {value: "long, hair"}});
    fireEvent.click(screen.getByRole("button", {name: "保存修改"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("revision_conflict");
    expect(screen.getByRole("textbox", {name: "英文原文"})).toHaveValue("long, hair");
    fireEvent.click(screen.getByRole("button", {name: "保存修改"}));
    await waitFor(() => expect(api.updateTag).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", {name: "管理分类"}));
    fireEvent.change(screen.getByLabelText("选择分类"), {target: {value: "root"}});
    expect(within(screen.getByLabelText("上级分类")).queryByRole("option", {name: "头发"})).not.toBeInTheDocument();
    api.updateCategory.mockRejectedValueOnce(new Error("category_cycle"));
    fireEvent.change(screen.getByLabelText("分类名称"), {target: {value: "人物新版"}});
    fireEvent.click(screen.getByRole("button", {name: "保存分类"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("category_cycle");
    expect(screen.getByLabelText("分类名称")).toHaveValue("人物新版");
  });
  it("cancels_history_pop_without_losing_dirty_editor_then_confirms", async () => {
    const router = mount(["/workbench", "/personal-tags"]);
    fireEvent.click(await screen.findByRole("button", {name: "管理词库"}));
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", {name: "编辑 长发"}));
    fireEvent.change(await screen.findByRole("textbox", {name: "英文原文"}), {target: {value: "unsaved exact,\ncontent"}});
    const confirm = vi.mocked(window.confirm);
    confirm.mockReturnValueOnce(false).mockReturnValueOnce(true);
    await router.navigate(-1);
    await waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(router.state.location.pathname).toBe("/personal-tags");
    expect(screen.getByRole("textbox", {name: "英文原文"})).toHaveValue("unsaved exact,\ncontent");
    await router.navigate(-1);
    expect(await screen.findByText("工作台内容")).toBeInTheDocument();
  });
  it("holds_history_pop_until_draft_flush_and_stays_on_failed_flush", async () => {
    let resolveSave!: (value: unknown) => void;
    api.saveDraft.mockImplementationOnce(() => new Promise(resolve => {resolveSave = resolve;}));
    const router = mount(["/workbench", "/personal-tags"]);
    fireEvent.click(await screen.findByRole("button", {name: "加入正向 长发"}));
    await waitFor(() => expect(api.saveDraft).toHaveBeenCalled());
    void router.navigate(-1);
    await waitFor(() => expect(router.state.blockers.size).toBeGreaterThan(0));
    expect(router.state.location.pathname).toBe("/personal-tags");
    resolveSave({items: [], revision: 2, updated_at: ""});
    expect(await screen.findByText("工作台内容")).toBeInTheDocument();

    api.saveDraft.mockRejectedValue(new Error("save unavailable"));
    await router.navigate("/personal-tags");
    fireEvent.click(await screen.findByRole("button", {name: "加入正向 长发"}));
    await waitFor(() => expect(api.saveDraft).toHaveBeenCalledTimes(2));
    await router.navigate(-1);
    expect(router.state.location.pathname).toBe("/personal-tags");
    expect(await screen.findByText(/组合草稿尚未保存/)).toBeInTheDocument();
  });
  it("allows_mode_switch_and_pop_when_initial_draft_load_failed_without_local_edits", async () => {
    api.getDraft.mockRejectedValue(new Error("draft unavailable"));
    const router = mount(["/workbench", "/personal-tags"]);
    await screen.findByText("draft unavailable");
    fireEvent.click(screen.getByRole("button", {name: "管理词库"}));
    expect(await screen.findByRole("table")).toBeInTheDocument();
    await router.navigate(-1);
    expect(await screen.findByText("工作台内容")).toBeInTheDocument();
    expect(api.saveDraft).not.toHaveBeenCalled();
  });
  it("never_offers_deleted_tags_in_picker_after_leaving_trash", async () => {
    api.listTags.mockImplementation(async ({trash}: {trash?: boolean}) => ({items: trash ? [{...tags[0], deleted_at: "now"}] : [tags[1]], total: 1, offset: 0, limit: 40, has_more: false}));
    mount(); fireEvent.click(screen.getByRole("button", {name: "管理词库"}));
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("checkbox", {name: "回收站"}));
    await waitFor(() => expect(api.listTags).toHaveBeenCalledWith(expect.objectContaining({trash: true})));
    fireEvent.click(screen.getByRole("button", {name: "挑选标签"}));
    await waitFor(() => expect(api.listTags).toHaveBeenLastCalledWith(expect.objectContaining({trash: false})));
    expect(screen.queryByRole("button", {name: "加入正向 长发"})).not.toBeInTheDocument();
    expect(await screen.findByRole("button", {name: "加入正向 短发"})).toBeInTheDocument();
  });
});
