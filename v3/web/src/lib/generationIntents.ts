import {apiRequest} from './api';
import {notifyLoraEnvironmentChanged} from './loraLibrary';
import type {ExecutionPolicy, GenerationRunRecord} from './types';
export type {ExecutionPolicy} from './types';

export interface GenerationIntentRequest {
  source: Record<string, unknown>;
  creationConfiguration: {workflow: {id: string; revision: string}; modelProfile?: string; [key: string]: unknown};
  executionPolicy: ExecutionPolicy;
}
export interface CandidateEvidence {
  eligible: boolean; reasons: string[]; signature?: string;
  probe: {environment_id: string; environment_epoch: number; checked_at: number; connection_state: string;
    capabilities_state: string; reason_codes: string[]; identity_strength?: string};
}
export interface GenerationIntentRecord {
  id: string; state: 'resolving' | 'blocked' | 'accepted' | 'canceled'; retryable: boolean; reason: string | null;
  candidate_progress: {order?: string[]; checked?: Record<string, CandidateEvidence>; unchecked?: string[]; cursor?: number; round?: number;
    input_error?: {message: string; fields?: Record<string, string> | null}};
  resolved_target: {id: string; display_name?: string; epoch?: number; workflow?: {id: string; revision: string}} | null;
  submission_id: string | null; run_id: string | null; response: GenerationRunRecord | null; updated_at: number;
}
export interface PendingGenerationIntent {
  protocol: 'intent-v1'; clientRequestId: string; body: GenerationIntentRequest; intentId?: string;
}

export function createGenerationIntent(body: GenerationIntentRequest, clientRequestId: string): Promise<GenerationIntentRecord> {
  return apiRequest('/api/v3/generation-intents', {method: 'POST', headers: {'Idempotency-Key': clientRequestId}, body: JSON.stringify(body)});
}
export function getGenerationIntent(id: string): Promise<GenerationIntentRecord> {
  return apiRequest(`/api/v3/generation-intents/${encodeURIComponent(id)}`);
}
export function retryGenerationIntent(id: string): Promise<GenerationIntentRecord> {
  return apiRequest(`/api/v3/generation-intents/${encodeURIComponent(id)}/retry-resolution`, {method: 'POST'});
}
export function cancelGenerationIntent(id: string): Promise<GenerationIntentRecord> {
  return apiRequest(`/api/v3/generation-intents/${encodeURIComponent(id)}/cancel`, {method: 'POST'});
}
export function confirmEnvironmentAssets(environmentId: string, workflow: {id: string; revision: string}, intentId?: string): Promise<{confirmed: boolean}> {
  return apiRequest(`/api/v3/execution-environments/${encodeURIComponent(environmentId)}/confirm-assets`, {
    method: 'POST', body: JSON.stringify({workflow_id: workflow.id, revision: workflow.revision, ...(intentId ? {intent_id: intentId} : {})})});
}
export async function markEnvironmentRebuilt(environmentId: string): Promise<{environment_epoch: number}> {
  const result=await apiRequest<{environment_epoch:number}>(`/api/v3/execution-environments/${encodeURIComponent(environmentId)}/rebuilt`, {method:'POST'});
  notifyLoraEnvironmentChanged(environmentId);
  return result;
}

/** Recovery always queries the original receipt; an uncertain POST reuses its frozen key/body. */
export function recoverGenerationIntent(pending: PendingGenerationIntent): Promise<GenerationIntentRecord> {
  return pending.intentId ? getGenerationIntent(pending.intentId) : createGenerationIntent(pending.body, pending.clientRequestId);
}

export const environmentReasonLabels: Record<string, string> = {
  unchecked: '尚未检查完，可继续检查', no_eligible_environment: '当前没有符合创作条件的环境',
  resource_identity_unconfirmed: '资源身份待确认，请核对当前环境的模型与文件映射',
  offline: '连接离线', timeout: '检测超时', connection_failed: '连接失败',
  disabled_or_untrusted: '连接已停用或主机指纹待确认', host_fingerprint: '主机指纹需要确认',
  incompatible_resources: '节点、模型或资源不符合当前条件', environment_changed: '环境配置或资源映射已变化',
  instance_changed: '实例已重建，请重新确认资源映射', invalid_request: '输入无效，请修正后新建请求',
  workflow_version_changed: '工作流版本已变化，请确认配置后新建请求', workspace_revision_conflict: '创作内容已变化，请确认当前版本',
  resolution_interrupted: '上次环境检查已中断，可继续检查原请求', invalid_parameters: '参数无效，请修正后新建请求',
  queue_full: '生成队列已满，本次尚未接受，可稍后继续检查', probe_failed: '环境检测失败，请检查连接设置',
  lora_not_installed: '所需 LoRA 未安装或未完成映射', reference_preset_unavailable: '所需工作流或资源尚未就绪',
  inspection_required: '连接在线，资源检测尚未完成；请在环境管理中完成检测后重新检查',
};
export function environmentReason(reason: string | null | undefined): string {
  return reason ? environmentReasonLabels[reason] || reason : '';
}
