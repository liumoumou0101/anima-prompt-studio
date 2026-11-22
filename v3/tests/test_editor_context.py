from pathlib import Path
import asyncio
import json
import pytest
from anima_prompt_studio_v3.api.workspace_store import WorkspaceStore, WorkspaceRevisionConflictError
from anima_prompt_studio_v3.core.requirements import WorkbenchError

def test_context_is_document_scoped_and_invalidates_without_revision(tmp_path: Path):
    store=WorkspaceStore(tmp_path/'workspace.db'); workspace=store.create('test',{'positive_text':'first'}); wid=workspace['id']
    a=store.editor_context(wid,'a',request_id='request-a',editor_epoch=1)
    b=store.editor_context(wid,'b',request_id='request-b',editor_epoch=1)
    store.invalidate_editor_context(wid,'a')
    with pytest.raises(WorkbenchError): store.check_editor_context(wid,'a',a['token'])
    store.check_editor_context(wid,'b',b['token'])
    assert store.get(wid)['revision']==1
    WorkspaceStore(store.path).check_editor_context(wid,'b',b['token'])

def test_checkpoint_stable_number_idempotency_without_mutating_workspace(tmp_path: Path):
    store=WorkspaceStore(tmp_path/'workspace.db'); workspace=store.create('test',{'positive_text':'first'}); wid=workspace['id']
    args=dict(operation_id='op-1',base_revision=1,kind='manual',label='first edit',snapshot={'positive':'second'})
    a=store.create_checkpoint(wid,**args); b=WorkspaceStore(store.path).create_checkpoint(wid,**args)
    assert a==b; assert a['version_number']==1; assert store.get(wid)==workspace
    assert len(store.list_checkpoints(wid))==1
    with pytest.raises(WorkbenchError): store.create_checkpoint(wid,**{**args,'snapshot':{'positive':'different'}})

def test_restore_invalidates_context_and_cas_is_atomic_and_replayable(tmp_path: Path):
    store=WorkspaceStore(tmp_path/'workspace.db'); workspace=store.create('test',{'positive_text':'first'}); wid=workspace['id']
    a=store.editor_context(wid,'a',request_id='request-a',editor_epoch=1)
    b=store.editor_context(wid,'b',request_id='request-b',editor_epoch=1)
    args=dict(document_id='a',operation_id='restore-1',expected_revision=1,title='test',draft={'positive_text':'restored'})
    restored=store.restore_editor(wid,**args)
    assert store.restore_editor(wid,**args)==restored; assert restored['revision']==2
    with pytest.raises(WorkbenchError): store.check_editor_context(wid,'a',a['token'])
    store.check_editor_context(wid,'b',b['token'])
    c=store.editor_context(wid,'a',request_id='request-c',editor_epoch=2)
    with pytest.raises(WorkspaceRevisionConflictError):store.restore_editor(wid,**{**args,'operation_id':'restore-2'})
    store.check_editor_context(wid,'a',c['token'])

def test_token_is_rechecked_inside_write_transaction(tmp_path: Path):
    store=WorkspaceStore(tmp_path/'workspace.db'); workspace=store.create('test',{'positive_text':'first'}); wid=workspace['id']
    context=store.editor_context(wid,'a',request_id='r',editor_epoch=1)
    store.check_editor_context(wid,'a',context['token'])
    store.invalidate_editor_context(wid,'a')
    with pytest.raises(WorkbenchError):
        store.transform(wid,expected_revision=1,operation=lambda draft:{**draft,'positive_text':'late'},editor_context=('a',context['token']))
    with pytest.raises(WorkbenchError):
        store.create_proposal(wid,expected_revision=1,draft=workspace['draft'],metadata={},editor_context=('a',context['token']))
    assert store.get(wid)==workspace

