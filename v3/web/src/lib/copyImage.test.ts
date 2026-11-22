import {beforeEach, expect, it, vi} from "vitest";
import {apiRequest} from "./api";
import {copyImageFileToClipboard} from "./copyImage";

vi.mock("./api", () => ({apiRequest: vi.fn()}));
beforeEach(() => {vi.mocked(apiRequest).mockReset();});

it("asks the local service to copy the original file with its exact gallery path", async () => {
  vi.mocked(apiRequest).mockResolvedValue({copied: true, file_name: "原图 1.png"});
  await copyImageFileToClipboard("中文目录/原图 1.png");
  expect(apiRequest).toHaveBeenCalledExactlyOnceWith("/api/v3/gallery/assets/clipboard", {
    method: "POST", body: JSON.stringify({path: "中文目录/原图 1.png"}),
  });
});

it("keeps native failures visible instead of falling back to image-only copying", async () => {
  vi.mocked(apiRequest).mockRejectedValue(new Error("剪贴板正忙，请稍后重试。"));
  await expect(copyImageFileToClipboard("batch/one.png")).rejects.toThrow("剪贴板正忙");
  expect(apiRequest).toHaveBeenCalledTimes(1);
});

it("does not claim success unless the service confirms the file copy", async () => {
  vi.mocked(apiRequest).mockResolvedValue({copied: false});
  await expect(copyImageFileToClipboard("batch/one.png")).rejects.toThrow("未能复制原图文件");
});
