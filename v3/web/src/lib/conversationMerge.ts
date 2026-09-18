import type {LocalConversation} from "./conversation";

export interface ConversationConflict {
  path: string;
  label: string;
  base: unknown;
  local: unknown;
  remote: unknown;
}

export interface ConversationMergeResult {
  merged: LocalConversation;
  conflicts: ConversationConflict[];
}

export type ConversationConflictChoices = Record<string, "local" | "remote">;

const labels: Record<string, string> = {
  delta: "未发送的修改", positive: "正向提示词", negative: "负向提示词", mode: "改写方式", model: "模型",
  "requirements.layers.subject.text": "主体要求", "requirements.layers.style.text": "风格要求",
  "requirements.layers.lighting.text": "光影要求", "requirements.layers.composition.text": "构图要求",
  "requirements.layers.exclusions.global": "全局排除", "requirements.layers.exclusions.scoped": "局部排除",
};

const leafLabels: Record<string, string> = {
  locked: "锁定设置", include_with_style_pin: "随风格引用", medium: "媒介", artists: "画师",
  character_tags: "角色标签", series_tags: "系列标签", general_tags: "普通标签", manual_artist_tags: "手动画师标签",
  shot: "景别", loras: "LoRA", settings: "生成设置",
};
const settingLabels: Record<string, string> = {preset_id: "配方", aspect: "画幅", width: "宽度", height: "高度", steps: "步数",
  cfg: "CFG", sampler: "采样器", scheduler: "调度器", seed: "种子", batch_size: "张数",
  remote_profile_id: "服务器", workflow_profile_id: "工作流"};

function labelFor(path: string): string {
  if (path.startsWith("settings.")) return `生成设置 · ${settingLabels[path.slice("settings.".length)] || path.slice("settings.".length)}`;
  return labels[path] || leafLabels[path.split(".").at(-1) || ""] || path;
}

function same(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (left === undefined || right === undefined) return false;
  return JSON.stringify(left) === JSON.stringify(right);
}

function plainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function clone<T>(value: T): T {
  return value === undefined ? value : structuredClone(value);
}

function mergeValue(base: unknown, local: unknown, remote: unknown, path: string, conflicts: ConversationConflict[]): unknown {
  if (same(local, remote)) return clone(local);
  if (same(local, base)) return clone(remote);
  if (same(remote, base)) return clone(local);
  if (plainObject(base) && plainObject(local) && plainObject(remote)) {
    const result: Record<string, unknown> = {};
    for (const key of new Set([...Object.keys(base), ...Object.keys(local), ...Object.keys(remote)])) {
      const value = mergeValue(base[key], local[key], remote[key], path ? `${path}.${key}` : key, conflicts);
      if (value !== undefined) result[key] = value;
    }
    return result;
  }
  conflicts.push({path, label: labelFor(path), base: clone(base), local: clone(local), remote: clone(remote)});
  return clone(remote);
}

export function mergeConversation(base: LocalConversation, local: LocalConversation, remote: LocalConversation): ConversationMergeResult {
  const conflicts: ConversationConflict[] = [];
  const merged = mergeValue(base, local, remote, "", conflicts) as LocalConversation;
  // Revisions are concurrency metadata, not user content. Always continue from the server revision.
  merged.baseRevision = remote.baseRevision;
  return {merged, conflicts: conflicts.filter(conflict => conflict.path !== "baseRevision")};
}

function setPath(target: Record<string, unknown>, path: string, value: unknown): void {
  const parts = path.split(".");
  let parent = target;
  for (const part of parts.slice(0, -1)) parent = parent[part] as Record<string, unknown>;
  const leaf = parts.at(-1)!;
  if (value === undefined) delete parent[leaf];
  else parent[leaf] = clone(value);
}

export function resolveConversationConflicts(result: ConversationMergeResult, choices: ConversationConflictChoices): LocalConversation {
  const resolved = structuredClone(result.merged) as unknown as Record<string, unknown>;
  for (const conflict of result.conflicts) {
    setPath(resolved, conflict.path, choices[conflict.path] === "local" ? conflict.local : conflict.remote);
  }
  return resolved as unknown as LocalConversation;
}
