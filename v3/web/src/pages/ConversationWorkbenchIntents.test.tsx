import {act, cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {ConversationWorkbenchPage} from './ConversationWorkbenchPage';
import {emptyRequirements, type ConversationRecord} from '../lib/conversation';
import {defaultGenerationSettings} from '../lib/generationSettings';
import {basicWorkflowSchema} from '../lib/workflowParameterSchema';
import {readConversationDraft, recoverConversationPending} from '../lib/conversationDrafts';
import type {GenerationIntentRecord, GenerationIntentRequest} from '../lib/generationIntents';

vi.mock('../components/ArtistRecommendations', () => ({ArtistRecommendations: () => null}));
vi.mock('../components/ManualIdentityTags', () => ({ManualIdentityTags: () => null}));
vi.mock('../components/SceneDesignControls', () => ({SceneDesignControls: () => null}));

let workspace: ConversationRecord;
let posts: Array<{key: string; body: GenerationIntentRequest}>;
let intent: GenerationIntentRecord;
let failAcceptanceResponse: boolean;
let initialState: 'blocked' | 'resolving' | 'accepted';
let createCount: number;
let directPosts: Array<{key: string; body: Record<string, unknown>}>;
let directFailure: {code: string; status: number} | 'network' | null;
const settings = {...defaultGenerationSettings(), workflow_profile_id: 'workflow', remote_profile_id: null,
  seed: '8798399215689017476', execution_policy: {mode: 'auto' as const, preferredEnvironmentIds: ['a']}};

beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); sessionStorage.setItem('anima-v3-session', 'test');
  const requirements = emptyRequirements(); requirements.layers.subject.text = '一只猫';
  workspace = {id: 'workspace_intents', title: '意图测试', revision: 3, created_at: '2026-10-25', updated_at: '2026-10-25',
    draft: {positive_text: '', excluded_text: '', model_profile: 'anima_base_v1', mode: 'faithful',
      generation_settings: structuredClone(settings), requirements: {...requirements, contract: 'anima-requirements/1', revision: 1},
      compiled: {positive: 'cat', negative: '', source: 'llm', compiled_token: 'cmp_3'}, compile_state: 'fresh', conversation_events: []}};
  localStorage.setItem('anima-conversation-active', JSON.stringify(workspace.id));
  posts = []; directPosts = []; directFailure = null; failAcceptanceResponse = false; initialState = 'blocked'; createCount = 0;
  const target = {workflow_profile_id: 'workflow', workflow_display_name: '标准文生图', compatible_model_profiles: ['anima_base_v1'],
    template_revision: 'revision', availability: 'ready', parameter_schema: basicWorkflowSchema('workflow', 'revision')};
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input), method = init?.method || 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    let response: unknown = {items: []};
    if (url.endsWith('/llm/settings')) response = {current: {service: 'test', model: 'small', workbench_enable_thinking: false, thinking: {mode: 'switchable', message: ''}}, services: []};
    else if (url.includes('/workspaces?')) response = {items: [workspace]};
    else if (url.endsWith('/generation-targets')) response = {items: ['a', 'b'].map(id => ({...target, remote_profile_id: id, remote_display_name: `环境${id}`}))};
    else if (url.endsWith('/proposal')) response = {proposal: null};
    else if (url.includes('/runs?limit=')) response = {items: intent?.response ? [intent.response] : []};
    else if (url.endsWith('/direct-prompt/runs')) {
      directPosts.push({key: new Headers(init?.headers).get('Idempotency-Key')!, body});
      if (directFailure && directFailure !== 'network') return new Response(JSON.stringify({error: {code: directFailure.code, message: '本次直接提交未被接受'}}), {status: directFailure.status});
      accept();
      if (directFailure === 'network') throw new TypeError('lost local acceptance response');
      response = intent.response;
    }
    else if (url.endsWith('/generation-submissions/by-key?key=' + encodeURIComponent(directPosts[0]?.key || ''))) response = {found: true, response: intent.response};
    else if (url.endsWith('/workbench/generation-source') && method === 'DELETE') {
      workspace = {...workspace, revision: workspace.revision + 1, draft: {...workspace.draft, generation_source: null}};
      response = workspace;
    }
    else if (url.endsWith('/generation-intents') && method === 'POST') {
      const key = new Headers(init?.headers).get('Idempotency-Key')!;
      posts.push({key, body});
      if (!intent) {
        createCount++;
        intent = {id: 'intent_one', state: initialState, retryable: true, reason: 'unchecked',
          candidate_progress: {unchecked: ['b'], checked: {}}, resolved_target: null, submission_id: null, run_id: null, response: null, updated_at: 1};
        if (initialState === 'accepted') accept();
      }
      if (failAcceptanceResponse) {failAcceptanceResponse = false; throw new TypeError('lost response');}
      response = intent;
    } else if (url.endsWith('/intent_one/retry-resolution')) {accept(); response = intent;}
    else if (url.endsWith('/intent_one/cancel')) {intent = {...intent, state: 'canceled', retryable: false}; response = intent;}
    else if (url.endsWith('/generation-intents/intent_one')) response = intent;
    else if (url.endsWith('/workspaces/' + workspace.id)) {
      if (method === 'PUT') workspace = {...workspace, revision: workspace.revision + 1, draft: {...workspace.draft,
        generation_settings: body.draft.generation_settings,
        ...(body.draft.prompt_edit ? {compiled: {...workspace.draft.compiled!, ...body.draft.prompt_edit}} : {})}};
      response = workspace;
    }
    return new Response(JSON.stringify(response), {status: 200});
  });
});
afterEach(() => {cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); intent = undefined as unknown as GenerationIntentRecord;});

