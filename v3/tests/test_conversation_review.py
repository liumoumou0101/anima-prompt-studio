"""Actual Anima state transitions with only the external LLM mocked."""
import asyncio
from copy import deepcopy
import json

import pytest

from anima_prompt_studio_v3.api.conversation import ConversationService, TurnRequest
from anima_prompt_studio_v3.api.workspace_store import WorkspaceStore
from anima_prompt_studio_v3.core.requirements import Requirements, WorkbenchError, dump
from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService

pytestmark = pytest.mark.real_rewrite_review
BEFORE = 'one adult woman in a red coat, standing on the left, upper body, watercolor'
AFTER = 'one adult woman in a blue coat, standing on the left, upper body, watercolor'


def prepared(tmp_path, *, tags=None, shot=None, negative=''):
    store = WorkspaceStore(tmp_path / 'review.db')
    req = dump(Requirements.empty())
    req['layers']['subject']['text'] = '一位成年女性，红色外套，站在左侧'
    req['layers']['composition']['text'] = '半身'
    req['layers']['subject']['general_tags'] = tags or []
    if shot:
        req['layers']['composition']['design'] = {'shot': {'value': shot, 'source': 'user'}}
    record = store.create('review', {'requirements_edit': {'layers': req['layers'], 'loras': []},
        'prompt_edit': {'positive': BEFORE, 'negative': negative}})
    return store, record


def candidate(positive=AFTER, negative='', **updates):
    return {'touched_layers': list(updates), 'layer_updates': updates,
        'positive': positive, 'negative': negative, 'warnings': []}


def positive_issue(quote, reason):
    return {"prompt_issues": [{"field": "positive", "quote": quote, "reason": reason}]}


def run(store, record, delta='只把红外套改为蓝外套，其他不变。', mode='faithful'):
    return asyncio.run(ConversationService(store).turn(TurnRequest(
        workspace_id=record['id'], revision=record['revision'], mode=mode,
        delta={'text': delta}, compiled={k: record['draft']['compiled'][k] for k in ('positive', 'negative')})))


def transport(monkeypatch, rewrites, reviews):
    calls = []
    async def complete(**kwargs):
        calls.append(deepcopy(kwargs))
        queue = reviews if kwargs['task'] == 'rewrite_review' else rewrites
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return {'text': json.dumps(item, ensure_ascii=False)}
    monkeypatch.setattr(LLMService, 'complete', complete)
    return calls


@pytest.mark.parametrize("mode", ["faithful", "expand"])
def test_free_text_shot_mismatch_is_classified_without_rewriting_finished_english(tmp_path, monkeypatch, mode):
    store, record = prepared(tmp_path)
    requirements = record["draft"]["requirements"]
    requirements["layers"]["composition"]["shot"] = "半身"
    record = store.update(record["id"], expected_revision=record["revision"], title=record["title"],
        draft={"requirements_edit": {"layers": requirements["layers"], "loras": []}})
    positive = BEFORE.replace("upper body", "full body from head to black boot soles")
    calls = transport(monkeypatch, [candidate(positive, composition={"text": "全身像"})], [
        {"issues": ["composition.shot 仍为半身，与全身像冲突，应改为全身。"]},
        {"prompt_issues": [], "layer_corrections": {"composition": {"shot": "全身"}}, "conflicts": []},
        {"prompt_issues": [], "layer_corrections": {}, "conflicts": []},
    ])
    result = run(store, record, "全身像，头顶至黑靴鞋底入画。", mode)
    assert result["positive"] == positive
    assert result["draft"]["requirements"]["layers"]["composition"]["shot"] == "全身"
    assert [call["task"] for call in calls] == ["rewrite", "rewrite_review", "rewrite_review", "rewrite_review"]
    assert "composition.design.shot" in calls[2]["messages"][-1]["content"]


