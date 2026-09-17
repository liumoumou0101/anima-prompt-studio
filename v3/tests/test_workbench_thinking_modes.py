from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from anima_prompt_studio_v3.core.requirements import WorkbenchError
from anima_prompt_studio_v3.prompt_assistant.services import completion, thinking_control


GO = 'https://opencode.ai/zen/go/v1'


def invoke(monkeypatch, model, *, enabled=False, task='rewrite', base=GO, response=None):
    requests = []

    def handle(request):
        requests.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json=response or {'choices': [{'message': {'content': 'OK'}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr(completion.HTTPClientPool, 'get_client', lambda **kw: client)
            result = await completion.complete(
                {'provider': 'custom', 'model': model, 'base_url': base},
                {'type': 'openai_compatible', 'workbench_enable_thinking': enabled},
                messages=[{'role': 'user', 'content': 'Return OK'}], task=task,
            )
            assert result['text'] == 'OK'
    asyncio.run(run())
    return requests[0]


@pytest.mark.parametrize('model', ['minimax-m3', 'mimo-v2.5', 'mimo-v2.5-pro',
    'deepseek-v4-pro', 'deepseek-flash', 'deepseek-v4.1-flash', 'deepseek-v4-flash-vision-exp'])
@pytest.mark.parametrize('enabled', [False, True])
def test_go_native_and_gateway_controls_follow_saved_workbench_choice(monkeypatch, model, enabled):
    _, payload = invoke(monkeypatch, model, enabled=enabled)
    assert payload.get('reasoning') == {'enabled': enabled}
    expected = 'adaptive' if enabled and model == 'minimax-m3' else 'enabled' if enabled else 'disabled'
    assert payload.get('thinking') == {'type': expected}
    assert not enabled or len(payload['messages']) == 1


@pytest.mark.parametrize('model', ['qwen3.7-max','qwen3.8-max','qwen3.8-flash','qwen3.7-plus','qwen3.6-plus'])
@pytest.mark.parametrize('enabled', [False, True])
def test_go_qwen_controls_follow_saved_workbench_choice(monkeypatch, model, enabled):
    _, payload = invoke(monkeypatch, model, enabled=enabled)
    assert payload.get('enable_thinking') is enabled
    assert payload.get('reasoning') == {'enabled': enabled}


@pytest.mark.parametrize('model', ['hy4-preview', 'hy3'])
@pytest.mark.parametrize('enabled', [False, True])
def test_go_hy_uses_verified_gateway_switch(monkeypatch, model, enabled):
    _, payload = invoke(monkeypatch, model, enabled=enabled)
    assert payload.get('reasoning') == {'enabled': enabled}
    assert 'thinking' not in payload


@pytest.mark.parametrize('enabled', [False, True])
def test_longcat_does_not_receive_gateway_override_that_defeats_native_control(monkeypatch, enabled):
    _, payload = invoke(monkeypatch, 'longcat-2.0', enabled=enabled)
    assert payload.get('thinking') == {'type': 'enabled' if enabled else 'disabled'}
    assert 'reasoning' not in payload


@pytest.mark.parametrize('model', ['glm-5.1','glm-5.2','glm-5.3','glm-5.3-flash',
    'kimi-k3','kimi-k2.7-code','minimax-m2.5','minimax-m2.7','grok-4.6',
    'muse-spark-1.3-contributor','muse-spark-1.2-contributor'])
def test_required_go_models_cannot_silently_run_thinking_with_toggle_off(monkeypatch, model):
    monkeypatch.setattr(completion.HTTPClientPool, 'get_client', lambda **kw: pytest.fail('paid request must not start'))
    with pytest.raises(WorkbenchError) as exc:
        asyncio.run(completion.complete({'provider':'custom','model':model,'base_url':GO}, {},
            messages=[{'role':'user','content':'OK'}]))
    assert exc.value.code == 'thinking_disable_unsupported'


@pytest.mark.parametrize('model', ['glm-5.1','glm-5.2','glm-5.3','kimi-k2.7-code'])
def test_go_thinking_only_chat_uses_native_on_without_rejected_reasoning_key(monkeypatch, model):
    _, payload = invoke(monkeypatch, model, enabled=True)
    assert payload.get('thinking') == {'type':'enabled'}
    assert 'reasoning' not in payload


@pytest.mark.parametrize('task', ['prompt_ingest','probe','ingest'])
def test_workbench_switch_does_not_enable_other_tasks(monkeypatch, task):
    _, payload = invoke(monkeypatch, 'mimo-v2.5-pro', enabled=True, task=task)
    assert payload['thinking'] == {'type':'disabled'}
    assert payload['reasoning'] == {'enabled':False}


@pytest.mark.parametrize('base', ['https://opencode.ai/zen/go/v1','https://opencode.ai/zen/go/v1/chat/completions'])
@pytest.mark.parametrize('enabled', [False, True])
def test_gpt_go_routes_responses_and_maps_reasoning(monkeypatch, base, enabled):
    url, payload = invoke(monkeypatch, 'gpt-5.6-luna', enabled=enabled, base=base,
        response={'object':'response','status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'OK'}]}]})
    assert url == GO + '/responses'
    assert payload['reasoning'] == {'effort':'medium' if enabled else 'none'}
    assert 'input' in payload and 'messages' not in payload


def test_minimax_m27_uses_messages_with_explicit_on(monkeypatch):
    url, payload = invoke(monkeypatch, 'minimax-m2.7', enabled=True,
        response={'type':'message','stop_reason':'end_turn','content':[{'type':'thinking','thinking':'PRIVATE'},{'type':'text','text':'OK'}]})
    assert url == GO + '/messages'
    assert payload['thinking']['type'] == 'enabled'
    assert payload['max_tokens'] > payload['thinking']['budget_tokens']


def test_capabilities_distinguish_go_alias_from_native_and_unknown():
    capability = getattr(thinking_control, 'get_thinking_capability', None)
    assert callable(capability), 'settings need a model capability independent of the current toggle'
    assert capability('custom','glm-5.2',base_url=GO)['mode'] == 'required'
    assert capability('custom','glm-5.2',base_url='https://api.z.ai/v1')['mode'] == 'switchable'
    assert capability('custom','mimo-v2.5-pro',base_url=GO)['mode'] == 'switchable'
    assert capability('custom','unknown-new-model',base_url=GO)['mode'] == 'unverified'
    assert capability('custom','gpt-5.6-luna',base_url=GO+'/../v1')['mode'] == 'unverified'


@pytest.mark.parametrize('base', ['https://opencode.ai.evil.test/zen/go/v1','http://opencode.ai/zen/go/v1','https://opencode.ai/zen/v1','https://opencode.ai:8443/zen/go/v1'])
def test_go_switch_and_protocol_mapping_never_leak_to_other_endpoints(monkeypatch, base):
    url, payload = invoke(monkeypatch,'gpt-5.6-luna',enabled=True,base=base)
    assert url == base+'/chat/completions'
    assert 'reasoning' not in payload


@pytest.mark.parametrize('suffix', ['/messages', '/responses'])
def test_switching_from_other_go_protocol_to_chat_uses_chat_endpoint(monkeypatch, suffix):
    url, payload = invoke(monkeypatch, 'mimo-v2.5-pro', base=GO+suffix)
    assert url == GO+'/chat/completions'
    assert payload['thinking'] == {'type':'disabled'}


@pytest.mark.parametrize('ending', ['', ',"finish_reason":"tool_calls"'])
def test_incomplete_chat_stream_is_not_accepted_as_a_finished_answer(monkeypatch, ending):
    async def run():
        body = 'data: {"choices":[{"delta":{"content":"{\\"ok\\":true}"}'+ending+'}]}\n\n'
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(
                200, content=body, headers={'Content-Type':'text/event-stream'}))) as client:
            monkeypatch.setattr(completion.HTTPClientPool, 'get_client', lambda **kw: client)
            with pytest.raises(completion.CompletionError) as exc:
                await completion.complete({'provider':'test','model':'mimo-v2.5','base_url':GO}, {},
                    messages=[{'role':'user','content':'OK'}])
            assert exc.value.reason == 'incomplete_response'
    asyncio.run(run())


def test_invalid_message_budget_is_a_safe_completion_error_before_network(monkeypatch):
    monkeypatch.setattr(completion.HTTPClientPool, 'get_client', lambda **kw: pytest.fail('network must not start'))
    with pytest.raises(completion.CompletionError) as exc:
        asyncio.run(completion.complete({'provider':'test','model':'minimax-m2.7','base_url':GO,'max_tokens':1000},
            {'workbench_enable_thinking':True,'enable_advanced_params':True}, messages=[{'role':'user','content':'OK'}]))
    assert exc.value.reason == 'invalid_response'
