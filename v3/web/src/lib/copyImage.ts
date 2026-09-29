import {apiRequest} from "./api";

/** The local service writes both a Windows file list and image data together. */
export async function copyImageFileToClipboard(path: string): Promise<void> {
  const result = await apiRequest<{copied: boolean; file_name: string}>("/api/v3/gallery/assets/clipboard", {
    method: "POST", body: JSON.stringify({path}),
  });
  if (result.copied !== true) throw new Error("未能复制原图文件，请重试。");
}
