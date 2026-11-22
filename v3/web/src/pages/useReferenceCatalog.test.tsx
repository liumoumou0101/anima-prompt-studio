import {act, renderHook, waitFor} from "@testing-library/react";
import {beforeEach, expect, it, vi} from "vitest";
import {ApiClientError, apiRequest} from "../lib/api";
import {useReferenceCatalog} from "./useReferenceCatalog";

vi.mock("../lib/api", async importOriginal => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {...actual, apiRequest: vi.fn()};
});

type Item = {id: string; title: string};
const pack = {ready: true};
const deferred = <T,>() => {let resolve!: (value: T) => void; let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {resolve = yes; reject = no;}); return {promise, resolve, reject};};

beforeEach(() => vi.mocked(apiRequest).mockReset());

it("ignores an older first page that resolves after a changed filter", async () => {
  const oldPage = deferred<unknown>(); const newPage = deferred<unknown>();
  vi.mocked(apiRequest).mockReturnValueOnce(oldPage.promise).mockReturnValueOnce(newPage.promise);
  const {result, rerender} = renderHook(({origin}) => useReferenceCatalog<Item>({enabled: true, filters: {q: "", origin}}), {initialProps: {origin: "old"}});
  rerender({origin: "new"});
  await act(async () => newPage.resolve({items:[{id:"new",title:"new"}],next_cursor:null,official_pack:pack,total:1}));
  await waitFor(() => expect(result.current.page?.items[0].id).toBe("new"));
  await act(async () => oldPage.resolve({items:[{id:"old",title:"old"}],next_cursor:null,official_pack:pack,total:1}));
  expect(result.current.page?.items[0].id).toBe("new");
});

it("singleflights a cursor, deduplicates appended ids, and stops at the end", async () => {
  const next = deferred<unknown>();
  vi.mocked(apiRequest)
    .mockResolvedValueOnce({items:[{id:"a",title:"a"}],next_cursor:"c1",official_pack:pack,total:2})
    .mockReturnValueOnce(next.promise);
  const {result} = renderHook(() => useReferenceCatalog<Item>({enabled: true, filters: {q: ""}}));
  await waitFor(() => expect(result.current.page?.next_cursor).toBe("c1"));
  act(() => {void result.current.loadMore(); void result.current.loadMore();});
  expect(apiRequest).toHaveBeenCalledTimes(2);
  await act(async () => next.resolve({items:[{id:"a",title:"duplicate"},{id:"b",title:"b"}],next_cursor:null,official_pack:pack,total:2}));
  await waitFor(() => expect(result.current.page?.items.map(item => item.id)).toEqual(["a","b"]));
  await act(async () => {await result.current.loadMore();});
  expect(apiRequest).toHaveBeenCalledTimes(2);
});

it("pauses automatic pagination after failure and retries only explicitly", async () => {
  vi.mocked(apiRequest)
    .mockResolvedValueOnce({items:[{id:"a",title:"a"}],next_cursor:"c1",official_pack:pack,total:2})
    .mockRejectedValueOnce(new Error("temporary"))
    .mockResolvedValueOnce({items:[{id:"b",title:"b"}],next_cursor:null,official_pack:pack,total:2});
  const {result} = renderHook(() => useReferenceCatalog<Item>({enabled: true, filters: {q: ""}}));
  await waitFor(() => expect(result.current.page?.next_cursor).toBe("c1"));
  await act(async () => {await result.current.loadMore();});
  expect(result.current.error?.phase).toBe("more");
  await act(async () => {await result.current.loadMore();});
  expect(apiRequest).toHaveBeenCalledTimes(2);
  await act(async () => {await result.current.retry();});
  expect(result.current.page?.items.map(item => item.id)).toEqual(["a","b"]);
});

it("refreshes the first page on an explicit stale-cursor retry", async () => {
  vi.mocked(apiRequest)
    .mockResolvedValueOnce({items:[{id:"a",title:"a"}],next_cursor:"old",official_pack:pack,total:2})
    .mockRejectedValueOnce(new ApiClientError("changed", "reference_version_conflict"))
    .mockResolvedValueOnce({items:[{id:"fresh",title:"fresh"}],next_cursor:null,official_pack:pack,total:1});
  const {result} = renderHook(() => useReferenceCatalog<Item>({enabled: true, filters: {q: ""}}));
  await waitFor(() => expect(result.current.page?.next_cursor).toBe("old"));
  await act(async () => {await result.current.loadMore();});
  await act(async () => {await result.current.retry();});
  expect(result.current.page?.items[0].id).toBe("fresh");
  expect(String(vi.mocked(apiRequest).mock.calls[2][0])).not.toContain("cursor=");
});

it("does not let an aborted old cursor request release a newer request for the same cursor", async () => {
  const oldMore = deferred<unknown>(); const newMore = deferred<unknown>();
  vi.mocked(apiRequest)
    .mockResolvedValueOnce({items:[{id:"a",title:"a"}],next_cursor:"same",official_pack:pack,total:2})
    .mockReturnValueOnce(oldMore.promise)
    .mockResolvedValueOnce({items:[{id:"a",title:"a"}],next_cursor:"same",official_pack:pack,total:2})
    .mockReturnValueOnce(newMore.promise);
  const {result} = renderHook(() => useReferenceCatalog<Item>({enabled: true, filters: {q: ""}}));
  await waitFor(() => expect(result.current.page?.next_cursor).toBe("same"));
  act(() => {void result.current.loadMore();});
  await act(async () => {await result.current.refresh();});
  act(() => {void result.current.loadMore();});
  await act(async () => oldMore.resolve({items:[{id:"old",title:"old"}],next_cursor:null,official_pack:pack,total:2}));
  await act(async () => {await result.current.loadMore();});
  expect(apiRequest).toHaveBeenCalledTimes(4);
  await act(async () => newMore.resolve({items:[{id:"b",title:"b"}],next_cursor:null,official_pack:pack,total:2}));
  expect(result.current.page?.items.map(item => item.id)).toEqual(["a","b"]);
});
