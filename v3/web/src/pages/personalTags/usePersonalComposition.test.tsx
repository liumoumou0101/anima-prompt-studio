import {act, renderHook, waitFor} from "@testing-library/react";
import {beforeEach, expect, it, vi} from "vitest";
import {ApiClientError} from "../../lib/api";
import {personalTagsApi, type CompositionItem, type DraftRecord} from "../../lib/personalTags";
import {usePersonalComposition} from "./usePersonalComposition";

vi.mock("../../lib/personalTags", async importOriginal => {
  const actual = await importOriginal<typeof import("../../lib/personalTags")>();
  return {...actual, personalTagsApi: {...actual.personalTagsApi, getDraft: vi.fn(), saveDraft: vi.fn()}};
});

const entry = (id: string): CompositionItem => ({id, source_tag_id: id, display_name: id,
  content: id, kind: "tag", polarity: "positive", weight: 1});
const draft = (items: CompositionItem[] = [], revision = 0): DraftRecord => ({items, revision, updated_at: ""});
const deferred = <T,>() => {let resolve!: (value: T) => void; let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {resolve = yes; reject = no;}); return {promise, resolve, reject};};

beforeEach(() => {localStorage.clear(); vi.mocked(personalTagsApi.getDraft).mockReset();
  vi.mocked(personalTagsApi.saveDraft).mockReset();});

it("restores_unsaved_composition_after_reload", async () => {
  const pending = deferred<DraftRecord>();
  vi.mocked(personalTagsApi.getDraft).mockResolvedValue(draft());
  vi.mocked(personalTagsApi.saveDraft).mockReturnValue(pending.promise);
  const first = renderHook(() => usePersonalComposition());
  await waitFor(() => expect(first.result.current.saveState).toBe("saved"));
  act(() => first.result.current.setItems([entry("unsaved")]));
  await waitFor(() => expect(personalTagsApi.saveDraft).toHaveBeenCalledWith([entry("unsaved")], 0));
  expect(localStorage.getItem("anima-personal-composition-draft:v1")).toContain("unsaved");
  first.unmount();
  const second = renderHook(() => usePersonalComposition());
  await waitFor(() => expect(second.result.current.items).toEqual([entry("unsaved")]));
  expect(second.result.current.saveState).not.toBe("saved");
  await act(async () => pending.resolve(draft([entry("unsaved")], 1)));
  second.unmount();
});

it("serializes_saves_and_preserves_draft_on_conflict", async () => {
  const firstSave = deferred<DraftRecord>();
  vi.mocked(personalTagsApi.getDraft).mockResolvedValue(draft());
  vi.mocked(personalTagsApi.saveDraft).mockReturnValueOnce(firstSave.promise)
    .mockRejectedValueOnce(new ApiClientError("changed", "revision_conflict", undefined, false,
      {current_revision: 4, current: draft([entry("remote")], 4)}));
  const {result} = renderHook(() => usePersonalComposition());
  await waitFor(() => expect(result.current.saveState).toBe("saved"));
  act(() => result.current.setItems([entry("first")]));
  await waitFor(() => expect(personalTagsApi.saveDraft).toHaveBeenCalledTimes(1));
  act(() => result.current.setItems([entry("first"), entry("latest")]));
  expect(personalTagsApi.saveDraft).toHaveBeenCalledTimes(1);
  await act(async () => firstSave.resolve(draft([entry("first")], 1)));
  await waitFor(() => expect(personalTagsApi.saveDraft).toHaveBeenCalledTimes(2));
  expect(vi.mocked(personalTagsApi.saveDraft).mock.calls[1]).toEqual([[entry("first"), entry("latest")], 1]);
  await waitFor(() => expect(result.current.saveState).toBe("conflict"));
  expect(result.current.items).toEqual([entry("first"), entry("latest")]);
  expect(localStorage.getItem("anima-personal-composition-draft:v1")).toContain("latest");
  expect(await act(async () => result.current.flush())).toBe(false);
  expect(personalTagsApi.saveDraft).toHaveBeenCalledTimes(2);
  vi.mocked(personalTagsApi.getDraft).mockResolvedValueOnce(draft([entry("remote")], 4));
  await act(async () => result.current.reload());
  expect(result.current.items).toEqual([entry("remote")]);
  expect(result.current.saveState).toBe("saved");
});

it("flushes_the_latest_edit_after_an_earlier_request_completes", async () => {
  const firstSave = deferred<DraftRecord>();
  vi.mocked(personalTagsApi.getDraft).mockResolvedValue(draft());
  vi.mocked(personalTagsApi.saveDraft).mockReturnValueOnce(firstSave.promise)
    .mockResolvedValueOnce(draft([entry("one"), entry("two")], 2));
  const {result} = renderHook(() => usePersonalComposition());
  await waitFor(() => expect(result.current.saveState).toBe("saved"));
  act(() => result.current.setItems([entry("one")]));
  await waitFor(() => expect(personalTagsApi.saveDraft).toHaveBeenCalledTimes(1));
  act(() => result.current.setItems(previous => [...previous, entry("two")]));
  let completion!: Promise<boolean>;
  act(() => {completion = result.current.flush();});
  await act(async () => firstSave.resolve(draft([entry("one")], 1)));
  expect(await act(async () => completion)).toBe(true);
  expect(vi.mocked(personalTagsApi.saveDraft).mock.calls).toEqual([
    [[entry("one")], 0], [[entry("one"), entry("two")], 1],
  ]);
  expect(result.current.saveState).toBe("saved");
  expect(localStorage.getItem("anima-personal-composition-draft:v1")).toBeNull();
});

it("preserves_local_edits_if_the_server_advanced_during_initial_load", async () => {
  const incoming = deferred<DraftRecord>();
  vi.mocked(personalTagsApi.getDraft).mockReturnValue(incoming.promise);
  const {result} = renderHook(() => usePersonalComposition());
  act(() => result.current.setItems([entry("mine")]));
  await act(async () => incoming.resolve(draft([entry("remote")], 3)));
  expect(result.current.items).toEqual([entry("mine")]);
  expect(result.current.saveState).toBe("conflict");
  expect(personalTagsApi.saveDraft).not.toHaveBeenCalled();
});

it("retries_a_failed_save_without_dropping_the_draft", async () => {
  vi.mocked(personalTagsApi.getDraft).mockResolvedValue(draft());
  vi.mocked(personalTagsApi.saveDraft).mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce(draft([entry("kept")], 1));
  const {result} = renderHook(() => usePersonalComposition());
  await waitFor(() => expect(result.current.saveState).toBe("saved"));
  act(() => result.current.setItems([entry("kept")]));
  await waitFor(() => expect(result.current.saveState).toBe("error"));
  expect(result.current.items).toEqual([entry("kept")]);
  expect(localStorage.getItem("anima-personal-composition-draft:v1")).toContain("kept");
  expect(await act(async () => result.current.flush())).toBe(true);
  expect(personalTagsApi.saveDraft).toHaveBeenCalledTimes(2);
  expect(result.current.saveState).toBe("saved");
});
