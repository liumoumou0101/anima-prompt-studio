"""Explicit raw prompt appends and durable recovery receipts; no generation."""
from __future__ import annotations

from fastapi import Depends
from pydantic import ConfigDict, Field

from ..core.requirements import ContractModel, WorkbenchError
from .workspace_store import WorkspaceStore


class PersonalPromptAppendRequest(ContractModel):
    model_config = ConfigDict(str_strip_whitespace=False)
    transfer_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    revision: int = Field(ge=1)
    positive: str = Field(max_length=20_000)
    negative: str = Field(max_length=20_000)


class PersonalPromptUndoRequest(ContractModel):
    revision: int = Field(ge=1)


def register_personal_prompt_transfer_routes(app, require_workspace_store, require_session):
    def prepare_write(workspace_id: str):
        conversation = app.state.conversation_service
        submissions = app.state.submission_service
        run_ids = set()
        busy = False
        if submissions is not None:
            # Queue acceptance locks queue -> workspace DB. Read queue state
            # BEFORE taking the DB write lock, never in the opposite order.
            run_ids = set(submissions.store.workspace_run_ids(workspace_id))
            terminal = {"completed", "failed", "canceled", "remote_missing"}
            busy = any(submissions.queue.get(run_id).state.value not in terminal for run_id in run_ids)

        def require_idle(connection):
            if conversation is not None and workspace_id in conversation.active:
                raise WorkbenchError("workspace_busy", "工作台正在更新提示词，请完成后再追加或撤销。")
            # A submission accepted after the queue snapshot must also block.
            # This read shares the mutation transaction and acquires no queue lock.
            current_ids = ({row[0] for row in connection.execute(
                "SELECT run_id FROM generation_submissions WHERE workspace_id=?", (workspace_id,))}
                if submissions is not None else set())
            if busy or current_ids != run_ids:
                raise WorkbenchError("workspace_busy", "工作台正在生成，请完成后再追加或撤销。")
        return require_idle

    if app.state.workspace_store is not None:
        # Only the captured guard runs inside BEGIN IMMEDIATE, after receipt
        # replay handling. Busy state never rejects an already-applied request.
        app.state.workspace_store.prepare_personal_prompt_write = prepare_write

    base = "/api/v3/workspaces/{workspace_id}/personal-prompt-transfers"

    @app.post(base, dependencies=[Depends(require_session)])
    def append(workspace_id: str, payload: PersonalPromptAppendRequest,
               store: WorkspaceStore = Depends(require_workspace_store)) -> dict:
        return store.append_personal_prompt(workspace_id, transfer_id=payload.transfer_id,
            expected_revision=payload.revision, positive=payload.positive, negative=payload.negative)

    @app.get(base + "/{transfer_id}", dependencies=[Depends(require_session)])
    def receipt(workspace_id: str, transfer_id: str,
                store: WorkspaceStore = Depends(require_workspace_store)) -> dict:
        return store.get_personal_prompt_transfer(workspace_id, transfer_id)

    @app.post(base + "/{transfer_id}/undo", dependencies=[Depends(require_session)])
    def undo(workspace_id: str, transfer_id: str, payload: PersonalPromptUndoRequest,
             store: WorkspaceStore = Depends(require_workspace_store)) -> dict:
        return store.undo_personal_prompt(workspace_id, transfer_id=transfer_id, expected_revision=payload.revision)
