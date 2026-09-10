import asyncio
import json
import sys
from pathlib import Path

import pytest

from anima_prompt_studio_v3.tools import evaluate_conversation as evaluation
from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
from anima_prompt_studio_v3.prompt_assistant.services.completion import CompletionError


def setup_model(monkeypatch):
    monkeypatch.setattr(evaluation, "configured_model", lambda: (True, {"model": "test"}))


@pytest.mark.parametrize("case", ["manual", "detective", "woodcut"])
def test_real_service_capture_preparation_and_independent_repeats(case, tmp_path, monkeypatch):
    setup_model(monkeypatch)
    seen = []
    async def fake(**kwargs):
        seen.append(kwargs)
        first = len(seen) % 3 == 1
        return {"text": json.dumps({"touched_layers": ["subject"] if first else [], "layer_updates": {"subject": {"text": "woman"}} if first else {}, "positive": "woman red scarf", "negative": "", "warnings": []})}
    monkeypatch.setattr(LLMService, "complete", fake)
    report = asyncio.run(evaluation.evaluate(case, tmp_path / 'output', repeats=2))
    assert len(seen) == 6
    assert report['status'] == 'completed'
    assert report['quality_verdict'] == 'pending_manual_review'
    assert all(row['restored'] and row['manual_review'] is None for row in report['results'])
    assert report['results'][0]['before']['id'] != report['results'][3]['before']['id']
    prep = report['results'][1]['preparation']
    if case == 'manual':
        assert prep['draft']['compiled']['source'] == 'user'
        assert 'wearing a red scarf' in json.dumps(seen[1])
    elif case == 'detective':
        assert prep['draft']['requirements']['layers']['subject']['locked'] is True
    else:
        assert report['results'][2]['mode'] == 'expand'
        assert 'EXPANSION' in json.dumps(seen[2])
    with pytest.raises(FileExistsError):
        asyncio.run(evaluation.evaluate(case, tmp_path / 'output'))
    assert len(seen) == 6


def test_failure_stops_all_repeats_and_never_saves_private_exception(tmp_path, monkeypatch):
    setup_model(monkeypatch)
    calls = []
    async def fail(**kwargs):
        calls.append(True)
        assert json.loads((tmp_path/'output/report.json').read_text(encoding='utf-8'))['results'][0]['status'] == 'started'
        raise CompletionError('Bearer SECRET', reason='upstream_http_error', upstream_status=401)
    monkeypatch.setattr(LLMService, 'complete', fail)
    report = asyncio.run(evaluation.evaluate('dual', tmp_path/'output', repeats=3))
    assert calls == [True]
    assert report['status'] == 'stopped'
    assert report['results'][0]['failure_preserved_workspace']
    assert report['results'][0]['error'] == {'reason':'upstream_http_error','upstream_status':401}
    assert 'SECRET' not in (tmp_path/'output/report.json').read_text(encoding='utf-8')


def test_preflight_cannot_call_model_or_create_output(tmp_path, monkeypatch, capsys):
    setup_model(monkeypatch)
    monkeypatch.setattr(evaluation, 'evaluate', lambda *a, **k: pytest.fail('must not execute'))
    monkeypatch.setattr(sys, 'argv', ['evaluate', 'woodcut', '--output', str(tmp_path/'output')])
    evaluation.main()
    assert json.loads(capsys.readouterr().out)['executed'] is False
    assert not (tmp_path/'output').exists()


def test_temporary_model_preserves_settings_and_restores_after_failure(monkeypatch):
    saved = {'model': 'original', 'provider': 'test', 'api_key': 'SECRET'}
    monkeypatch.setattr(LLMService, '_get_config', staticmethod(lambda: saved))
    with pytest.raises(RuntimeError):
        with evaluation.temporary_model('candidate'):
            assert LLMService._get_config() == {**saved, 'model': 'candidate'}
            assert saved['model'] == 'original'
            raise RuntimeError('stop')
    assert LLMService._get_config() is saved


def test_override_is_used_by_real_service_and_report(tmp_path, monkeypatch):
    monkeypatch.setattr(LLMService, '_get_config', staticmethod(lambda: {'model': 'original'}))
    monkeypatch.setattr(evaluation, 'configured_model', lambda: (True, {'model': LLMService._get_config()['model']}))
    async def fail(**kwargs):
        assert LLMService._get_config()['model'] == 'candidate'
        raise CompletionError('failed')
    monkeypatch.setattr(LLMService, 'complete', fail)
    report = asyncio.run(evaluation.evaluate('woodcut', tmp_path/'output', model_override='candidate'))
    assert report['model']['model'] == 'candidate'
    assert report['status'] == 'stopped'
    assert LLMService._get_config()['model'] == 'original'


def test_charcoal_prompt_ingest_pin_and_lora_removal_use_real_services(tmp_path, monkeypatch):
    setup_model(monkeypatch)
    calls = []
    async def fake(**kwargs):
        calls.append(kwargs)
        assert kwargs.get('images') is None
        if kwargs['task'] == 'prompt_ingest':
            return {'text': json.dumps({'layer_updates': {
                'subject': {'text': 'elderly man with beard'},
                'style': {'text': 'soft smudged shading', 'medium': 'charcoal', 'artists': []},
                'lighting': {'text': ''}, 'composition': {'text': '', 'shot': ''},
                'exclusions': {'global': [], 'scoped': []}}, 'include_with_style_pin': {}, 'warnings': []})}
        first = len(calls) == 2
        return {'text': json.dumps({'touched_layers': ['subject'] if first else [],
            'layer_updates': {'subject': {'text': 'woman holding kitten'}} if first else {},
            'positive': 'woman holding kitten charcoal', 'negative': '', 'warnings': []})}
    monkeypatch.setattr(LLMService, 'complete', fake)
    image = Path(__file__).resolve().parents[1] / 'example-packs/cma-styles-20260910-v1/media/off_cma_166868/original.webp'
    report = asyncio.run(evaluation.evaluate('charcoal', tmp_path/'output', reference_image=image))
    assert report['status'] == 'completed'
    assert len(calls) == 4 and report['planned_prompt_ingests'] == 1
    pin = report['reference_preparations'][0]['after_pin']['draft']['requirements']
    assert pin['layers']['subject']['text'] == ''
    assert pin['layers']['style']['medium'] == 'charcoal'
    assert len(pin['loras']) == 1
    assert report['results'][2]['preparation']['draft']['compile_state'] == 'stale'
    assert report['results'][2]['before']['draft']['requirements']['loras'] == []
    assert report['results'][2]['result']['draft']['requirements']['loras'] == []
    assert report['results'][2]['delta'] == ''


def test_charcoal_ingest_failure_stops_before_rewrite(tmp_path, monkeypatch):
    setup_model(monkeypatch)
    from anima_prompt_studio_v3.api.reference_ingest import IngestService
    async def fail(*args, **kwargs):
        raise RuntimeError('SECRET')
    monkeypatch.setattr(IngestService, 'ingest', fail)
    image = Path(__file__).resolve().parents[1] / 'example-packs/cma-styles-20260910-v1/media/off_cma_166868/original.webp'
    report = asyncio.run(evaluation.evaluate('charcoal', tmp_path/'output', reference_image=image))
    assert report['status'] == 'stopped' and report['results'] == []
    assert report['reference_preparations'][0]['status'] == 'failed'
    assert 'SECRET' not in (tmp_path/'output/report.json').read_text(encoding='utf-8')
