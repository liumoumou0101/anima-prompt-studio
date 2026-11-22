import asyncio

from anima_prompt_studio_v3.runtime.environment_router import EnvironmentRouter
from anima_prompt_studio_v3.runtime.environment_probe import ProbeResult


def test_deterministic_batches_and_continue_unchecked():
    now = [0.]
    called = []
    async def probe(candidate, deadline, expected_epoch):
        called.append(candidate['id'])
        now[0] += 5
        return ProbeResult(candidate['id'], expected_epoch, now[0], 'online' if candidate['id'] == '5' else 'offline', 'ready', [] if candidate['id'] == '5' else ['offline'])
    router = EnvironmentRouter(lambda *_: [{'id': str(i), 'epoch': 0} for i in range(6)], probe,
                               lambda *args: (True, []), clock=lambda: now[0])
    result = asyncio.run(router.resolve_environment({}, {'mode': 'auto', 'preferredEnvironmentIds': []}, 15))
    assert result['reason'] == 'unchecked' and result['progress']['cursor'] < 6
    second = asyncio.run(router.resolve_environment({}, {'mode': 'auto'}, now[0] + 15, progress=result['progress']))
    assert second['target']['id'] == '5'
    assert called == ['0', '1', '2', '3', '4', '5']


def test_pinned_never_falls_back_and_preference_beats_race():
    async def probe(candidate, deadline, expected_epoch):
        await asyncio.sleep(0)
        return ProbeResult(candidate['id'], 0, 1, 'online', 'ready', [])
    router = EnvironmentRouter(lambda *_: [{'id': 'a', 'epoch': 0}, {'id': 'b', 'epoch': 0}], probe,
                               lambda snapshot, candidate, result: (candidate['id'] == 'b', ['missing_resource']))
    result = asyncio.run(router.resolve_environment({}, {'mode': 'pinned', 'environmentId': 'a'}, router.clock() + 15))
    assert result['target'] is None and result['progress']['order'] == ['a']
    result = asyncio.run(router.resolve_environment({}, {'mode': 'auto', 'preferredEnvironmentIds': ['b']}, router.clock() + 15))
    assert result['target']['id'] == 'b'
