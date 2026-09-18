export interface ComparisonBaseline {
  version: 1;
  workspaceId: string;
  runId: string;
  artifactId: string;
}

function storageKey(workspaceId: string): string {
  return `anima-v3-comparison-baseline:${encodeURIComponent(workspaceId)}`;
}
function validId(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= 512 && !/[\u0000-\u001f]/.test(value);
}

export function readComparisonBaseline(workspaceId?: string): {value: ComparisonBaseline | null; warning: string} {
  if (!workspaceId) return {value: null, warning: ""};
  let raw: string | null;
  try { raw = localStorage.getItem(storageKey(workspaceId)); }
  catch { return {value: null, warning: "无法读取本机保存的对比基准。仍可选择图片进行本次对比。"}; }
  if (!raw) return {value: null, warning: ""};
  try {
    const value: unknown = JSON.parse(raw);
    if (value && typeof value === "object" && "version" in value && value.version === 1
      && "workspaceId" in value && value.workspaceId === workspaceId
      && "runId" in value && validId(value.runId) && "artifactId" in value && validId(value.artifactId)) {
      return {value: {version: 1, workspaceId, runId: value.runId, artifactId: value.artifactId}, warning: ""};
    }
  } catch { /* Invalid saved values must not prevent comparison. */ }
  return {value: null, warning: "保存的对比基准记录无效，已忽略。请重新选择基准图片。"};
}

export function saveComparisonBaseline(workspaceId: string | undefined, runId: string, artifactId: string): string {
  if (!workspaceId) return "";
  try {
    // Keep only identifiers; image URLs, prompts and credentials never belong here.
    localStorage.setItem(storageKey(workspaceId), JSON.stringify({version: 1, workspaceId, runId, artifactId}));
    return "";
  } catch { return "无法保存对比基准。当前仍可对比，但刷新或离开后可能无法恢复。"; }
}

export function clearComparisonBaseline(workspaceId?: string): string {
  if (!workspaceId) return "";
  try { localStorage.removeItem(storageKey(workspaceId)); return ""; }
  catch { return "无法清除已保存的对比基准。已清除本次对比，但刷新后旧基准可能重新出现。"; }
}