function accept() {
  const run = {id: 'run_original', state: 'draft' as const, remote_profile_id: 'a', workflow_profile_id: 'workflow',
    artifact_count: 0, status_message: '已接受', workspace_revision: workspace.revision, compiled_token: workspace.draft.compiled!.compiled_token,
    available_actions: [], progress: 0, prompt_job_id: 'job', created_at: '', updated_at: '', completed_at: null, error: null,
    error_code: null, error_message: null, remote_prompt_id: ''};
  intent = {...intent, state: 'accepted', retryable: false, reason: null, candidate_progress: {}, resolved_target: {id: 'a', display_name: '环境a'},
    run_id: run.id, submission_id: 'sub_original', response: run};
}
async function mount() {
  const view = render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await screen.findByLabelText('正向提示词');
  await waitFor(() => expect(screen.getByRole('button', {name: '生成图片'})).toBeEnabled());
  return view;
}

function pin(environmentId = 'a') {
  workspace.draft.generation_settings = {...workspace.draft.generation_settings!, remote_profile_id: environmentId,
    execution_policy: {mode: 'pinned', environmentId}};
}

it('submits a new pinned conversational request without a snapshot directly with its selected target and settings', async () => {
  pin('b');
  workspace.draft.requirements!.loras = [{logical_id: 'style_lora', file_name: 'style.safetensors', weight: 0.7, required: true, trigger_words: ['style'], source: {kind: 'user'}}];
  await mount();
  fireEvent.change(screen.getByLabelText('这次想怎么改？'), {target: {value: '保留尚未应用的意见'}});
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByText('已接受');
  expect(directPosts).toHaveLength(1);
  expect(posts).toHaveLength(0);
  expect(directPosts[0].body).toMatchObject({submission_kind: 'conversational', use_current_prompt: true,
    workspace_id: 'workspace_intents', workspace_revision: workspace.revision, compiled_token: 'cmp_3',
    positive_prompt: 'cat', negative_prompt: '', model_profile: 'anima_base_v1', remote_profile_id: 'b', workflow_profile_id: 'workflow',
    settings: {seed: '8798399215689017476'}});
  expect(directPosts[0].body).not.toHaveProperty('workflow_snapshot_run_id');
  expect(directPosts[0].body).not.toHaveProperty('creationConfiguration');
  expect(directPosts[0].body).not.toHaveProperty('lora_selection');
  expect(workspace.draft.requirements!.loras[0].file_name).toBe('style.safetensors');
  expect(screen.getByLabelText('这次想怎么改？')).toHaveValue('保留尚未应用的意见');
  expect(recoverConversationPending(workspace.id)).toBeNull();
});

