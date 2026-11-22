"""Independent reviewer contract and safe failure boundary."""
import asyncio
import json

import pytest

from anima_prompt_studio_v3.core.requirements import WorkbenchError
from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService

pytestmark = pytest.mark.real_rewrite_review


def review(context=None, candidate=None):
    from anima_prompt_studio_v3.core.rewrite_review import review_rewrite
    return asyncio.run(review_rewrite(context or {'kind': 'anima', 'mode': 'faithful', 'delta': '只改外套为蓝色'},
        candidate or {'positive': 'a woman in a blue coat', 'negative': ''}, timeout_s=2))


def test_reviewer_receives_final_candidate_and_original_context(monkeypatch):
    seen = []
    async def complete(**kwargs):
        seen.append(kwargs)
        return {'text': json.dumps({"prompt_issues": [{"field": "positive", "quote": "blue coat",
            "reason": "遗漏画面左侧位置。"}], "conflicts": []})}
    monkeypatch.setattr(LLMService, 'complete', complete)
    result = review()
    assert result == {'issues': ['遗漏画面左侧位置。'], 'conflicts': []}
    assert seen[0]['task'] == 'rewrite_review'
    assert seen[0]['images'] is None
    assert seen[0]['timeout_s'] <= 2
    body = json.loads(seen[0]['messages'][-1]['content'])
    assert body['context']['delta'] == '只改外套为蓝色'
    assert body['candidate']['positive'] == 'a woman in a blue coat'


@pytest.mark.parametrize('raw', [
    '{"issues":"good"}', '{"issues":[],"issues":["lost count"]}',
    '{"valid":true}', '{"issues":[42]}', '[]', '{"issues":[],"extra":true}',
])
def test_malformed_review_never_silently_accepts(monkeypatch, raw):
    async def complete(**kwargs):
        return {'text': raw}
    monkeypatch.setattr(LLMService, 'complete', complete)
    with pytest.raises(WorkbenchError) as caught:
        review()
    assert caught.value.code == 'rewrite_review_unavailable'


def test_a_layer_value_cannot_be_evidence_of_wrong_english(monkeypatch):
    replies = iter([
        {"prompt_issues": [{"field": "positive", "quote": "半身", "reason": "旧中文景别仍是半身"}]},
        {"prompt_issues": [], "layer_corrections": {"composition": {"shot": "全身"}}},
    ])
    calls = []
    async def complete(**kwargs):
        calls.append(kwargs)
        return {"text": json.dumps(next(replies), ensure_ascii=False)}
    monkeypatch.setattr(LLMService, 'complete', complete)
    candidate = {"positive": "full-body portrait, head and soles in frame", "negative": ""}
    assert review(candidate=candidate) == {
        "issues": [], "conflicts": [], "layer_corrections": {"composition": {"shot": "全身"}},
    }
    assert len(calls) == 2
    assert "composition.design.shot" in calls[-1]["messages"][-1]["content"]


def test_transport_failure_is_private_and_does_not_become_pass(monkeypatch):
    async def complete(**kwargs):
        raise RuntimeError('private provider body with secret')
    monkeypatch.setattr(LLMService, 'complete', complete)
    with pytest.raises(WorkbenchError) as caught:
        review()
    assert caught.value.code == 'rewrite_review_unavailable'
    assert 'secret' not in str(caught.value)


def test_cancellation_is_not_translated_to_a_review_result(monkeypatch):
    async def complete(**kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(LLMService, 'complete', complete)
    with pytest.raises(asyncio.CancelledError):
        review()


def test_moss_review_cannot_receive_anima_edit_only_policy(monkeypatch):
    async def complete(**kwargs):
        system = kwargs['messages'][0]['content']
        assert 'For kind=moss' in system
        assert 'For kind=anima' not in system
        return {'text': '{"issues":[],"conflicts":[]}'}
    monkeypatch.setattr(LLMService, 'complete', complete)
    assert review({'kind': 'moss', 'mode': 'expand', 'source_text': '一位成年女性，全身，白底，不加道具'},
        {'positive': '一位成年女性，全身，白底，微笑，不加道具', 'negative': '',
         'changes': ['补充微笑'], 'warnings': []}) == {'issues': [], 'conflicts': []}
