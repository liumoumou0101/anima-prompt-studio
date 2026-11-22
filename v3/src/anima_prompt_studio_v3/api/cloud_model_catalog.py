from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from ..runtime.cloud_model_catalog import CloudModelCatalog


class ApplyCloudMappingRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model_id: str = Field(min_length=1, max_length=128)
    workflow_profile_id: str = Field(min_length=1, max_length=256)
    session_id: str = Field(min_length=1, max_length=256)
    environment_epoch: StrictInt = Field(ge=0)


def register_cloud_model_catalog_routes(app, require_session, require_database):
    from .app import ApiError
    prefix = '/api/v3/settings/remote-profiles/{remote_id}/model-catalog'

    def invoke(database, method, remote_id, *args):
        try:
            return getattr(CloudModelCatalog(database), method)(remote_id, *args)
        except KeyError:
            raise ApiError(404, 'remote_profile_not_found', '连接不存在。') from None
        except ValueError as exc:
            raise ApiError(409, 'cloud_catalog_conflict', str(exc)) from None

    @app.get(prefix, dependencies=[Depends(require_session)])
    def get_catalog(remote_id: str, database=Depends(require_database)):
        return invoke(database, 'report', remote_id)

    @app.post(prefix + '/refresh', dependencies=[Depends(require_session)])
    def refresh_catalog(remote_id: str, database=Depends(require_database)):
        return invoke(database, 'refresh', remote_id)

    @app.post(prefix + '/apply-mapping', dependencies=[Depends(require_session)])
    def apply_catalog_mapping(remote_id: str, payload: ApplyCloudMappingRequest, database=Depends(require_database)):
        with app.state.remote_profile_lock:
            return invoke(database, 'apply_mapping', remote_id, payload.model_id, payload.workflow_profile_id,
                          payload.session_id, payload.environment_epoch)
