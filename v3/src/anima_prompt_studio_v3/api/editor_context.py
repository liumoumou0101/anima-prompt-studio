"""Per-document rewrite cancellation, immutable checkpoints and CAS restore API."""
from typing import Any
from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from .workspace_store import WorkspaceStore

class EditorContextRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    document_id:str=Field(min_length=1,max_length=128)
    request_id:str=Field(min_length=1,max_length=128)
    editor_epoch:int=Field(ge=0)

class CheckpointRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    operation_id:str=Field(min_length=1,max_length=128)
    base_revision:int=Field(ge=1)
    kind:str=Field(min_length=1,max_length=40)
    label:str=Field(max_length=4000)
    snapshot:dict[str,Any]
    source:dict[str,Any]|None=None

class RestoreEditorRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    document_id:str=Field(min_length=1,max_length=128)
    operation_id:str=Field(min_length=1,max_length=128)
    revision:int=Field(ge=1)
    title:str=Field(min_length=1,max_length=200)
    draft:dict[str,Any]

def make_editor_router(store:WorkspaceStore)->APIRouter:
    router=APIRouter(prefix='/api/v3/workspaces')

    @router.post('/{workspace_id}/editor-context')
    def context(workspace_id:str,payload:EditorContextRequest):
        return store.editor_context(workspace_id,**payload.model_dump())

    @router.delete('/{workspace_id}/editor-context/{document_id}')
    def invalidate(workspace_id:str,document_id:str,expected_token:str|None=Query(default=None,min_length=1,max_length=128)):
        invalidated=store.invalidate_editor_context(workspace_id,document_id,expected_token=expected_token)
        return {'invalidated':invalidated}

    @router.post('/{workspace_id}/checkpoints')
    def checkpoint(workspace_id:str,payload:CheckpointRequest):
        return store.create_checkpoint(workspace_id,**payload.model_dump())

    @router.get('/{workspace_id}/checkpoints')
    def checkpoints(workspace_id:str,limit:int=Query(default=50,ge=1,le=100),offset:int=Query(default=0,ge=0)):
        return {'items':store.list_checkpoints(workspace_id,limit=limit,offset=offset)}

    @router.post('/{workspace_id}/editor-restore')
    def restore(workspace_id:str,payload:RestoreEditorRequest):
        values=payload.model_dump();values['expected_revision']=values.pop('revision')
        return store.restore_editor(workspace_id,**values)

    return router
