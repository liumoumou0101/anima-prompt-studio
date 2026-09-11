"""Session-authenticated workflow management endpoints."""
from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from anima_prompt_studio.domain.execution_models import RemoteCredentials
from ..runtime.workflow_catalog import WorkflowCatalog, InspectionJobs
from .models import RemoteConnectionTestRequest
from ..core.lora_resolution import LoraBindingsRequest, MappingConflict, ResourceUnavailable
from ..runtime.lora_catalog import LoraCatalog


class MappingRequest(BaseModel):
    revision: str
    mapping: dict[str, str] = Field(default_factory=dict, max_length=100)


class RemoteFileRequest(RemoteConnectionTestRequest):
    path: str = Field(max_length=2048)


class EnabledRequest(BaseModel):
    enabled: bool


class RevisionRequest(BaseModel):
    revision: str = Field(max_length=64)


def register_workflow_routes(app, database, require_session):
    manager = WorkflowCatalog(database)
    manager.archive_official_versions()
    jobs = InspectionJobs(manager)
    app.state.workflow_jobs = jobs
    root = "/api/v3/workflows"
    loras = LoraCatalog(manager)

    def guarded(call):
        try:
            return call()
        except KeyError as exc:
            return JSONResponse({"error": {"code": "workflow_not_found", "message": "连接或工作流不存在"}}, status_code=404)
        except MappingConflict as exc:
            return JSONResponse({"error": {"code": "mapping_revision_conflict", "message": str(exc)}}, status_code=409)
        except ResourceUnavailable as exc:
            return JSONResponse({"error": {"code": exc.code, "message": str(exc), "details": exc.details}}, status_code=422)
        except ValueError as exc:
            return JSONResponse({"error": {"code": "workflow_validation_failed", "message": str(exc)}}, status_code=422)
        except (OSError, RuntimeError):
            return JSONResponse({"error": {"code": "workflow_remote_failed", "message": "读取失败，请检查服务器连接和文件路径。"}}, status_code=502)

    @app.get(root + "/catalog", dependencies=[Depends(require_session)])
    def library():
        return guarded(manager.library)

    @app.post(root + "/preview", dependencies=[Depends(require_session)])
    def preview(payload: dict):
        return guarded(lambda: manager.preview_import(payload))

    @app.get(root + "/servers/{remote_id}", dependencies=[Depends(require_session)])
    def report(remote_id: str):
        def read():
            # A fast local check can finish while report() reads SQLite. Capture
            # status first so an older report still tells the UI to poll again.
            inspection = jobs.status(remote_id)
            return {**manager.report(remote_id), "inspection": inspection}
        return guarded(read)

    @app.post(root + "/servers/{remote_id}/inspect", dependencies=[Depends(require_session)])
    def inspect(remote_id: str, payload: RemoteConnectionTestRequest):
        def start():
            remote = manager.remote(remote_id)
            if not remote.connection_ready or not remote.enabled:
                raise ValueError("请启用连接并确认 SSH 指纹。")
            return jobs.start(remote_id, RemoteCredentials(
                password=payload.password.get_secret_value() if payload.password else "",
                passphrase=payload.passphrase.get_secret_value() if payload.passphrase else "",
            ))
        return guarded(start)

    @app.post(root + "/servers/{remote_id}/cancel", dependencies=[Depends(require_session)])
    def cancel(remote_id: str):
        return jobs.cancel(remote_id)

    @app.put(root + "/servers/{remote_id}/{workflow_id}/mapping", dependencies=[Depends(require_session)])
    def mapping(remote_id: str, workflow_id: str, payload: MappingRequest):
        return guarded(lambda: manager.save_mapping(remote_id, workflow_id, payload.revision, payload.mapping))

    @app.get(root + "/servers/{remote_id}/{workflow_id}/lora-bindings", dependencies=[Depends(require_session)])
    def lora_bindings(remote_id: str, workflow_id: str):
        return guarded(lambda: loras.get(remote_id, workflow_id))

    @app.put(root + "/servers/{remote_id}/{workflow_id}/lora-bindings", dependencies=[Depends(require_session)])
    def save_lora_bindings(remote_id: str, workflow_id: str, payload: LoraBindingsRequest):
        return guarded(lambda: loras.save(remote_id, workflow_id, payload))

    @app.post(root + "/import", dependencies=[Depends(require_session)])
    def import_workflow(payload: dict):
        return guarded(lambda: manager.import_profile(payload))

    @app.get(root + "/export/{workflow_id}", dependencies=[Depends(require_session)])
    def export_workflow(workflow_id: str):
        return guarded(lambda: manager.export_profile(workflow_id))

    @app.put(root + "/{workflow_id}/enabled", dependencies=[Depends(require_session)])
    def enabled(workflow_id: str, payload: EnabledRequest):
        return guarded(lambda: manager.set_enabled(workflow_id, payload.enabled))

    @app.get(root + "/{workflow_id}/versions", dependencies=[Depends(require_session)])
    def versions(workflow_id: str):
        return {"items": manager.versions(workflow_id)}

    @app.post(root + "/{workflow_id}/restore", dependencies=[Depends(require_session)])
    def restore(workflow_id: str, payload: RevisionRequest):
        return guarded(lambda: manager.restore_version(workflow_id, payload.revision))

    @app.post(root + "/servers/{remote_id}/read-file", dependencies=[Depends(require_session)])
    def read_file(remote_id: str, payload: RemoteFileRequest):
        return guarded(lambda: manager.read_remote_file(remote_id, payload.path, RemoteCredentials(
            password=payload.password.get_secret_value() if payload.password else "",
            passphrase=payload.passphrase.get_secret_value() if payload.passphrase else "",
        )))

    @app.get(root + "/servers/{remote_id}/diagnostics", dependencies=[Depends(require_session)])
    def diagnostics(remote_id: str):
        def build():
            report = manager.report(remote_id)
            return {"schema": "anima-workflow-diagnostics/1", "checked_at": report["checked_at"],
                    "items": [{k: i[k] for k in ("revision", "origin", "state", "experimental")}
                              for i in report["items"]]}
        return guarded(build)
