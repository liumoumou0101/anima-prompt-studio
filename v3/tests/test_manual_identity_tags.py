import json

from anima_prompt_studio_v3.core.requirements import (
    Requirements, RequirementsEdit, PromptEdit, apply_layer_updates, apply_pin,
    compile_prompt, compile_state, digest, dump, inputs_fingerprint,
)
from test_conversation import conversation_client, turn
from test_api import reference_db


def manual_requirements():
    raw = dump(Requirements.empty())
    raw['layers']['subject'].update(character_tags=['Unknown_Hero_(Game)', 'unknown hero (game)'], series_tags=['Example_Game'])
    raw['layers']['style']['manual_artist_tags'] = ['@sample_artist']
    return Requirements.model_validate(raw)


def test_manual_tags_survive_llm_omission_and_api_reload(conversation_client):
    client, captured = conversation_client
    req = dump(manual_requirements())
    created = client.post('/api/v3/workspaces', json={'draft': {'requirements_edit': {k: req[k] for k in ('layers', 'loras')}}}).json()
    response = turn(client, created)
    assert response.status_code == 200, response.text
    saved = response.json()
    expected = r'unknown hero \(game\), example game, @sample artist, '
    assert saved['positive'].startswith(expected)
    assert saved['draft']['compiled']['positive'] == saved['positive']
    assert saved['negative'] == ''
    request = json.loads(captured[0]['messages'][1]['content'])
    assert request['requirements']['layers']['subject']['character_tags'] == ['unknown hero (game)']
    restored = client.get('/api/v3/workspaces/' + saved['id']).json()
    assert restored['draft']['requirements']['layers']['subject']['series_tags'] == ['example game']
    assert restored['draft']['compile_state'] == 'fresh'


def test_manual_tags_normalize_deduplicate_and_remove_on_recompile():
    draft = {'requirements': dump(manual_requirements()), 'mode': 'faithful'}
    first = compile_prompt(draft, PromptEdit(positive='unknown_hero_(game), example game, @sample_artist, standing', negative='blurry'), source='llm')
    assert first['positive'] == r'unknown hero \(game\), example game, @sample artist, standing'
    assert first['negative'] == 'blurry'
    draft['compiled'] = first
    draft['requirements']['layers']['subject']['character_tags'] = []
    draft['requirements']['layers']['subject']['series_tags'] = []
    draft['requirements']['layers']['style']['manual_artist_tags'] = []
    assert compile_state(draft) == 'stale'
    changed = compile_prompt(draft, PromptEdit(positive=first['positive'], negative='blurry'), source='llm')
    assert changed['positive'] == 'standing'


def test_manual_prompt_stays_exact_and_subject_updates_preserve_tags():
    req = manual_requirements()
    changed = apply_layer_updates(req, ['subject'], {'subject': {'text': '站在海边'}})
    assert changed.layers.subject.character_tags == req.layers.subject.character_tags
    changed = apply_layer_updates(req, ['style'], {'style': {'text': '水彩', 'medium': 'watercolor', 'artists': []}})
    assert changed.layers.style.manual_artist_tags == ['sample artist']
    draft = {'requirements': dump(req)}
    result = compile_prompt(draft, PromptEdit(positive='my exact text', negative=''), source='user')
    assert result['positive'] == 'my exact text'
    pinned = apply_pin(Requirements.empty(), req, 'whole_scene')
    assert pinned.layers.subject.character_tags == req.layers.subject.character_tags


def test_old_empty_fields_do_not_invalidate_fingerprint():
    old = dump(Requirements.empty())
    old.pop('revision')
    old.pop('prompt_locks', None)
    old['layers']['subject'].pop('character_tags')
    old['layers']['subject'].pop('series_tags')
    old['layers']['subject'].pop('general_tags')
    old['layers']['style'].pop('manual_artist_tags')
    # Reconstruct the historical payload, before optional scene controls existed.
    old['layers']['composition'].pop('design', None)
    old['layers']['lighting'].pop('mood', None)
    expected = digest({'requirements': old, 'mode': 'faithful', 'model_profile': 'anima_aesthetic_v1', 'compiler_contract': 'anima-rewrite/1'})
    assert inputs_fingerprint({'requirements': dump(Requirements.empty())}) == expected


def test_explicit_general_tags_survive_rewrite_and_removal():
    req = Requirements.empty()
    req.layers.subject.general_tags = ["blue sky", "wide shot"]
    changed = apply_layer_updates(req, ["subject"], {"subject": {"text": "山间小屋"}})
    assert changed.layers.subject.general_tags == ["blue sky", "wide shot"]
    draft = {"requirements": dump(changed)}
    first = compile_prompt(draft, PromptEdit(positive="cabin, blue_sky", negative=""), source="llm")
    assert first["positive"] == "blue sky, wide shot, cabin"
    draft["compiled"] = first
    draft["requirements"]["layers"]["subject"]["general_tags"] = []
    assert compile_prompt(draft, PromptEdit(positive=first["positive"], negative=""), source="llm")["positive"] == "cabin"
