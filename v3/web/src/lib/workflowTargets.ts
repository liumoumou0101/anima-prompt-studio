import type {GenerationTarget} from "./types";

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