it.each([
  {code: 'direct_preparation_timeout', status: 503}, {code: 'rate_limited', status: 429},
  {code: 'remote_not_configured', status: 422}, {code: 'unauthorized', status: 403},
  {code: 'unknown', status: 422}, {code: 'incompatible_model', status: 422},
])('unlocks a pinned request after definitive $code without losing the draft', async rejection => {
  pin(); directFailure = rejection;
  await mount();
  fireEvent.change(screen.getByLabelText('这次想怎么改？'), {target: {value: '尚未发送的想法'}});
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByText('本次直接提交未被接受');
  expect(screen.getByRole('button', {name: '生成图片'})).toBeEnabled();
  expect(screen.getByRole('button', {name: '更新提示词'})).toBeEnabled();
  expect(screen.getByRole('button', {name: '新会话'})).toBeEnabled();
  expect(screen.getByLabelText('正向提示词')).toHaveValue('cat');
  expect(screen.getByLabelText('这次想怎么改？')).toHaveValue('尚未发送的想法');
  expect(screen.queryByRole('region', {name: '未确认的提交'})).not.toBeInTheDocument();
  expect(recoverConversationPending(workspace.id)).toBeNull();
  const firstKey = directPosts[0].key;
  directFailure = null;
  fireEvent.change(screen.getByLabelText('执行环境', {selector: 'select'}), {target: {value: 'b'}});
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByText('已接受');
  expect(directPosts).toHaveLength(2);
  expect(directPosts[1].key).not.toBe(firstKey);
  expect(directPosts[1].body.remote_profile_id).toBe('b');
});

it('keeps uncertain pinned transport optional across reload and queries by key without replay or overwriting later edits', async () => {
  pin(); directFailure = 'network';
  const view = await mount();
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByText(/无法连接本地服务/);
  const frozen = structuredClone(directPosts[0]);
  expect(screen.getByRole('region', {name: '未确认的提交'})).toHaveTextContent(/旧任务仍可能完成/);
  expect(screen.getByRole('button', {name: '生成图片'})).toBeEnabled();
  expect(screen.getByRole('button', {name: '新会话'})).toBeEnabled();
  expect(recoverConversationPending(workspace.id)).toBeNull();
  view.unmount();
  directFailure = null;
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await screen.findByRole('button', {name: '查询旧提交结果'});
  await waitFor(() => expect(screen.getByRole('button', {name: '生成图片'})).toBeEnabled());
  expect(directPosts).toEqual([frozen]);
  fireEvent.change(screen.getByLabelText('正向提示词'), {target: {value: 'later edited cat'}});
  fireEvent.change(screen.getByLabelText('这次想怎么改？'), {target: {value: '后续意见保留'}});
  fireEvent.change(screen.getByLabelText('执行环境', {selector: 'select'}), {target: {value: 'b'}});
  fireEvent.click(screen.getByRole('button', {name: '查询旧提交结果'}));
  await screen.findByText('已接受');
  expect(screen.getByLabelText('正向提示词')).toHaveValue('later edited cat');
  expect(screen.getByLabelText('这次想怎么改？')).toHaveValue('后续意见保留');
  expect(screen.getByLabelText('执行环境', {selector: 'select'})).toHaveValue('b');
  expect(readConversationDraft(workspace.id)?.local?.positive).toBe('later edited cat');
  expect(directPosts).toEqual([frozen]);
  const queries = vi.mocked(fetch).mock.calls.filter(([input]) => String(input).includes('/generation-submissions/by-key?'));
  expect(queries).toHaveLength(1);
  expect(String(queries[0][0])).toBe('/api/v3/generation-submissions/by-key?key=' + encodeURIComponent(frozen.key));
  expect(queries[0][1]?.method || 'GET').toBe('GET');
  expect(screen.queryByRole('region', {name: '未确认的提交'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await waitFor(() => expect(directPosts).toHaveLength(2));
  expect(directPosts[1].key).not.toBe(frozen.key);
  expect(directPosts[1].body).toMatchObject({remote_profile_id: 'b', positive_prompt: 'later edited cat'});
});

it('retains an uncertain receipt when no accepted task is found until it is explicitly ignored', async () => {
  pin(); directFailure = 'network';
  await mount(); fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByText(/无法连接本地服务/);
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).includes('/generation-submissions/by-key?')
    ? new Response(JSON.stringify({found: false, response: null})) : original(input, init));
  fireEvent.click(screen.getByRole('button', {name: '查询旧提交结果'}));
  await screen.findByText(/暂未查到已接受任务/);
  expect(screen.getByRole('button', {name: '查询旧提交结果'})).toBeEnabled();
  expect(screen.getByRole('button', {name: '生成图片'})).toBeEnabled();
  expect(directPosts).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', {name: '忽略这条记录'}));
  expect(screen.queryByRole('region', {name: '未确认的提交'})).not.toBeInTheDocument();
});

it.each([{}, {id: '  ', state: 'draft'}, {id: 'not-a-run-state', state: 'accepted'}])(
  'retains recovery and later edits for a malformed run receipt from the read-only query: %j', async response => {
    pin(); directFailure = 'network';
    await mount(); fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
    await screen.findByText(/无法连接本地服务/);
    fireEvent.change(screen.getByLabelText('正向提示词'), {target: {value: 'later prompt stays'}});
    fireEvent.change(screen.getByLabelText('这次想怎么改？'), {target: {value: '后续意见保留'}});
    const saved = structuredClone(readConversationDraft(workspace.id)?.local);
    const original = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation(async (input, init) => String(input).includes('/generation-submissions/by-key?')
      ? new Response(JSON.stringify({found: true, response})) : original(input, init));
    fireEvent.click(screen.getByRole('button', {name: '查询旧提交结果'}));
    await screen.findByText(/查询回执不完整/);
    expect(screen.getByRole('button', {name: '查询旧提交结果'})).toBeEnabled();
    expect(screen.getByRole('button', {name: '生成图片'})).toBeEnabled();
    expect(screen.getByLabelText('正向提示词')).toHaveValue('later prompt stays');
    expect(screen.getByLabelText('这次想怎么改？')).toHaveValue('后续意见保留');
    expect(readConversationDraft(workspace.id)?.local).toEqual(saved);
    expect(screen.queryByText(/已找到旧提交的任务/)).not.toBeInTheDocument();
    expect(directPosts).toHaveLength(1);
  },
);

it('retains optional recovery for a malformed run receipt from a pinned POST', async () => {
  pin();
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).endsWith('/direct-prompt/runs')
    ? new Response(JSON.stringify({id: 'not-a-run', state: 'accepted', workspace_revision: 3, compiled_token: 'cmp_3'})) : original(input, init));
  await mount();
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByText(/提交回执不完整/);
  expect(screen.getByRole('button', {name: '查询旧提交结果'})).toBeEnabled();
  expect(screen.getByRole('button', {name: '生成图片'})).toBeEnabled();
  expect(screen.getByLabelText('正向提示词')).toHaveValue('cat');
});

