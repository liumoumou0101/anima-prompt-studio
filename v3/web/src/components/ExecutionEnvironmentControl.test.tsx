import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import ExecutionEnvironmentControl from './ExecutionEnvironmentControl';
import type {GenerationIntentRecord} from '../lib/generationIntents';

describe('execution environment control', () => {
  it('disables cancellation during a receipt action', () => {
    const cancel = vi.fn();
    const intent = {id: 'i', state: 'blocked', candidate_progress: {}} as GenerationIntentRecord;
    render(<ExecutionEnvironmentControl policy={{mode: 'auto', preferredEnvironmentIds: []}} environments={[]} intent={intent} disabled onChange={vi.fn()} onCancel={cancel}/>);
    const button = screen.getByRole('button', {name: '取消本次生成'});
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(cancel).not.toHaveBeenCalled();
  });
  it('only changes execution policy', () => {
    const change = vi.fn();
    render(<ExecutionEnvironmentControl policy={{mode: 'auto', preferredEnvironmentIds: []}} environments={[{id: 'a', display_name: '本机'}]} onChange={change}/>);
    fireEvent.change(screen.getByLabelText('执行环境', {selector: 'select'}), {target: {value: 'a'}});
    expect(change).toHaveBeenCalledWith({mode: 'pinned', environmentId: 'a'});
  });
  it('distinguishes unchecked candidates and offers continuation', () => {
    const retry = vi.fn();
    const intent = {id: 'i', state: 'blocked', retryable: true, reason: 'unchecked', candidate_progress: {unchecked: ['b']}, resolved_target: null} as GenerationIntentRecord;
    render(<ExecutionEnvironmentControl policy={{mode: 'auto', preferredEnvironmentIds: []}} environments={[]} intent={intent} onChange={vi.fn()} onRetry={retry}/>);
    expect(screen.getByText(/还有 1 个环境尚未检查/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: '继续检查'}));
    expect(retry).toHaveBeenCalledOnce();
  });
  it('accepted receipt displays frozen target without retry action', () => {
    const intent = {id: 'i', state: 'accepted', retryable: false, candidate_progress: {}, resolved_target: {id: 'a', display_name: '原环境'}} as GenerationIntentRecord;
    render(<ExecutionEnvironmentControl policy={{mode: 'auto', preferredEnvironmentIds: []}} environments={[]} intent={intent} onChange={vi.fn()} onRetry={vi.fn()}/>);
    expect(screen.getByText(/本次已选环境：原环境/)).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: '重新检查'})).not.toBeInTheDocument();
  });
  it('links an online environment with incomplete inventory to its existing full inspection', () => {
    const intent = {id: 'i', state: 'blocked', retryable: true, reason: 'no_eligible_environment',
      candidate_progress: {checked: {'a/b': {eligible: false, reasons: ['inspection_required'],
        probe: {environment_id: 'a/b', environment_epoch: 0, checked_at: 1, connection_state: 'online', capabilities_state: 'unchecked', reason_codes: ['inspection_required']}}}},
      resolved_target: null, submission_id: null, run_id: null, response: null, updated_at: 1} as GenerationIntentRecord;
    render(<ExecutionEnvironmentControl policy={{mode: 'auto', preferredEnvironmentIds: []}} environments={[]} intent={intent} onChange={vi.fn()}/>);
    expect(screen.getByRole('link', {name: '打开此环境的完整资源检测'})).toHaveAttribute('href', '/workflows?environment=a%2Fb');
    expect(screen.getByText(/连接在线，资源检测尚未完成/)).toBeInTheDocument();
  });
});
