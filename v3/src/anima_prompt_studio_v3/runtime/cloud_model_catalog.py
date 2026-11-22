"""Session-fenced, data-only gateway catalogs and exact asset suggestions."""
import json
import time
from pathlib import Path
from uuid import uuid4
from anima_prompt_studio.domain.execution_models import RemoteCredentials
from ..core.profiles import ModelProfileRegistry
from ..core.model_versions import workflow_models
from ..remote.cloud_model_catalog import parse_catalog, asset_path
from ..remote.comfy_client import ComfyUIClient, ComfyAPIError
from ..remote.connections import connection_factory, client_for_connection, read_runtime_identity
from ..remote.runtime_identity import bind_runtime_identity, confirm_runtime_identity, identity_state
from ..remote.preparation_budget import DirectPreparationTimeout
from ..storage.runtime_repository import SQLiteRepository
from .workflow_catalog import WorkflowCatalog, catalog, fingerprint, apply_mapping, ASSET_INPUTS, TTL
from .packaged_workflows import workflow_revision


def _write(repo, key, value):
    repo.connection.execute('INSERT INTO settings(key,value_json) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json', (key, json.dumps(value, ensure_ascii=False)))


def _signature(repo, remote):
    return [fingerprint(remote), remote.http_session_id, repo.get_setting('environment_epoch:' + remote.id, 0)]


def _specs(info, class_type):
    definition = info.get(class_type, {})
    groups = definition.get('input', {}) if isinstance(definition, dict) else {}
    return {**groups.get('required', {}), **groups.get('optional', {})}


def _choices(spec):
    return spec[0] if isinstance(spec, (list, tuple)) and spec and isinstance(spec[0], (list, tuple)) else []


def assert_runtime_confirmed(repository, profile):
    if identity_state(repository, profile).get('conflicted'):
        raise ValueError('云端运行时身份已变化，请重新导入当前连接后再提交。')