it('releases global busy after a read-only recovery query hangs and preserves its receipt', async () => {
  pin(); directFailure = 'network';
  await mount(); fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByText(/无法连接本地服务/);
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).includes('/generation-submissions/by-key?')) return new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('timeout', 'AbortError')), {once: true});
    });
    return original(input, init);
  });
  vi.useFakeTimers();
  await act(async () => {fireEvent.click(screen.getByRole('button', {name: '查询旧提交结果'}));});
  expect(screen.getByRole('button', {name: '生成图片'})).toBeDisabled();
  await act(async () => {await vi.advanceTimersByTimeAsync(12000);});
  expect(screen.getByRole('button', {name: '生成图片'})).toBeEnabled();
  expect(screen.getByRole('button', {name: '查询旧提交结果'})).toBeEnabled();
  expect(screen.getByRole('button', {name: '新会话'})).toBeEnabled();
  expect(screen.getByText(/查询旧提交超时/)).toBeVisible();
  expect(screen.getByLabelText('正向提示词')).toHaveValue('cat');
  expect(directPosts).toHaveLength(1);
});

it('unlocks a pinned request that hangs locally while retaining its optional receipt', async () => {
  pin();
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith('/direct-prompt/runs')) return new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('timeout', 'AbortError')), {once: true});
    });
    return original(input, init);
  });
  await mount();
  vi.useFakeTimers();
  await act(async () => {fireEvent.click(screen.getByRole('button', {name: '生成图片'}));});
  expect(screen.getByRole('button', {name: '生成图片'})).toBeDisabled();
  await act(async () => {await vi.advanceTimersByTimeAsync(12000);});
  expect(screen.getByText(/等待本地服务超时，提交结果尚未确认/)).toBeVisible();
  expect(screen.getByRole('button', {name: '生成图片'})).toBeEnabled();
  expect(screen.getByRole('button', {name: '新会话'})).toBeEnabled();
  expect(screen.getByRole('button', {name: '查询旧提交结果'})).toBeEnabled();
  expect(recoverConversationPending(workspace.id)).toBeNull();
  expect(vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith('/direct-prompt/runs'))).toHaveLength(1);
});

