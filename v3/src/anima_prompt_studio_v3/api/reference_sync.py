"""Discover known local collections and expose a background import's status."""
from pathlib import Path
import sys

from fastapi import Depends

from ..core.requirements import ContractModel
from ..storage.reference_sync import LocalReferenceSync


class RescanLocalReferences(ContractModel):
    pass


def local_reference_source(workspace_db: Path, frontend_dist: Path | None) -> Path | None:
    """Use explicit app locations only; never walk parents or the current directory."""
    state = workspace_db.resolve().parent
    candidates = [state / "anima-ref"]
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "anima-ref")
    if frontend_dist is not None:
        frontend = frontend_dist.resolve()
        if frontend.parent.name == "web" and frontend.parent.parent.name == "v3":
            candidates.append(frontend.parent.parent.parent / "anima-ref")
    if state.name == "state" and state.parent.name == ".local" and state.parent.parent.name == "v3":
        candidates.append(state.parent.parent.parent / "anima-ref")
    return next((candidate for candidate in candidates if candidate.is_dir()), None)


def register_local_sync_routes(app, store, workspace_db, require_session):
    sync = LocalReferenceSync(store, lambda: local_reference_source(Path(workspace_db), app.state.frontend_dist))
    app.state.reference_sync = sync
    app.router.add_event_handler("startup", sync.start)
    app.router.add_event_handler("shutdown", sync.close)
    dependencies = [Depends(require_session)]
    prefix = "/api/v3/reference-examples/local-sync"

    @app.get(prefix, dependencies=dependencies)
    def local_sync_status():
        return sync.status()

    @app.post(prefix, dependencies=dependencies)
    def rescan_local_references(payload: RescanLocalReferences):
        return sync.start()
