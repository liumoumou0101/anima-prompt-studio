import {useId} from 'react';
import type {ExecutionPolicy, GenerationIntentRecord} from '../lib/generationIntents';
import {environmentReason} from '../lib/generationIntents';

export interface ExecutionEnvironmentOption {id: string; display_name: string; address?: string; enabled?: boolean}
export interface ExecutionEnvironmentControlProps {
  policy: ExecutionPolicy; environments: ExecutionEnvironmentOption[];
  intent?: GenerationIntentRecord | null; disabled?: boolean; allowAutomatic?: boolean;
  onChange: (policy: ExecutionPolicy) => void;
  onRetry?: () => void; onCancel?: () => void;
  onConfirmAssets?: (environmentId: string) => void;
  onRebuilt?: (environmentId: string) => void;
}

export default function ExecutionEnvironmentControl({policy, environments, intent, disabled, allowAutomatic = true,
  onChange, onRetry, onCancel, onConfirmAssets, onRebuilt}: ExecutionEnvironmentControlProps) {
  const id = useId();
  const names = new Map(environments.map(environment => [environment.id, environment.display_name]));
  const accepted = intent?.state === 'accepted';
  const selection = policy.mode === 'auto' ? 'auto' : policy.environmentId;
  return <section className="execution-environment-control" aria-label="执行环境">
    <label htmlFor={id}>执行环境</label>
    <select id={id} value={selection} disabled={disabled} onChange={event => {
      const value = event.target.value;
      onChange(value === 'auto' ? {mode: 'auto', preferredEnvironmentIds: policy.mode === 'pinned' ? [policy.environmentId] : policy.preferredEnvironmentIds}
        : {mode: 'pinned', environmentId: value});
    }}>
      {allowAutomatic && <option value="auto">自动选择相同创作条件的环境</option>}
      {environments.map(environment => <option key={environment.id} value={environment.id} disabled={environment.enabled === false}>
        {environment.display_name}{environment.address ? ` · ${environment.address}` : ''}
      </option>)}
      {policy.mode === 'pinned' && !names.has(policy.environmentId) && <option value={policy.environmentId}>{policy.environmentId ? "原固定环境（不可用）" : "请选择固定环境"}</option>}
    </select>
    {policy.mode === 'pinned' && <small>仅使用固定环境；离线时保留创作条件。</small>}
    {intent && <div aria-live="polite">
      {accepted ? <p>本次已选环境：{intent.resolved_target?.display_name || names.get(intent.resolved_target?.id || '') || intent.resolved_target?.id}。任务目标已冻结。</p>
        : intent.state === 'resolving' ? <p>正在检查环境，尚未接受任务。</p>
        : intent.state === 'canceled' ? <p>本次生成意图已取消。</p>
        : <p>{environmentReason(intent.reason)}</p>}
      {intent.candidate_progress.input_error && <p role="alert">{intent.candidate_progress.input_error.message}</p>}
      {intent.state === 'blocked' && !intent.retryable && onCancel && <p>请先取消本次生成，再修正输入后重新提交。</p>}
      <ul>{Object.entries(intent.candidate_progress.checked || {}).map(([environmentId, evidence]) => <li key={environmentId}>
        <strong>{names.get(environmentId) || environmentId}</strong>：{evidence.eligible ? '预检通过' : evidence.reasons.map(environmentReason).join('；') || '待检测'}
        {evidence.probe.checked_at > 0 && <small> · 检测于 {new Date(evidence.probe.checked_at * 1000).toLocaleTimeString()}</small>}
        {evidence.reasons.includes('inspection_required') && <a href={`/workflows?environment=${encodeURIComponent(environmentId)}`}>
          打开此环境的完整资源检测</a>}
        {evidence.reasons.includes('resource_identity_unconfirmed') && onConfirmAssets && <button type="button" disabled={disabled}
          onClick={() => onConfirmAssets(environmentId)}>确认当前环境资源映射</button>}
      </li>)}</ul>
      {(intent.candidate_progress.unchecked?.length || 0) > 0 && <p>还有 {intent.candidate_progress.unchecked!.length} 个环境尚未检查。</p>}
      {intent.state === 'blocked' && intent.retryable && onRetry && <button type="button" disabled={disabled} onClick={onRetry}>
        {intent.candidate_progress.unchecked?.length ? '继续检查' : '重新检查'}</button>}
      {(intent.state === 'resolving' || intent.state === 'blocked') && onCancel && <button type="button" disabled={disabled} onClick={onCancel}>取消本次生成</button>}
    </div>}
    {policy.mode === 'pinned' && onRebuilt && <button type="button" disabled={disabled} onClick={() => onRebuilt(policy.environmentId)}>此环境已重建</button>}
  </section>;
}