def test_ignored_edit_is_repaired_before_persisting(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    calls = transport(monkeypatch, [candidate(BEFORE), candidate(subject={'text': '一位成年女性，蓝色外套，站在左侧'})],
        [positive_issue("red coat", "没有将红外套改成蓝外套。"), {'issues': []}])
    result = run(store, record)
    assert result['positive'] == AFTER
    assert store.get(record['id'])['draft']['compiled']['positive'] == AFTER
    assert [c['task'] for c in calls] == ['rewrite', 'rewrite_review', 'rewrite', 'rewrite_review']
    assert all(c.get('images') is None for c in calls)


def test_bad_repair_cannot_commit_and_stops_after_one_retry(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    calls = transport(monkeypatch, [candidate(BEFORE), candidate(BEFORE)],
        [positive_issue("red coat", "外套仍然是红色。"), positive_issue("red coat", "外套仍然是红色。")])
    with pytest.raises(WorkbenchError) as caught:
        run(store, record)
    assert caught.value.code == 'rewrite_constraints_failed'
    assert store.get(record['id']) == record
    assert len(calls) == 4


def test_review_failure_keeps_original_and_hides_private_error(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    transport(monkeypatch, [candidate()], [RuntimeError('private upstream credential body')])
    result = run(store, record)
    assert result['review_status'] == 'needs_review'
    assert result['draft']['compiled']['positive'] == AFTER
    assert result['warnings'] and 'private' not in str(result)
    assert store.get_proposal(record['id'])['review_status'] == 'needs_review'
    assert store.get(record['id']) == record


def test_unavailable_recheck_cannot_release_a_known_unresolved_defect(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    transport(monkeypatch, [candidate(BEFORE), candidate(BEFORE)],
              [positive_issue("red coat", "要求蓝色，仍是红色"), RuntimeError("unavailable")])
    with pytest.raises(WorkbenchError) as error:
        run(store, record)
    assert error.value.code == 'rewrite_constraints_failed'
    assert store.get_proposal(record['id']) is None
    assert store.get(record['id']) == record


def test_optional_design_advice_does_not_block_compatible_text(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    warning = '还可以加强背景对比度，这是可选的表现手法。'
    transport(monkeypatch, [candidate()], [{'prompt_issues': [], 'warnings': [warning]}])
    result = run(store, record)
    assert result['positive'] == AFTER and warning in result['warnings']
    assert store.get_proposal(record['id']) is None
    assert store.get(record['id'])['revision'] == record['revision'] + 1


def test_unresolved_meaning_is_reviewable_instead_of_auto_saved(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    reason = "“侧边”的指代无法从现有描述确定，请核对候选。"
    transport(monkeypatch, [candidate()], [{'prompt_issues': [], 'unverified': reason}])
    result = run(store, record)
    assert result['review_status'] == 'needs_review'
    assert reason in result['warnings']
    assert store.get(record['id']) == record


def test_review_sees_actual_post_insertion_tag_conflict(tmp_path, monkeypatch):
    store, record = prepared(tmp_path, tags=['hat'])
    calls = transport(monkeypatch, [candidate(BEFORE + ', bareheaded')],
        [{'issues': [], 'conflicts': ['去帽要求与选中的固定标签 hat 冲突，请先取消该标签。']}])
    with pytest.raises(WorkbenchError) as caught:
        run(store, record, delta='去掉帽子，其他不变。')
    assert caught.value.code == 'scene_design_conflict'
    payload = json.loads(calls[-1]['messages'][-1]['content'])
    assert payload['candidate']['positive'].startswith('hat, ')
    assert 'bareheaded' in payload['candidate']['positive']
    assert store.get(record['id']) == record
    assert len(calls) == 2


def test_selected_shot_conflict_cannot_be_saved_as_fresh(tmp_path, monkeypatch):
    store, record = prepared(tmp_path, shot='半身')
    calls = transport(monkeypatch, [candidate(BEFORE.replace('upper body', 'full body'), composition={'text': '全身'})],
        [{'issues': [], 'conflicts': ['全身像要求与仍选中的半身控件冲突，请先调整景别。']}])
    with pytest.raises(WorkbenchError) as caught:
        run(store, record, delta='改成全身，其他不变。')
    assert caught.value.code == 'scene_design_conflict'
    payload = json.loads(calls[-1]['messages'][-1]['content'])
    assert payload['candidate']['requirements']['layers']['composition']['design']['shot']['value'] == '半身'
    assert store.get(record['id']) == record


def test_negative_and_ledger_are_repaired_together(tmp_path, monkeypatch):
    store, record = prepared(tmp_path, negative='watermark, blurry')
    transport(monkeypatch,
        [candidate(BEFORE, 'watermark', exclusions={'global': ['blurry'], 'scoped': []})],
        [{'prompt_issues': [], 'layer_corrections': {'exclusions': {'global': ['watermark']}}}, {'issues': []}])
    result = run(store, record, delta='只删负面 blurry，保留 watermark，正面原文保持不变。', mode='expand')
    assert result['positive'] == BEFORE
    assert result['negative'] == 'watermark'
    assert result['draft']['requirements']['layers']['exclusions']['global'] == ['watermark']


@pytest.mark.parametrize("mode", ["faithful", "expand"])
def test_stale_lighting_is_reconciled_without_regenerating_valid_text(tmp_path, monkeypatch, mode):
    store, record = prepared(tmp_path, negative="  watermark\n")
    positive = "  " + AFTER + ", bright soft dusk light  \n"
    subject = {"text": "一位成年女性，蓝色外套，站在左侧"}
    lighting = {"text": "明亮、柔和的黄昏光线"}
    calls = transport(monkeypatch, [candidate(positive, "  watermark\n", subject=subject)], [
        {"issues": [], "layer_corrections": {"lighting": lighting}}, {"issues": []},
    ])
    result = run(store, record, delta="把红外套改成蓝色，并改成明亮柔和的黄昏光线。", mode=mode)
    assert [call['task'] for call in calls] == ['rewrite', 'rewrite_review', 'rewrite_review']
    first, second = [json.loads(call['messages'][1]['content'])['candidate'] for call in calls[1:]]
    assert first['positive'] == second['positive'] == result['positive'] == positive
    assert first['negative'] == second['negative'] == result['negative'] == "  watermark\n"
    assert second['requirements']['layers']['lighting']['text'] == lighting['text']
    assert second['requirements']['layers']['subject']['text'] == subject['text']
    assert result['changed_layers'] == ['subject', 'lighting']
    assert result['draft']['requirements']['revision'] == record['draft']['requirements']['revision'] + 1
    assert store.get(record['id'])['revision'] == record['revision'] + 1


def test_repair_retains_first_candidates_valid_layer_edits(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    subject = {"text": "一位成年女性，蓝色外套，站在左侧"}
    calls = transport(monkeypatch, [
        candidate(AFTER + ", midday light", subject=subject),
        candidate(AFTER + ", dusk light", lighting={"text": "黄昏光线"}),
    ], [positive_issue("midday light", "正文仍写着正午，需要替换为黄昏。"), {"issues": []}])
    result = run(store, record, delta="把红外套改成蓝色，时间改为黄昏。")
    assert [call['task'] for call in calls] == ['rewrite', 'rewrite_review', 'rewrite', 'rewrite_review']
    assert result['draft']['requirements']['layers']['subject']['text'] == subject['text']
    assert result['changed_layers'] == ['subject', 'lighting']
    assert result['draft']['requirements']['revision'] == record['draft']['requirements']['revision'] + 1


@pytest.mark.parametrize("correction, lock_lighting", [
    ({"lighting": {"text": "日落"}}, True),
    ({"lighting": {"mood": None}}, False),
    ({"style": {"artists": ["some artist"]}}, False),
])
def test_ledger_reconciliation_never_changes_protected_controls(tmp_path, monkeypatch, correction, lock_lighting):
    store, record = prepared(tmp_path)
    if lock_lighting:
        requirements = record['draft']['requirements']
        requirements['layers']['lighting']['locked'] = True
        record = store.update(record['id'], expected_revision=record['revision'], title=record['title'],
            draft={'requirements_edit': {'layers': requirements['layers'], 'loras': []}})
    calls = transport(monkeypatch, [candidate()], [{"issues": [], "layer_corrections": correction}])
    with pytest.raises(WorkbenchError) as caught:
        run(store, record)
    assert caught.value.code == 'invalid_layer_updates'
    if lock_lighting:
        assert '光影' in str(caught.value)
    assert len(calls) == 2
    assert store.get(record['id']) == record


def test_unresolved_ledger_reconciliation_never_commits(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    correction = {"issues": [], "layer_corrections": {"subject": {"text": "蓝色外套"}}}
    calls = transport(monkeypatch, [candidate()], [correction, correction])
    result = run(store, record)
    assert result['review_status'] == 'needs_review'
    assert result['draft']['compiled']['positive'] == AFTER
    assert len(calls) == 3
    assert store.get(record['id']) == record


@pytest.mark.parametrize("task, expected", [("rewrite", "invalid_layer_updates"), ("sync_requirements", None)])
def test_empty_delta_can_only_reconcile_in_an_authorized_operation(tmp_path, monkeypatch, task, expected):
    store, record = prepared(tmp_path)
    reviewed = {"positive": BEFORE, "negative": ""}
    correction = {"issues": [], "layer_corrections": {"subject": {"text": "穿红外套、站在左侧的成年女性"}}}
    transport(monkeypatch, [candidate(**reviewed)], [correction, {"issues": []}])
    request = TurnRequest(workspace_id=record["id"], revision=record["revision"], task=task,
                          delta={"text": ""}, compiled=reviewed)
    if expected:
        with pytest.raises(WorkbenchError) as caught:
            asyncio.run(ConversationService(store).turn(request))
        assert caught.value.code == expected
    else:
        result = asyncio.run(ConversationService(store).turn(request))
        assert result['changed_layers'] == ['subject']
        assert result['draft']['compiled']['positive'] == reviewed['positive']
    assert store.get(record['id']) == record


def test_expansion_outside_narrow_scope_is_repaired(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    transport(monkeypatch, [candidate(AFTER + ', sunset, smiling'), candidate()],
        [positive_issue("sunset, smiling", "只改外套颜色不能添加夕阳或微笑。"), {'issues': []}])
    result = run(store, record, mode='expand')
    assert result['positive'] == AFTER


def test_reviewed_no_text_change_explains_and_flags_it(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    transport(monkeypatch, [candidate(BEFORE)], [{'issues': []}])
    result = run(store, record, delta='保持现在的红外套，不做其他修改。')
    assert result['positive'] == BEFORE
    assert result['prompt_changed'] is False
    assert result['message']


def test_negative_only_edit_preserves_exact_visible_positive_whitespace(tmp_path, monkeypatch):
    store, record = prepared(tmp_path, negative='blurry, watermark')
    positive = '  ' + BEFORE + '\n'
    record = store.update(record['id'], expected_revision=record['revision'], title=record['title'],
        draft={'prompt_edit': {'positive': positive, 'negative': 'blurry, watermark'}})
    transport(monkeypatch, [candidate(positive, 'watermark')], [{'issues': []}])
    result = run(store, record, delta='只删负面blurry，正面连同空白逐字保持不变。')
    assert result['positive'] == positive


def test_unchanged_positive_keeps_existing_selected_tag_order_and_spacing(tmp_path, monkeypatch):
    store, record = prepared(tmp_path, tags=['blue eyes'], negative='blurry, watermark')
    positive = '  ' + BEFORE + ', (blue eyes:1.2)\n'
    record = store.update(record['id'], expected_revision=record['revision'], title=record['title'],
        draft={'prompt_edit': {'positive': positive, 'negative': 'blurry, watermark'}})
    transport(monkeypatch, [candidate(positive, 'watermark')], [{'issues': []}])
    result = run(store, record, delta='只删负面blurry，正面连同权重、顺序、空白逐字保持不变。')
    assert result['positive'] == positive


def test_existing_scene_edit_does_not_run_general_expansion_recipe(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    calls = transport(monkeypatch, [candidate()], [{'issues': []}])
    result = run(store, record, mode='expand')
    context = json.loads(calls[0]['messages'][1]['content'])
    assert context['rewrite_goal']['operation'] == 'edit_existing'
    assert context['rewrite_goal']['scope'] == 'latest_delta'
    assert result['draft']['mode'] == 'expand'
    assert 'develop the picture, not just translate' not in calls[0]['messages'][0]['content']