it('allows an explicit new pinned task without first querying an uncertain old request', async () => {
  pin(); directFailure = 'network';
  await mount(); fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByText(/无法连接本地服务/);
  const oldKey = directPosts[0].key;
  directFailure = null;
  fireEvent.change(screen.getByLabelText('执行环境', {selector: 'select'}), {target: {value: 'b'}});
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByText('已接受');
  expect(directPosts).toHaveLength(2);
  expect(directPosts[1].key).not.toBe(oldKey);
  expect(directPosts[1].body.remote_profile_id).toBe('b');
  expect(screen.getByRole('button', {name: '查询旧提交结果'})).toBeEnabled();
  expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes('/generation-submissions/by-key?'))).toBe(false);
});

it('retains an old run snapshot and routes it to an explicitly chosen pinned environment', async () => {
  pin('a');
  initialState = 'accepted';
  workspace.draft.generation_settings!.parameter_schema = basicWorkflowSchema('workflow', 'revision');
  workspace.draft.generation_source = {run_id: 'old_run', remote_profile_id: 'a', workflow_profile_id: 'workflow', model_profile: 'anima_base_v1'};
  await mount();
  fireEvent.change(screen.getByLabelText('执行环境', {selector: 'select'}), {target: {value: 'b'}});
  expect(readConversationDraft(workspace.id)?.local?.workflowSnapshotRunId).toBe('old_run');
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByText('已接受');
  expect(directPosts).toHaveLength(0);
  expect(posts).toHaveLength(1);
  expect(posts[0].body).toMatchObject({executionPolicy: {mode: 'pinned', environmentId: 'b'},
    creationConfiguration: {workflow: {id: 'workflow', revision: 'revision'}},
    source: {workflow_snapshot_run_id: 'old_run', settings: {seed: '8798399215689017476', parameter_schema: {workflowId: 'workflow', templateRevision: 'revision'}}}});
  expect(workspace.draft.generation_source?.run_id).toBe('old_run');
  expect(vi.mocked(fetch).mock.calls.some(([input, init]) => String(input).endsWith('/workbench/generation-source') && init?.method === 'DELETE')).toBe(false);
});

function blockOnTimeout() {
  intent = {...intent, state: 'blocked', retryable: true, reason: 'no_eligible_environment', candidate_progress: {
    unchecked: [], checked: {a: {eligible: false, reasons: ['offline', 'timeout'], probe: {
      environment_id: 'a', environment_epoch: 0, checked_at: 1, connection_state: 'offline',
      capabilities_state: 'unchecked', reason_codes: ['timeout'],
    }}},
  }};
}

async function reopenUnconfirmedSubmission() {
  failAcceptanceResponse = true;
  const view = await mount();
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByText(/无法连接本地服务/);
  const frozen = structuredClone(posts[0]);
  view.unmount();
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole('button', {name: '查询本次提交'})).toBeEnabled());
  expect(posts).toHaveLength(1);
  return frozen;
}

