import type {GenerationTarget} from "./types";

type WorkflowIdentity = {
  workflow_id: string;
  display_name: string;
  origin?: string;
  workflow_kind?: string;
  experimental?: boolean;
};

// Only catalog-confirmed built-ins are translated. A user can keep a packaged ID
// for a modified template, so the ID alone is never proof of official ownership.
const officialWorkflowNames: Record<string, string> = {
  "23_Turbo_v1.1": "ANIMA Turbo v1.1 · 基础版",
  "24_AnimaYume_v1.0_Final": "AnimaYume v1.0 Final · 基础版",
  "25_MiaoMiao_Harem_ANIMA_v1.6": "MiaoMiao Harem ANIMA v1.6 · 基础版",
  "26_Turbo_v1.1": "ANIMA Turbo v1.1 · 社区优化实验版",
  "27_AnimaYume": "AnimaYume v1.0 Final · 社区优化实验版",
  "28_MiaoMiao": "MiaoMiao Harem ANIMA v1.6 · 社区优化实验版",
  v3_base_v1: "ANIMA Base v1.0 · 基础版",
  v3_aesthetic_v1_0: "ANIMA Aesthetic v1.0 · 基础版",
  v3_aesthetic_v1_1: "ANIMA Aesthetic v1.1 · 基础版",
  v3_anima_2_9b_preview_v1: "Anima 2.9B Preview v1 · 作者参数基线",
  v3_animayume_v1_5_base: "AnimaYume v1.5 Base · 作者参数基线",
};

// Translate only exact packaged notes. Extended or user-authored notes stay intact.
const officialWorkflowNotes: Record<string, string> = {
  "Packaged verified ANIMA Turbo v1.1 baseline. Uses 10 steps, CFG 1, er_sde, simple scheduler, and no legacy Turbo LoRA.":
    "ANIMA Turbo v1.1 基础版采用 10 步、CFG 1、er_sde 采样器和 simple 调度器，不使用旧版 Turbo LoRA。",
  "Packaged community optimization for ANIMA Turbo v1.1. Requires the verified NAG and Layer Replay custom nodes on the ComfyUI host.":
    "ANIMA Turbo v1.1 社区优化版，需要在 ComfyUI 环境中安装兼容的 NAG 和 Layer Replay 自定义节点。",
  "Packaged verified ANIMA community workflow. Imported only when the local database has no workflow with the same ID.":
    "内置 ANIMA 社区模型模板，使用前请确认当前环境中的模型文件和节点依赖。",
  "V3 maintained baseline; recommended parameters are editable. Server capability validation and image-quality comparison required.":
    "V3 维护的基础版，推荐参数可调整；请检测执行环境，并通过图片对照确认效果。",
};

export function workflowName(workflow: WorkflowIdentity): string {
  const id = workflow.workflow_id.replace(/^official:/, "");
  return workflow.origin === "official" ? officialWorkflowNames[id] || workflow.display_name : workflow.display_name;
}

function workflowType(workflow: WorkflowIdentity): string {
  if (workflow.workflow_kind === "txt2img_basic") return "文生图";
  if (workflow.workflow_kind === "txt2img_hiresfix_1_5x") return "文生图 + 1.5 倍放大";
  return workflow.workflow_kind || "类型待确认";
}

function workflowBaseLabel(workflow: WorkflowIdentity): string {
  const origin = workflow.origin;
  const source = origin === "official" ? "内置" : origin === "user" ? "用户模板" : "来源待确认";
  const name = workflowName(workflow);
  return `${name}${workflow.experimental && !name.includes("实验") ? " · 实验" : ""} · ${workflowType(workflow)} · ${source}`;
}

export function workflowLabel(workflow: WorkflowIdentity, peers: WorkflowIdentity[] = []): string {
  const label = workflowBaseLabel(workflow);
  const duplicate = peers.some(peer => peer.workflow_id !== workflow.workflow_id && workflowBaseLabel(peer) === label);
  return duplicate ? `${label} · ${workflow.workflow_id}` : label;
}

function targetWorkflow(target: GenerationTarget): WorkflowIdentity {
  return {workflow_id: target.workflow_profile_id, display_name: target.workflow_display_name,
    origin: target.workflow_origin, workflow_kind: target.workflow_kind, experimental: target.experimental};
}

export function targetLabel(target: GenerationTarget, peers: GenerationTarget[] = []): string {
  return workflowLabel(targetWorkflow(target), peers.filter(peer => peer.remote_profile_id === target.remote_profile_id).map(targetWorkflow));
}

function targetEndpoint(target: GenerationTarget): string {
  const local = target.connection_type === "local";
  const host = (local ? target.remote_comfy_host : target.remote_ssh_host)?.trim();
  if (!host) return "";
  const address = host.includes(":") && !host.startsWith("[") ? `[${host}]` : host;
  const port = local ? target.remote_comfy_port : target.remote_ssh_port;
  return `${local ? "http://" : ""}${address}${port ? `:${port}` : ""}`;
}

export function targetRemoteLabel(target: GenerationTarget, peers: GenerationTarget[] = []): string {
  const duplicates = peers.filter(peer => peer.remote_profile_id !== target.remote_profile_id && peer.remote_display_name === target.remote_display_name);
  if (!duplicates.length) return target.remote_display_name;
  const endpoint = targetEndpoint(target);
  const label = `${target.remote_display_name}${endpoint ? ` · ${endpoint}` : ""}`;
  const sameEndpoint = duplicates.filter(peer => targetEndpoint(peer) === endpoint);
  if (endpoint && !sameEndpoint.length) return label;
  const shortId = target.remote_profile_id.slice(0, 8);
  const id = sameEndpoint.some(peer => peer.remote_profile_id.slice(0, 8) === shortId) ? target.remote_profile_id : shortId;
  return `${label} · 连接 ${id}`;
}

export function targetDescription(target: GenerationTarget): string {
  const kind = target.workflow_kind === "txt2img_hiresfix_1_5x" ? "先生成图片，再放大到 1.5 倍并细化。" : `${workflowType(targetWorkflow(target))}流程。`;
  const variant = target.experimental ? "含实验优化节点，需确认执行环境支持；可先选同模型的基础版进行对照。" : "";
  const notes = target.workflow_notes?.trim() || "";
  const official = target.workflow_origin === "official" && officialWorkflowNames[target.workflow_profile_id.replace(/^official:/, "")];
  const description = official ? officialWorkflowNotes[notes] || notes : notes;
  return `${kind}${variant}${description ? ` ${description} ` : ""}模板标识：${target.workflow_profile_id}`;
}

export function targetReady(target: GenerationTarget): boolean {
  // Older API adapters did not expose availability; production V3 now always does.
  return target.availability === undefined || target.availability === "ready";
}

export function defaultTarget(targets: GenerationTarget[]): GenerationTarget | undefined {
  return targets.find(target => targetReady(target) && !target.experimental)
    || targets.find(target => !target.experimental && target.availability !== "disabled");
}

export function targetStatus(target: GenerationTarget): string {
  const labels: Record<string, string> = {unchecked: "待检测", stale: "检测已过期", connection_failed: "连接检测失败", missing_nodes: "缺少节点", invalid_inputs: "资产或参数不匹配", mapping_stale: "映射需确认", disabled: "已停用"};
  return targetReady(target) ? "" : labels[target.availability || ""] || "未就绪";
}
