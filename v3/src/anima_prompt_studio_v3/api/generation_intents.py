"""Logical generation requests route before one durable, atomic acceptance."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from threading import Lock
from pathlib import Path
import time
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .models import DirectPromptSubmitRequest
from ..core.requirements import RequirementLora, WorkbenchError, compile_state, digest
from ..core.workflow_parameters import resolve_generation_parameters
from ..runtime.environment_probe import EnvironmentProbe
from ..runtime.environment_router import EnvironmentRouter
from ..runtime.generation import GenerationSettings
from ..runtime.lora_catalog import LoraCatalog
from ..runtime.packaged_workflows import workflow_revision
from ..runtime.workflow_catalog import WorkflowCatalog, fingerprint
from ..storage.generation_intents import IntentStore, LeaseLost
from ..storage.runtime_repository import SQLiteRepository


class ExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['auto', 'pinned'] = 'auto'
    preferredEnvironmentIds: list[str] = Field(default_factory=list, max_length=100)
    environmentId: str | None = None


class GenerationIntentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: dict
    creationConfiguration: dict
    executionPolicy: ExecutionPolicy


def public_intent(record):
    return {key: record[key] for key in ('id', 'state', 'reason', 'retryable', 'candidate_progress',
                                        'resolved_target', 'submission_id', 'run_id', 'response', 'updated_at')}


class GenerationIntentService:
    def __init__(self, workspaces, submissions, bridge, database, *, probe=None, candidates=None, eligible=None, clock=time.monotonic):
        self.store, self.submissions, self.bridge = IntentStore(workspaces), submissions, bridge
        self.database, self.clock = database, clock
        self.manager = WorkflowCatalog(database) if database else None
        self.probe = probe or EnvironmentProbe(database, credentials=self._credentials)
        self.candidates_override, self.eligible_override = candidates, eligible
        self.executor, self.jobs, self.lock = ThreadPoolExecutor(max_workers=2, thread_name_prefix='anima-intent'), {}, Lock()
        self.validation_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='anima-intent-validation')

    def _credentials(self, remote_id):
        from anima_prompt_studio.domain.execution_models import RemoteCredentials
        vault = getattr(self.submissions.queue, '_passphrase_vault', None)
        return RemoteCredentials(passphrase=vault.get(remote_id) if vault else '')

    def _payload(self, body, remote_id='routing-pending'):
        workflow = body['creationConfiguration'].get('workflow', {})
        if not workflow.get('id') or not workflow.get('revision'):
            raise WorkbenchError('invalid_request', '必须明确选择工作流及版本。')
        source = deepcopy(body['source'])
        if 'remote_profile_id' in source or 'workflow_profile_id' in source:
            raise WorkbenchError('invalid_request', '执行环境必须由独立策略指定。')
        return DirectPromptSubmitRequest(**source, remote_profile_id=remote_id, workflow_profile_id=workflow['id'])

    def _prepare(self, payload):
        return self.bridge.prepare_direct(positive_prompt=payload.positive_prompt, negative_prompt=payload.negative_prompt,
            model_profile_id=payload.model_profile, project_name=payload.project_name,
            settings=GenerationSettings(**payload.settings.model_dump()))

    def _preflight(self, body):
        payload = self._payload(body)
        policy = body['executionPolicy']
        if policy['mode'] == 'pinned' and not policy.get('environmentId'):
            raise WorkbenchError('invalid_request', '固定模式需要指定执行环境。')
        configured_model = body['creationConfiguration'].get('modelProfile')
        if configured_model and configured_model != payload.model_profile:
            raise WorkbenchError('invalid_request', '创作配置与提交模型不一致。')
        prepared = self._prepare(payload)
        frozen, source_run_id = None, payload.workflow_snapshot_run_id
        resources = [RequirementLora.model_validate(item.model_dump()) for item in payload.lora_selection]
        if payload.submission_kind == 'conversational':
            workspace = self.store.workspaces.get(payload.workspace_id)
            if workspace['revision'] != payload.workspace_revision:
                from .workspace_store import WorkspaceRevisionConflictError
                raise WorkspaceRevisionConflictError(workspace['revision'])
            draft = workspace['draft']
            if not draft.get('compiled') or draft['compiled']['compiled_token'] != payload.compiled_token or (not payload.use_current_prompt and compile_state(draft) != 'fresh'):
                raise WorkbenchError('stale_compiled_prompt', '编译内容已变化，请重新提交。')
            resources = [RequirementLora.model_validate(item) for item in (draft.get('requirements') or {}).get('loras', [])]
            generation_source = draft.get('generation_source')
            if generation_source:
                if generation_source['workflow_profile_id'] != payload.workflow_profile_id or generation_source['model_profile'] != payload.model_profile:
                    raise WorkbenchError('incompatible_workflow', '请先解除原工作流快照，再更换模型或工作流。')
                source_run_id = generation_source['run_id']
        if payload.submission_kind == 'reference':
            reference = self.submissions.reference_get(payload.reference_preset_id, payload.source_version)
            if not reference['requirements_valid']:
                raise WorkbenchError('empty_requirements', '参考图尚无有效要求。')
            if 'lora_selection' not in payload.model_fields_set:
                resources = [RequirementLora.model_validate(item) for item in reference['requirements']['loras'] if item['required']]
        if source_run_id:
            frozen = self.submissions.queue.get(source_run_id).request_json.get('workflow_snapshot')
            if not frozen:
                raise WorkbenchError('workflow_snapshot_missing', '原任务没有可用工作流快照。')
            from anima_prompt_studio.domain.execution_models import WorkflowProfile
            frozen_profile = WorkflowProfile.model_validate(frozen)
            if frozen_profile.id != payload.workflow_profile_id:
                raise WorkbenchError('incompatible_workflow', '所选工作流与原图快照不一致。')
        if self.manager:
            profile = frozen_profile if frozen else LoraCatalog(self.manager).profile(payload.workflow_profile_id)
            revision = profile.runtime_assets.get('binding_template_revision', workflow_revision(profile))
            if revision != body['creationConfiguration']['workflow']['revision']:
                raise WorkbenchError('workflow_version_changed', '工作流版本已变化，请确认创作配置后重新生成。')
            from ..core.generation_recipes import validate_job_recipe
            from ..core.model_versions import model_matches_workflow
            if not model_matches_workflow(payload.model_profile, profile):
                raise WorkbenchError('incompatible_model', '模型与工作流不兼容。')
            validate_job_recipe(prepared.job, profile)
            resolved = resolve_generation_parameters(profile, prepared.job.generation_params,
                payload.settings.workflow_parameter_overrides, requested_schema=payload.settings.parameter_schema)
            prepared.job.integration_metadata['parameter_schema'] = resolved['schema']
            prepared.job.integration_metadata['workflow_parameters'] = resolved
        return payload, prepared, resources, frozen

    def _candidates(self, snapshot, policy, *, repository=None):
        if self.candidates_override:
            return self.candidates_override(snapshot, policy)
        repo = repository or SQLiteRepository(self.database)
        try:
            result = []
            workflow_id = snapshot['creationConfiguration']['workflow']['id']
            last_success = repo.get_setting('environment_last_success', None)
            if not last_success:
                last_success = next((run.remote_profile_id for run in repo.list_generation_runs(limit=1000)
                                     if run.state.value == 'completed'), None)
            for profile in repo.list_remote_profiles(enabled_only=True):
                if policy['mode'] == 'auto' and not repo.get_setting('environment_auto_allowed:' + profile.id, True):
                    continue
                epoch = repo.get_setting('environment_epoch:' + profile.id, 0)
                mapping = repo.get_setting('workflow_mapping:' + profile.id + ':' + workflow_id, {})
                loras = repo.get_setting(LoraCatalog.key(profile.id, workflow_id), {})
                confirmation = repo.get_setting('environment_asset_confirmation:' + profile.id + ':' + workflow_id, {})
                evidence = {'profile': fingerprint(profile), 'epoch': epoch, 'workflow': snapshot['creationConfiguration']['workflow'],
                            'mapping': mapping, 'loras': loras, 'confirmation': confirmation}
                result.append({'id': profile.id, 'profile': profile, 'epoch': epoch, 'signature': digest(evidence),
                               'display_name': profile.display_name, 'mapping': mapping, 'confirmation': confirmation,
                               'last_success': last_success == profile.id})
            return result
        finally:
            if repository is None:
                repo.close()

    def create(self, request, key):
        body = request.model_dump(mode='json') if isinstance(request, GenerationIntentRequest) else deepcopy(request)
        # Lookup precedes validation of mutable workspace/resources on replay.
        entry = self.store.create(key, body)
        if entry['state'] not in {'accepted', 'canceled'}:
            self.schedule(entry['id'])
        return public_intent(self.store.get(entry['id']))

    def schedule(self, intent_id, *, recheck=False):
        with self.lock:
            if intent_id in self.jobs and not self.jobs[intent_id].done():
                return
            self.jobs[intent_id] = self.executor.submit(self.resolve, intent_id, recheck=recheck)

    def resolve(self, intent_id, *, recheck=False):
        epoch = self.store.acquire(intent_id, uuid4().hex)
        if epoch is None:
            return public_intent(self.store.get(intent_id))
        record = self.store.get(intent_id)
        body, progress = record['request'], record['candidate_progress']
        try:
            payload, prepared, resources, frozen = self._preflight(body)
            planned = {}
            def candidates(snapshot, policy):
                return [{**candidate, 'recheck': recheck} for candidate in self._candidates(snapshot, policy)]
            def eligible(snapshot, candidate, evidence):
                if self.eligible_override:
                    okay, reasons = self.eligible_override(snapshot, candidate, evidence)
                    if not okay:
                        return okay, reasons
                if self.manager:
                    mapping, confirmation = candidate.get('mapping', {}), candidate.get('confirmation', {})
                    workflow = body['creationConfiguration']['workflow']
                    mapping_current = (mapping.get('revision') == workflow['revision'] and mapping.get('fingerprint') == fingerprint(candidate['profile'])
                                       and mapping.get('environment_epoch', 0) == candidate['epoch'])
                    confirmed = (confirmation.get('epoch') == candidate['epoch'] and confirmation.get('fingerprint') == fingerprint(candidate['profile'])
                                 and confirmation.get('workflow_revision') == workflow['revision'] and confirmation.get('mapping_hash') == digest(mapping))
                    if evidence.identity_strength == 'weak':
                        # Filename maps cannot prove weights after an undetectable replacement.
                        confirmed = confirmed and 0 <= time.time() - confirmation.get('confirmed_at', 0) <= 30
                        if not confirmed:
                            return False, ['resource_identity_unconfirmed']
                    if body['executionPolicy']['mode'] == 'auto' and not (mapping_current or confirmed):
                        return False, ['resource_identity_unconfirmed']
                    # An epoch change invalidates old mappings even in pinned mode.
                    if candidate['epoch'] and not confirmed and not mapping_current:
                        return False, ['resource_identity_unconfirmed']
                try:
                    planned[candidate['id']] = self.submissions.queue.plan_cached(prepared, candidate['id'], payload.workflow_profile_id, resources, frozen)
                    # Freeze the locally resolved schema and actual parameters at acceptance.
                    planned_job, planned_target, _ = planned[candidate['id']]
                    resolved = resolve_generation_parameters(planned_target.workflow_profile,
                        planned_job.job.generation_params, payload.settings.workflow_parameter_overrides)
                    planned_job.job.integration_metadata.update(parameter_schema=resolved['schema'], workflow_parameters=resolved)
                    return True, []
                except Exception as exc:
                    return False, [getattr(exc, 'code', 'incompatible_resources')]
            async def bounded_eligible(snapshot, candidate, evidence):
                future = self.validation_executor.submit(eligible, snapshot, candidate, evidence)
                return await asyncio.shield(asyncio.wrap_future(future))
            router = EnvironmentRouter(candidates, self.probe, bounded_eligible, clock=self.clock)
            result = asyncio.run(router.resolve_environment(body, body['executionPolicy'], self.clock() + 15, progress=progress, recheck=recheck))
            progress = result['progress']
            candidate = result['target']
            if candidate is None:
                self.store.block(intent_id, epoch, progress, result['reason'], result['retryable'])
            else:
                remote_id = candidate['id']
                target = {key: candidate[key] for key in ('id', 'epoch', 'signature', 'display_name') if key in candidate}
                target['workflow'] = body['creationConfiguration']['workflow']
                locked_repository = [None]
                shared_database = bool(self.database and Path(self.database).resolve() == Path(self.store.workspaces.path).resolve())
                @contextmanager
                def acceptance_context():
                    if self.database is None or shared_database:
                        yield
                        return
                    repo = SQLiteRepository(self.database)
                    try:
                        # Serialize environment/mapping edits through acceptance, including WAL databases.
                        repo.connection.execute('BEGIN IMMEDIATE')
                        locked_repository[0] = repo
                        yield
                    finally:
                        locked_repository[0] = None
                        repo.connection.rollback()
                        repo.close()
                def verify(acceptance_db):
                    if shared_database:
                        locked_repository[0] = SQLiteRepository.from_connection(self.database, acceptance_db)
                    current = next((c for c in self._candidates(body, body['executionPolicy'], repository=locked_repository[0]) if c['id'] == remote_id), None)
                    if current is None or current.get('signature') != candidate.get('signature'):
                        raise WorkbenchError('environment_changed', '接受前执行环境或资源映射已变化，请重新检查。')
                    evidence = progress.get('checked', {}).get(remote_id, {}).get('probe', {})
                    if self.manager and evidence.get('identity_strength') == 'weak' and not (
                            0 <= time.time() - current.get('confirmation', {}).get('confirmed_at', 0) <= 30):
                        raise WorkbenchError('resource_identity_unconfirmed', '当前环境的资源确认已过期，请重新确认映射。')
                    if self.manager and frozen is None:
                        profile = LoraCatalog(self.manager).profile(payload.workflow_profile_id, repository=locked_repository[0])
                        if workflow_revision(profile) != body['creationConfiguration']['workflow']['revision']:
                            raise WorkbenchError('workflow_version_changed', '接受前工作流版本已变化。')
                    # Source version/revision validation is repeated by SubmissionStore under this transaction.
                actual = self._payload(body, remote_id)
                self.submissions.submit(actual, 'intent-v1:' + intent_id, 'direct', lambda: deepcopy(prepared),
                    planned=planned[remote_id], acceptance_hook=self.store.acceptance(intent_id, epoch, target, progress, verify),
                    acceptance_context=acceptance_context)
        except LeaseLost:
            pass
        except Exception as exc:
            reason = getattr(exc, 'code', None) or ('workspace_revision_conflict' if type(exc).__name__ == 'WorkspaceRevisionConflictError'
                else 'invalid_parameters' if type(exc).__name__ == 'ParameterValidationError'
                else 'queue_full' if type(exc).__name__ == 'GenerationQueueFullError' else 'invalid_request')
            retryable = reason in {'environment_changed', 'resource_identity_unconfirmed'} or type(exc).__name__ == 'GenerationQueueFullError'
            if type(exc).__name__ in {'ParameterValidationError', 'WorkbenchError', 'ValidationError', 'WorkspaceRevisionConflictError'}:
                progress = {**progress, 'input_error': {'message': str(exc), 'fields': getattr(exc, 'errors', None) if isinstance(getattr(exc, 'errors', None), dict) else None}}
            try:
                self.store.block(intent_id, epoch, progress, reason, retryable)
            except LeaseLost:
                pass
        return public_intent(self.store.get(intent_id))

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.validation_executor.shutdown(wait=False, cancel_futures=True)
        if hasattr(self.probe, 'close'):
            self.probe.close()


def install_generation_intents(app, workspaces, submissions, bridge, database, require_session):
    service = GenerationIntentService(workspaces, submissions, bridge, database)
    app.state.generation_intent_service = service
    router = APIRouter(prefix='/api/v3', dependencies=[Depends(require_session)])

    @router.post('/generation-intents', status_code=202)
    def create(payload: GenerationIntentRequest, idempotency_key: str = Header(alias='Idempotency-Key')):
        try:
            return service.create(payload, idempotency_key)
        except ValueError as exc:
            from ..storage.generation_submissions import IdempotencyConflict
            if isinstance(exc, IdempotencyConflict):
                raise
            raise WorkbenchError('invalid_request', '幂等键必须是 1–256 个字符。') from exc

    @router.get('/generation-intents/{intent_id}')
    def get(intent_id: str):
        try:
            return public_intent(service.store.recover_expired(intent_id))
        except KeyError:
            raise HTTPException(404, '生成意图不存在。') from None

    @router.post('/generation-intents/{intent_id}/retry-resolution', status_code=202)
    def retry(intent_id: str):
        entry = get(intent_id)
        if entry['state'] not in {'accepted', 'canceled'} and entry['retryable']:
            # Unchecked candidates always continue first; a finished round explicitly rechecks.
            service.schedule(intent_id, recheck=not bool(entry['candidate_progress'].get('unchecked')))
        return get(intent_id)

    @router.post('/generation-intents/{intent_id}/cancel')
    def cancel(intent_id: str):
        get(intent_id)
        return public_intent(service.store.cancel(intent_id))

    @router.post('/execution-environments/{environment_id}/rebuilt')
    def rebuilt(environment_id: str):
        repo = SQLiteRepository(database)
        try:
            return {'environment_id': environment_id, 'environment_epoch': repo.rebuild_environment(environment_id)}
        finally:
            repo.close()

    @router.post('/execution-environments/{environment_id}/confirm-assets')
    def confirm_assets(environment_id: str, payload: dict):
        workflow_id, revision = payload.get('workflow_id'), payload.get('revision')
        repo = SQLiteRepository(database)
        try:
            profile = repo.get_remote_profile(environment_id)
            if payload.get('intent_id'):
                intent = service.store.get(payload['intent_id'])
                if intent['state'] in {'accepted', 'canceled'}:
                    raise HTTPException(409, '该意图已结束。')
                workflow = intent['request']['creationConfiguration']['workflow']
                if workflow != {'id': workflow_id, 'revision': revision}:
                    raise HTTPException(409, '确认的工作流与冻结请求不一致。')
                source, prepared, resources, frozen = service._preflight(intent['request'])
                # Validate the exact retained graph, even if the current library has advanced.
                service.submissions.queue.plan_cached(prepared, environment_id, source.workflow_profile_id, resources, frozen)
            else:
                template = LoraCatalog(service.manager).profile(workflow_id)
                if workflow_revision(template) != revision:
                    raise HTTPException(409, '工作流版本已变化。')
                report = service.manager.report(environment_id)
                item = next((item for item in report['items'] if item['workflow_id'] == workflow_id), None)
                if not item or item['state'] != 'ready':
                    raise HTTPException(409, '请先完成当前环境检测并确认文件映射。')
            mapping = repo.get_setting('workflow_mapping:' + environment_id + ':' + workflow_id, {})
            repo.set_setting('environment_asset_confirmation:' + environment_id + ':' + workflow_id,
                             {'epoch': repo.get_setting('environment_epoch:' + environment_id, 0), 'fingerprint': fingerprint(profile),
                              'workflow_revision': revision, 'mapping_hash': digest(mapping), 'confirmed_at': time.time()})
            return {'confirmed': True}
        finally:
            repo.close()

    app.include_router(router)
    app.router.add_event_handler('shutdown', service.close)
    return service