it('replaces a recovered unknown receipt with visible timeout evidence and retries the same intent', async () => {
  const frozen = await reopenUnconfirmedSubmission();
  blockOnTimeout();
  fireEvent.click(screen.getByRole('button', {name: '查询本次提交'}));
  const status = await screen.findByRole('region', {name: '本次提交状态'});
  expect(await within(status).findByText('当前没有符合创作条件的环境')).toBeVisible();
  expect(within(status).getByText(/连接离线；检测超时/)).toBeVisible();
  expect(within(status).getByText('环境a', {selector: 'strong'})).toBeVisible();
  expect(screen.queryByText(/接受结果尚未确认/)).not.toBeInTheDocument();
  expect(screen.queryByRole('button', {name: '查询本次提交'})).not.toBeInTheDocument();
  expect(screen.getAllByLabelText('执行环境', {selector: 'select'})).toHaveLength(1);
  expect(screen.getAllByRole('button', {name: '取消本次生成'})).toHaveLength(1);
  expect(posts).toEqual([frozen, frozen]);
  expect(recoverConversationPending(workspace.id)).toEqual({key: frozen.key, body: JSON.stringify(frozen.body)});

  // Future edits must not alter the frozen request being rechecked.
  fireEvent.change(screen.getByLabelText('执行环境', {selector: 'select'}), {target: {value: 'b'}});
  const original = vi.mocked(fetch).getMockImplementation()!;
  let finishRetry: (() => void) | undefined;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith('/intent_one/retry-resolution')) {
      expect(init?.method).toBe('POST');
      expect(init?.body).toBeUndefined();
      await new Promise<void>(resolve => {finishRetry = resolve;});
    }
    return original(input, init);
  });
  fireEvent.click(within(status).getByRole('button', {name: '重新检查'}));
  await waitFor(() => expect(finishRetry).toBeDefined());
  expect(within(status).getByRole('button', {name: '重新检查'})).toBeDisabled();
  expect(within(status).getByText(/检测超时/)).toBeVisible();
  finishRetry!();
  await screen.findByText(/本次已选环境：环境a/);
  expect(screen.getByLabelText('执行环境', {selector: 'select'})).toHaveValue('b');
  expect(posts).toEqual([frozen, frozen]);
  expect(createCount).toBe(1);
  expect(intent.run_id).toBe('run_original');
  expect(recoverConversationPending(workspace.id)).toBeNull();
});

it.each(['accepted', 'blocked'] as const)('waits for a fresh %s receipt after retry returns the unchanged blocked receipt', async state => {
  await mount();
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByRole('button', {name: '继续检查'});
  const frozen = recoverConversationPending(workspace.id);
  const original = vi.mocked(fetch).getMockImplementation()!;
  let gets = 0;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith('/intent_one/retry-resolution')) return new Response(JSON.stringify(intent), {status: 202});
    if (url.endsWith('/generation-intents/intent_one') && ++gets === 2) {
      if (state === 'accepted') accept();
      else {blockOnTimeout(); intent = {...intent, updated_at: 2};}
    }
    return original(input, init);
  });
  fireEvent.click(screen.getByRole('button', {name: '继续检查'}));
  if (state === 'accepted') {
    await screen.findByText(/本次已选环境：环境a/, {}, {timeout: 3000});
    expect(recoverConversationPending(workspace.id)).toBeNull();
  } else {
    expect(await screen.findByText(/连接离线；检测超时/, {}, {timeout: 3000})).toBeVisible();
    expect(screen.getByRole('button', {name: '重新检查'})).toBeEnabled();
    expect(recoverConversationPending(workspace.id)).toEqual(frozen);
  }
  expect(screen.queryByText(/正在等待新的检查结果/)).not.toBeInTheDocument();
  const retries = vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith('/retry-resolution'));
  expect(retries).toHaveLength(1);
  expect(retries[0][1]?.method).toBe('POST');
  expect(gets).toBe(2);
  expect(posts).toHaveLength(1);
  expect(posts[0]).toEqual({key: frozen!.key, body: JSON.parse(frozen!.body)});
});

it('finishes waiting with retry feedback if a recheck never produces a fresh receipt', async () => {
  await mount();
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByRole('button', {name: '继续检查'});
  const frozen = recoverConversationPending(workspace.id);
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).endsWith('/retry-resolution')
    ? new Response(JSON.stringify(intent), {status: 202}) : original(input, init));
  vi.useFakeTimers();
  await act(async () => {fireEvent.click(screen.getByRole('button', {name: '继续检查'}));});
  expect(screen.getByText(/正在等待新的检查结果/)).toBeVisible();
  await act(async () => {await vi.advanceTimersByTimeAsync(20000);});
  expect(screen.getByText(/尚未收到新的环境检查结果/)).toBeVisible();
  expect(screen.getByRole('button', {name: '继续检查'})).toBeEnabled();
  expect(screen.getByRole('button', {name: '取消本次生成'})).toBeEnabled();
  expect(recoverConversationPending(workspace.id)).toEqual(frozen);
  expect(vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith('/retry-resolution'))).toHaveLength(1);
  expect(posts).toHaveLength(1);
});

