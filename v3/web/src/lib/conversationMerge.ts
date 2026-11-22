import type {LocalConversation} from "./conversation";
import {configurationFromSettings,resolveConfiguration} from "./creationConfiguration";
import {modelProfileChoices} from "./modelProfiles";
import {basicWorkflowSchema} from "./workflowParameterSchema";

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

const generationPath = "generationConditions";
const atomicPaths = new Set([generationPath,"requirements.layers.style.artist_preset","artistPresetPlacement"]);
type GenerationConditions = Pick<LocalConversation,"model"|"settings"|"workflowSnapshotRunId"> & {loras:LocalConversation["requirements"]["loras"]};

function generationConditions(draft: LocalConversation): GenerationConditions {
  return {model:draft.model,settings:draft.settings,workflowSnapshotRunId:draft.workflowSnapshotRunId ?? null,loras:draft.requirements.loras};
}

function withGenerationConditions(draft: LocalConversation, conditions: GenerationConditions): LocalConversation {
  const {loras,...generation} = conditions;
  return {...draft,...generation,requirements:{...draft.requirements,loras}};
}

const labels: Record<string, string> = {
  [generationPath]: "模型与生成条件",
  delta: "未发送的修改", positive: "正向提示词", negative: "负向提示词", mode: "改写方式", model: "模型",
  "requirements.layers.subject.text": "主体要求", "requirements.layers.style.text": "风格要求",
  "requirements.layers.lighting.text": "光影要求", "requirements.layers.composition.text": "构图要求",
  "requirements.layers.exclusions.global": "全局排除", "requirements.layers.exclusions.scoped": "局部排除",
  "requirements.layers.style.artist_preset": "画师串版本", artistPresetPlacement: "画师串位置",
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
  if (Array.isArray(left) && Array.isArray(right)) return left.length === right.length && left.every((item,i)=>same(item,right[i]));
  if (plainObject(left) && plainObject(right)) {
    return [...new Set([...Object.keys(left),...Object.keys(right)])].every(key=>same(left[key],right[key]));
  }
  return false;
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
  if (!atomicPaths.has(path) && plainObject(base) && plainObject(local) && plainObject(remote)) {
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
  if (local.model !== remote.model) {
    const selected = mergeValue(generationConditions(base),generationConditions(local),generationConditions(remote),generationPath,conflicts) as GenerationConditions;
    // Merge the remaining prompt and tag edits with the same complete conditions on all three drafts.
    base = withGenerationConditions(base,selected);
    local = withGenerationConditions(local,selected);
    remote = withGenerationConditions(remote,selected);
  }
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
  let resolved = structuredClone(result.merged);
  for (const conflict of result.conflicts) {
    const selected = choices[conflict.path] === "local" ? conflict.local : conflict.remote;
    if (conflict.path === generationPath) resolved = withGenerationConditions(resolved,clone(selected as GenerationConditions));
    else setPath(resolved as unknown as Record<string,unknown>,conflict.path,selected);
  }
  return resolved;
}

export function conflictValueLabel(conflict: ConversationConflict, side: "local" | "remote"): string {
  const value = conflict[side];
  if (conflict.path !== generationPath) return typeof value === "string" ? value : JSON.stringify(value) ?? "";
  const {model,settings,loras} = value as GenerationConditions;
  const config = configurationFromSettings(settings,model,undefined,{preserveSnapshot:true});
  const schema = settings.parameter_schema || basicWorkflowSchema(config.workflow.id,config.workflow.revision);
  const {width,height,steps,cfg} = resolveConfiguration(config,schema).values;
  const name = modelProfileChoices().find(item=>item.id === model)?.label || model;
  return [name,config.workflow.id || "未选工作流",`${width ?? "?"}×${height ?? "?"}`,`${steps ?? "?"} 步`,`CFG ${cfg ?? "?"}`,`LoRA ${loras.length}`].join(" · ");
}