class CloudModelCatalog:
    def __init__(self, database):
        self.database = Path(database)

    def report(self, remote_id):
        repo = SQLiteRepository(self.database)
        try:
            return self._report(repo, repo.get_remote_profile(remote_id))
        finally:
            repo.close()

    def _report(self, repo, remote):
        signature = _signature(repo, remote)
        result = {'remote_profile_id': remote.id, 'session_id': remote.http_session_id,
                  'environment_epoch': signature[2], 'status': 'unchecked', 'checked_at': None,
                  'message': '尚未检查云端模型目录。', 'runtime_id': None, 'items': []}
        if remote.connection_type != 'http':
            return {**result, 'status': 'unsupported', 'message': '此连接使用现有工作流与文件检测。'}
        if identity_state(repo, remote).get('conflicted'):
            return {**result, 'status': 'unavailable', 'message': '云端运行时身份已变化，请重新导入当前连接。'}
        snapshot = repo.get_setting('cloud_model_catalog:' + remote.id)
        if not snapshot:
            return result
        if snapshot['signature'] != signature:
            return {**result, 'status': 'stale', 'message': '连接会话已变化，请刷新云端目录。'}
        result.update({k: snapshot[k] for k in ('status', 'checked_at', 'message', 'runtime_id')})
        if result['status'] != 'ready':
            return result
        capability = repo.get_setting('workflow_capabilities:' + remote.id, {})
        if (not remote.enabled or not remote.connection_ready or time.time() - snapshot['checked_at'] > TTL
                or capability.get('fingerprint') != fingerprint(remote) or capability.get('error')
                or capability.get('environment_epoch', signature[2]) != signature[2]
                or time.time() - capability.get('checked_at', 0) > TTL):
            return {**result, 'status': 'stale', 'message': '目录或节点能力已过期，请重新刷新。'}
        result['items'] = self._items(repo, snapshot['models'], capability.get('object_info', {}))
        return result

    def _items(self, repo, models, info):
        supported = {p.id: p for p in ModelProfileRegistry.built_in().all()}
        workflows = catalog(self.database, repository=repo)
        result = []
        for raw in models:
            item = {k: raw[k] for k in ('id', 'display_name', 'family', 'ready', 'selected_for_startup')}
            item['supported'] = raw['id'] in supported and supported[raw['id']].family.lower() == raw['family'].lower()
            item['assets'] = [{**a, 'ready': any(a['filename'] in _choices(spec) for node in info for name, spec in _specs(info, node).items()
                                               if name in ASSET_INPUTS and self._category_for_input(name, a['category']))} for a in raw['assets']]
            defaults = dict(raw['suggested_defaults'])
            for key, input_name in (('sampler', 'sampler_name'), ('scheduler', 'scheduler')):
                choices = {v for node in info for name, spec in _specs(info, node).items() if name == input_name for v in _choices(spec) if isinstance(v, str)}
                if defaults.get(key) not in choices:
                    defaults.pop(key, None)
            item['suggested_defaults'], item['workflow_mappings'] = defaults, []
            if item['supported']:
                for workflow, _ in workflows:
                    if item['id'] not in workflow_models(workflow):
                        continue
                    errors, mapping = [], {}
                    if not item['ready']:
                        errors.append('云端报告模型文件缺失，请先在笔记本准备该模型。')
                    for node_id, node in workflow.api_workflow.items():
                        specs = _specs(info, node['class_type'])
                        for name in node['inputs']:
                            alias = ('checkpoint' if name in {'unet_name', 'ckpt_name'} else
                                     'text_encoder' if name in {'clip_name', 'clip_name1', 'clip_name2'} else
                                     'vae' if name == 'vae_name' else None)
                            if not alias:
                                continue
                            path = raw.get(alias)
                            asset = asset_path(path) if path else None
                            if not asset or not self._category_for_input(name, asset['category']) or asset['filename'] not in _choices(specs.get(name)):
                                errors.append(f'节点 {node_id}.{name} 没有精确匹配的云端资产。')
                            else:
                                mapping[f'{node_id}.{name}'] = asset['filename']
                    if not errors:
                        resolved = apply_mapping(workflow, mapping)
                        if item["id"] not in workflow_models(resolved):
                            errors.append("映射资产与模型家族或版本不兼容。")
                        client = ComfyUIClient('http://unused', session=object())
                        client._object_info_cache = info
                        errors += ['缺少节点：' + n for n in client.validate_workflow_nodes(resolved.api_workflow)]
                        errors += client.validate_workflow_inputs(resolved.api_workflow)
                    item['workflow_mappings'].append({'workflow_profile_id': workflow.id, 'revision': workflow_revision(workflow),
                                                       'mapping': {} if errors else mapping, 'errors': errors})
            result.append(item)
        return result

    @staticmethod
    def _category_for_input(name, category):
        return category in {'unet_name': {'diffusion_models'}, 'ckpt_name': {'checkpoints'},
                            'clip_name': {'text_encoders', 'clip'}, 'clip_name1': {'text_encoders', 'clip'},
                            'clip_name2': {'text_encoders', 'clip'}, 'vae_name': {'vae'}, 'lora_name': {'loras'}}.get(name, set())

    def _read_catalog(self, remote, client, previous_identity):
        bind_runtime_identity(client, remote, self.database)
        identity = read_runtime_identity(client, remote)
        parsed = parse_catalog(client.read_bounded('/_moss/models'))
        parsed = getattr(client, '_clean', lambda value: value)(parsed)
        if parsed['runtime_id'] and identity and parsed['runtime_id'] != identity:
            raise ComfyAPIError('运行时身份发生变化。', code='runtime_identity_mismatch')
        # An authenticated, versioned catalog also identifies gateways imported
        # as plain URLs; retain the existing profile and import session.
        identity = identity or parsed['runtime_id']
        confirm_runtime_identity(self.database, remote, identity)
        if previous_identity and previous_identity != identity:
            raise ComfyAPIError('运行时身份发生变化。', code='runtime_identity_mismatch')
        return parsed, identity

    def refresh(self, remote_id):
        return self._refresh(remote_id)

    def record_inspection(self, profile, environment_epoch, client, object_info):
        """Reuse one inspection's client and capabilities; never inspect twice."""
        return self._refresh(profile.id, client=client, object_info=object_info,
                             expected_profile=profile, expected_epoch=environment_epoch)

    def _refresh(self, remote_id, *, client=None, object_info=None, expected_profile=None, expected_epoch=None):
        repo = SQLiteRepository(self.database)
        tunnel = None
        inspection = client is not None
        try:
            remote = repo.get_remote_profile(remote_id)
            signature = _signature(repo, remote)
            if remote.connection_type != 'http':
                return self._report(repo, remote)
            if expected_profile is not None and (fingerprint(expected_profile) != signature[0] or expected_epoch != signature[2]):
                return self._report(repo, remote)
            refresh_token = uuid4().hex
            repo.set_setting('cloud_model_catalog_refresh:' + remote_id, refresh_token)
            previous_catalog = repo.get_setting('cloud_model_catalog:' + remote_id, {})
            same_session = previous_catalog.get('signature', [None, None])[1] == remote.http_session_id
            previous_identity = (previous_catalog.get('last_runtime_id') or previous_catalog.get('runtime_id')) if same_session else None
            snapshot = {'signature': signature, 'checked_at': time.time(), 'runtime_id': None, 'models': [],
                        'last_runtime_id': previous_identity, 'identity_changed': bool(same_session and previous_catalog.get('identity_changed')),
                        'status': 'unavailable', 'message': '云端目录读取失败，请检查连接、认证和笔记本服务后重试。'}
            identity_changed = False
            identity_error = None
            try:
                if not remote.enabled or not remote.connection_ready:
                    raise ValueError('disabled')
                if client is None:
                    tunnel = connection_factory(remote, connect_timeout=5)
                    tunnel.open(RemoteCredentials())
                    client = client_for_connection(tunnel, timeout=(5, 10))
                parsed, identity = self._read_catalog(remote, client, previous_identity)
                info = object_info if object_info is not None else client.object_info(refresh=True)
                # Verify the sanitized shape before persisting a ready snapshot.
                # A credential matching a field/path must never leave a broken cache.
                self._items(repo, parsed['models'], info)
                snapshot.update(status='ready', runtime_id=identity, last_runtime_id=identity, identity_changed=False,
                                models=parsed['models'], message='目录已检查；文件就绪不代表模型已加载或出图已验证。')
                snapshot['workflow_revisions'] = {p.id: workflow_revision(p) for p, _ in catalog(self.database)}
            except DirectPreparationTimeout:
                raise
            except ComfyAPIError as exc:
                identity_changed = exc.code.startswith('runtime_identity_')
                identity_error = exc if identity_changed else None
                if exc.code == 'unsupported':
                    snapshot.update(status='unsupported', message='此服务未提供云端模型目录，可继续使用现有工作流检测。')
            except Exception:
                pass
            with repo.connection:
                repo.connection.execute('BEGIN IMMEDIATE')
                current = repo.get_remote_profile(remote_id)
                if signature != _signature(repo, current) or repo.get_setting('cloud_model_catalog_refresh:' + remote_id) != refresh_token:
                    if inspection and identity_error is not None:
                        raise identity_error
                    return self._report(repo, current)
                if identity_changed and not identity_state(repo, current).get('conflicted'):
                    _write(repo, 'environment_epoch:' + remote_id, signature[2] + 1)
                    _write(repo, 'workflow_capabilities:' + remote_id, {})
                    _write(repo, 'environment_probe:' + remote_id, {})
                    snapshot.update(signature=_signature(repo, current), identity_changed=True,
                                    message='云端运行时身份已变化或无法确认，请重新导入当前连接。')
                _write(repo, 'cloud_model_catalog:' + remote_id, snapshot)
                if snapshot['status'] == 'ready':
                    previous = repo.get_setting('workflow_capabilities:' + remote_id, {})
                    _write(repo, 'workflow_capabilities:' + remote_id, {**previous, 'fingerprint': signature[0], 'environment_epoch': signature[2],
                           'checked_at': snapshot['checked_at'], 'object_info': info, 'error': None})
            if inspection and identity_error is not None:
                raise identity_error
            return self._report(repo, current)
        finally:
            if tunnel is not None:
                tunnel.close()
            repo.close()

    def get_submission_mapping(self, remote_id, model_id, workflow_id, object_info):
        """Return a current exact proposal without persisting asset bindings."""
        repo = SQLiteRepository(self.database)
        try:
            remote = repo.get_remote_profile(remote_id)
            report = self._report(repo, remote)
            if report['status'] != 'ready':
                return None
            snapshot = repo.get_setting('cloud_model_catalog:' + remote_id)
            identity = identity_state(repo, remote).get('runtime_id') or remote.http_runtime_id
            if identity and snapshot.get('runtime_id') != identity:
                return None
            item = next((item for item in self._items(repo, snapshot['models'], object_info)
                         if item['id'] == model_id and item['supported'] and item['ready']), None)
            proposal = next((entry for entry in item['workflow_mappings']
                             if entry['workflow_profile_id'] == workflow_id), None) if item else None
            if (not proposal or proposal['errors'] or not proposal['mapping']
                    or snapshot.get('workflow_revisions', {}).get(workflow_id) != proposal['revision']):
                return None
            return dict(proposal['mapping'])
        finally:
            repo.close()

    def apply_mapping(self, remote_id, model_id, workflow_id, session_id, environment_epoch):
        repo = SQLiteRepository(self.database)
        try:
            with repo.connection:
                repo.connection.execute('BEGIN IMMEDIATE')
                remote = repo.get_remote_profile(remote_id)
                result = self._report(repo, remote)
                if (result['status'] != 'ready' or result['session_id'] != session_id or result['environment_epoch'] != environment_epoch):
                    raise ValueError('连接会话或目录已变化，请刷新后重新应用。')
                item = next((i for i in result['items'] if i['id'] == model_id and i['supported'] and i['ready']), None)
                proposal = next((m for m in item['workflow_mappings'] if m['workflow_profile_id'] == workflow_id), None) if item else None
                snapshot = repo.get_setting('cloud_model_catalog:' + remote_id)
                revisions = snapshot.get('workflow_revisions', {})
                if not proposal or proposal['errors'] or not proposal['mapping'] or revisions.get(workflow_id) != proposal['revision']:
                    raise ValueError('模型资产或工作流已变化，没有可应用的精确映射；请刷新目录。')
                WorkflowCatalog(self.database).save_mapping(remote_id, workflow_id, proposal['revision'], proposal['mapping'], repository=repo)
                return self._report(repo, remote)
        finally:
            repo.close()