it('stops awaiting a fresh recheck receipt after unmount', async () => {
  const view = await mount();
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByRole('button', {name: '继续检查'});
  const frozen = recoverConversationPending(workspace.id);
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).endsWith('/retry-resolution')
    ? new Response(JSON.stringify(intent), {status: 202}) : original(input, init));
  vi.useFakeTimers();
  await act(async () => {fireEvent.click(screen.getByRole('button', {name: '继续检查'}));});
  expect(screen.getByText(/正在等待新的检查结果/)).toBeVisible();
  view.unmount();
  accept();
  await act(async () => {await vi.advanceTimersByTimeAsync(20000);});
  expect(vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith('/generation-intents/intent_one'))).toHaveLength(0);
  expect(recoverConversationPending(workspace.id)).toEqual(frozen);
  expect(posts).toHaveLength(1);
});

it('shows a nonretryable input error at the recovered receipt and cancels before allowing correction', async () => {
  const frozen = await reopenUnconfirmedSubmission();
  intent = {...intent, state: 'blocked', retryable: false, reason: 'invalid_parameters', candidate_progress: {
    input_error: {message: '步数必须大于零', fields: {steps: '必须大于零'}},
  }};
  fireEvent.click(screen.getByRole('button', {name: '查询本次提交'}));
  const status = await screen.findByRole('region', {name: '本次提交状态'});
  expect(await within(status).findByRole('alert')).toHaveTextContent('步数必须大于零');
  expect(within(status).getByText(/请先取消本次生成，再修正输入/)).toBeVisible();
  expect(within(status).queryByRole('button', {name: /重新检查|继续检查/})).not.toBeInTheDocument();
  expect(screen.queryByRole('button', {name: '查询本次提交'})).not.toBeInTheDocument();
  expect(screen.getByLabelText('正向提示词')).toBeDisabled();
  fireEvent.click(within(status).getByRole('button', {name: '取消本次生成'}));
  await screen.findByText('本次生成意图已取消。');
  expect(screen.getByLabelText('正向提示词')).toBeEnabled();
  expect(recoverConversationPending(workspace.id)).toBeNull();
  expect(posts).toEqual([frozen, frozen]);
  expect(intent.run_id).toBeNull();
  expect(vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith('/intent_one/cancel'))).toHaveLength(1);
});

it.each(['blocked', 'accepted'] as const)('shows a known resolving receipt and polls read-only to %s', async state => {
  initialState = 'resolving';
  await mount();
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  const status = await screen.findByRole('region', {name: '本次提交状态'});
  expect(await within(status).findByText('正在检查环境，尚未接受任务。')).toBeVisible();
  expect(within(status).getByRole('button', {name: '取消本次生成'})).toBeEnabled();
  expect(screen.queryByRole('button', {name: '查询本次提交'})).not.toBeInTheDocument();
  expect(screen.queryByText(/接受结果尚未确认/)).not.toBeInTheDocument();
  if (state === 'blocked') blockOnTimeout(); else accept();
  if (state === 'blocked') {
    expect(await within(status).findByText(/检测超时/, {}, {timeout: 2500})).toBeVisible();
    expect(within(status).getByRole('button', {name: '重新检查'})).toBeEnabled();
    expect(recoverConversationPending(workspace.id)).not.toBeNull();
  } else {
    await screen.findByText(/本次已选环境：环境a/, {}, {timeout: 2500});
    expect(recoverConversationPending(workspace.id)).toBeNull();
  }
  const polls = vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith('/generation-intents/intent_one'));
  expect(polls).toHaveLength(1);
  expect(polls[0][1]?.method || 'GET').toBe('GET');
  expect(posts).toHaveLength(1);
  expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith('/retry-resolution'))).toBe(false);
});