def test_canceled_context_cannot_be_resurrected_by_old_epoch(tmp_path: Path):
    store=WorkspaceStore(tmp_path/'workspace.db'); workspace=store.create('test',{});wid=workspace['id']
    store.editor_context(wid,'a',request_id='r1',editor_epoch=1)
    store.invalidate_editor_context(wid,'a')
    with pytest.raises(WorkbenchError):store.editor_context(wid,'a',request_id='late-r1',editor_epoch=1)
    store.invalidate_editor_context(wid,'a')
    fresh=store.editor_context(wid,'a',request_id='r2',editor_epoch=2)
    store.check_editor_context(wid,'a',fresh['token'])

def test_delayed_invalidation_cannot_cancel_a_newer_request(tmp_path: Path):
    store=WorkspaceStore(tmp_path/'workspace.db');workspace=store.create('test',{});wid=workspace['id']
    old=store.editor_context(wid,'a',request_id='old',editor_epoch=1)
    new=store.editor_context(wid,'a',request_id='new',editor_epoch=2)
    assert store.invalidate_editor_context(wid,'a',expected_token=old['token']) is False
    store.check_editor_context(wid,'a',new['token'])
    assert store.invalidate_editor_context(wid,'a',expected_token=new['token']) is True
    with pytest.raises(WorkbenchError):store.check_editor_context(wid,'a',new['token'])

def test_llm_result_after_document_cancellation_does_not_write(tmp_path: Path,monkeypatch):
    from anima_prompt_studio_v3.api.conversation import ConversationService,TurnRequest
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    from anima_prompt_studio_v3.core.requirements import Requirements,dump
    store=WorkspaceStore(tmp_path/'workspace.db');requirements=dump(Requirements.empty());requirements['layers']['subject']['text']='person'
    workspace=store.create('test',{'requirements_edit':{'layers':requirements['layers'],'loras':[]}});wid=workspace['id']
    context=store.editor_context(wid,'a',request_id='request',editor_epoch=1)
    async def complete(**kwargs):
        store.invalidate_editor_context(wid,'a',expected_token=context['token'])
        return {'text':json.dumps({'touched_layers':[],'layer_updates':{},'positive':'person, warm light','negative':'','warnings':[]})}
    monkeypatch.setattr(LLMService,'complete',complete)
    request=TurnRequest(workspace_id=wid,revision=1,document_id='a',context_token=context['token'],request_id='request',editor_epoch=1,delta={'text':'warm light'})
    with pytest.raises(WorkbenchError) as caught:asyncio.run(ConversationService(store).turn(request))
    assert caught.value.code=='editor_context_stale';assert store.get(wid)==workspace

def test_editor_router_preserves_token_cas_and_stable_receipts(tmp_path: Path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from anima_prompt_studio_v3.api.editor_context import make_editor_router
    store=WorkspaceStore(tmp_path/'workspace.db');workspace=store.create('test',{});wid=workspace['id']
    app=FastAPI();app.include_router(make_editor_router(store))
    with TestClient(app) as client:
        base=f'/api/v3/workspaces/{wid}'
        old=client.post(base+'/editor-context',json={'document_id':'a','request_id':'old','editor_epoch':1}).json()
        new=client.post(base+'/editor-context',json={'document_id':'a','request_id':'new','editor_epoch':2}).json()
        assert client.delete(base+'/editor-context/a',params={'expected_token':old['token']}).json()=={'invalidated':False}
        store.check_editor_context(wid,'a',new['token'])
        body={'operation_id':'op','base_revision':1,'kind':'manual','label':'edit','snapshot':{'positive':'test'}}
        one=client.post(base+'/checkpoints',json=body);two=client.post(base+'/checkpoints',json=body)
        assert one.status_code==200;assert two.json()==one.json()
        assert client.get(base+'/checkpoints').json()['items']==[one.json()]
        body={'document_id':'a','operation_id':'restore','revision':1,'title':'test','draft':{'positive_text':'restored'}}
        one=client.post(base+'/editor-restore',json=body);two=client.post(base+'/editor-restore',json=body)
        assert one.status_code==200;assert two.json()==one.json();assert one.json()['revision']==2
