from fastapi import Depends

from .models import TemporaryConnectionImportRequest
from ..remote.temporary_connections import import_temporary_connection
from ..storage.runtime_repository import SQLiteRepository


def register_temporary_connection_routes(app, require_session, require_database, response):
    from .app import ApiError
    @app.post('/api/v3/settings/temporary-connections/import', dependencies=[Depends(require_session)])
    def import_connection(payload: TemporaryConnectionImportRequest, database=Depends(require_database)):
        from ..remote.credential_store import CredentialStore, CredentialStoreError
        with app.state.remote_profile_lock:
            repository = SQLiteRepository(database)
            try:
                credentials = CredentialStore()
                result = import_temporary_connection(repository, credentials,
                    connection_text=payload.connection_text.get_secret_value(),
                    api_key=payload.api_key.get_secret_value() if payload.api_key is not None else None,
                    display_name=payload.display_name, target_profile_id=payload.target_profile_id, serialize=response)
                for manager in (app.state.generation_queue, getattr(app.state, 'workflow_jobs', None)):
                    if manager is not None and hasattr(manager, 'restore_profile'):
                        manager.restore_profile(result['id'])
                return result
            except KeyError:
                raise ApiError(404, 'remote_profile_not_found', '连接不存在。') from None
            except TypeError:
                raise ApiError(409, 'temporary_connection_target_invalid', '只能更新现有 HTTPS 临时连接。') from None
            except ValueError as exc:
                raise ApiError(422, 'temporary_connection_invalid', str(exc)) from None
            except CredentialStoreError:
                raise ApiError(503, 'credential_store_unavailable', '无法安全保存连接密钥，原连接已保留。', retryable=True) from None
            finally:
                repository.close()
