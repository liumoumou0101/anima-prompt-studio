import {beforeEach, describe, expect, it, vi} from 'vitest';
vi.mock('./api', () => ({apiRequest: vi.fn()}));
import {apiRequest} from './api';
import {createGenerationIntent, recoverGenerationIntent, retryGenerationIntent} from './generationIntents';

describe('generation intent protocol', () => {
  beforeEach(() => vi.clearAllMocks());
  const body = {source: {positive_prompt: 'cat', settings: {seed: '8798399215689017476'}},
    creationConfiguration: {workflow: {id: 'workflow', revision: 'v1'}}, executionPolicy: {mode: 'auto' as const, preferredEnvironmentIds: []}};
  it('sends frozen inputs with a stable key and exact string seed', async () => {
    await createGenerationIntent(body, 'same-key');
    expect(apiRequest).toHaveBeenCalledWith('/api/v3/generation-intents', expect.objectContaining({headers: {'Idempotency-Key': 'same-key'}, body: JSON.stringify(body)}));
  });
  it('recovers an accepted or uncertain request by its original id without rebuilding inputs', async () => {
    await recoverGenerationIntent({protocol: 'intent-v1', clientRequestId: 'same-key', body, intentId: 'intent/1'});
    expect(apiRequest).toHaveBeenCalledWith('/api/v3/generation-intents/intent%2F1');
    expect(apiRequest).toHaveBeenCalledTimes(1);
  });
  it('repeats an uncertain first POST using the same frozen key and body', async () => {
    await recoverGenerationIntent({protocol: 'intent-v1', clientRequestId: 'same-key', body});
    expect(apiRequest).toHaveBeenCalledWith('/api/v3/generation-intents', expect.objectContaining({headers: {'Idempotency-Key': 'same-key'}, body: JSON.stringify(body)}));
    await retryGenerationIntent('intent1');
    expect(apiRequest).toHaveBeenLastCalledWith('/api/v3/generation-intents/intent1/retry-resolution', {method: 'POST'});
  });
});