it.each(['blocked', 'accepted'] as const)('recovers a transient resolving poll failure with GET only to %s', async state => {
  initialState = 'resolving';
  const original = vi.mocked(fetch).getMockImplementation()!;
  let failPoll = true;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith('/generation-intents/intent_one') && failPoll) {
      failPoll = false;
      throw new TypeError('temporary status failure');
    }
    return original(input, init);
  });
  await mount();
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByText('正在检查环境，尚未接受任务。');
  const frozen = recoverConversationPending(workspace.id);
  expect(await screen.findByText(/无法连接本地服务/, {}, {timeout: 2500})).toBeVisible();
  expect(recoverConversationPending(workspace.id)).toEqual(frozen);
  if (state === 'blocked') blockOnTimeout(); else accept();
  if (state === 'blocked') {
    expect(await screen.findByText(/连接离线；检测超时/, {}, {timeout: 2500})).toBeVisible();
    expect(recoverConversationPending(workspace.id)).toEqual(frozen);
  } else {
    await screen.findByText(/本次已选环境：环境a/, {}, {timeout: 2500});
    expect(recoverConversationPending(workspace.id)).toBeNull();
  }
  expect(screen.queryByText(/无法连接本地服务/)).not.toBeInTheDocument();
  const receiptRequests = vi.mocked(fetch).mock.calls.filter(([input]) => String(input).includes('/generation-intents/'));
  expect(receiptRequests).toHaveLength(2);
  expect(receiptRequests.every(([input, init]) => String(input).endsWith('/generation-intents/intent_one')
    && (init?.method || 'GET') === 'GET' && init?.body === undefined)).toBe(true);
  expect(posts).toHaveLength(1);
  expect(posts[0]).toEqual({key: frozen!.key, body: JSON.parse(frozen!.body)});
  expect(createCount).toBe(1);
});

it('stops read-only poll recovery after unmount without settling the pending request', async () => {
  initialState = 'resolving';
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith('/generation-intents/intent_one')) throw new TypeError('temporary status failure');
    return original(input, init);
  });
  const view = await mount();
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByText(/无法连接本地服务/, {}, {timeout: 2500});
  const frozen = recoverConversationPending(workspace.id);
  view.unmount();
  accept();
  await new Promise(resolve => setTimeout(resolve, 1000));
  expect(vi.mocked(fetch).mock.calls.filter(([input]) => String(input).includes('/generation-intents/'))).toHaveLength(1);
  expect(recoverConversationPending(workspace.id)).toEqual(frozen);
  expect(posts).toHaveLength(1);
});

it('continues one frozen auto request after changing the future environment policy', async () => {
  await mount();
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByRole('button', {name: '继续检查'});
  expect(posts).toHaveLength(1);
  expect(posts[0].body.executionPolicy).toEqual({mode: 'auto', preferredEnvironmentIds: ['a']});
  expect(posts[0].body.source.settings).toMatchObject({seed: '8798399215689017476'});
  expect(posts[0].body.creationConfiguration.workflow).toEqual({id: 'workflow', revision: 'revision'});
  fireEvent.change(screen.getByLabelText('执行环境', {selector: 'select'}), {target: {value: 'b'}});
  fireEvent.click(screen.getByRole('button', {name: '继续检查'}));
  await screen.findByText(/本次已选环境：环境a/);
  expect(screen.getByLabelText('执行环境', {selector: 'select'})).toHaveValue('b');
  expect(posts).toHaveLength(1);
  expect(recoverConversationPending(workspace.id)).toBeNull();
});

it('recovers lost acceptance across remount using the original key and exact body', async () => {
  initialState = 'accepted'; failAcceptanceResponse = true;
  const view = await mount();
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  await screen.findByText(/无法连接本地服务/);
  const frozen = structuredClone(posts[0]);
  expect(recoverConversationPending(workspace.id)?.key).toBe(frozen.key);
  view.unmount();
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await screen.findByRole('button', {name: '查询本次提交'});
  fireEvent.click(screen.getByRole('button', {name: '查询本次提交'}));
  await screen.findByText(/本次已选环境：环境a/);
  expect(posts).toHaveLength(2);
  expect(posts[1]).toEqual(frozen);
  expect(createCount).toBe(1);
});

it('cancels resolving intent without submitting a generation run', async () => {
  initialState = 'resolving';
  await mount();
  fireEvent.click(screen.getByRole('button', {name: '生成图片'}));
  fireEvent.click(await screen.findByRole('button', {name: '取消本次生成'}));
  await screen.findByText('本次生成意图已取消。');
  expect(recoverConversationPending(workspace.id)).toBeNull();
  expect(posts).toHaveLength(1);
  expect(intent.run_id).toBeNull();
});
