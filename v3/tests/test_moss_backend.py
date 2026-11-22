import asyncio
import importlib
import json
import pytest
from anima_prompt_studio_v3.core.profiles import ModelProfileRegistry
from anima_prompt_studio_v3.core.runtime_profiles import V3RuntimeProfiles
from anima_prompt_studio_v3.runtime.packaged_workflows import packaged_workflow_profiles
from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter, GenerationSettings
from anima_prompt_studio_v3.core.workflow_compiler import V3WorkflowCompiler
from anima_prompt_studio.domain.execution_models import RemoteProfile

MODEL = "moss_image_sft_int8"

def test_moss_family_workflow_and_raw_chinese():
    assert ModelProfileRegistry.built_in().get(MODEL).family == "moss"
    model = V3RuntimeProfiles().get_model(MODEL)
    assert (model.steps, model.cfg, model.sampler, model.scheduler, model.default_width, model.default_height) == (25, 2.5, "er_sde", "simple", 1024, 1024)
    workflow = next(w for w in packaged_workflow_profiles() if w.id == "v3_moss_image_sft_int8")
    prepared = CandidateToPromptJobAdapter().prepare_direct(positive_prompt='宫廷肖像，牌子写着“春天”', negative_prompt='不要眼镜', model_profile_id=MODEL)
    graph = V3WorkflowCompiler().render(prepared.job, workflow, RemoteProfile(id="test", display_name="test", ssh_host="localhost", ssh_user="test"), MODEL, "abc").workflow
    assert graph["4"]["inputs"]["text"] == '宫廷肖像，牌子写着“春天”'
    assert graph["5"]["inputs"]["text"] == '不要眼镜'
    assert graph["6"]["class_type"] == "EmptyFlux2LatentImage"
    assert graph["3"]["inputs"]["type"] == "moss_image"
    assert graph["1"]["inputs"]["unet_name"] == "moss_image_sft_int8_convrot.safetensors"
    assert graph["3"]["inputs"]["clip_name"] == "qwen3.5_9b_w4a8_gptq.safetensors"
    assert graph["8"]["inputs"]["vae_name"] == "flux2-vae_small.safetensors"

@pytest.mark.parametrize("width,height", [(1032,1024),(1024,1032)])
def test_moss_rejects_non_16_dimensions(width,height):
    with pytest.raises(ValueError, match="16"):
        CandidateToPromptJobAdapter().prepare_direct(positive_prompt="中文", model_profile_id=MODEL, settings=GenerationSettings(width=width,height=height))

@pytest.mark.parametrize("mode", ["polish", "expand"])
def test_assist_preserves_chinese_quotes_negative_and_instructions(monkeypatch, mode):
    moss = importlib.import_module("anima_prompt_studio_v3.api.moss")
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    async def complete(**kwargs):
        instruction = kwargs["messages"][0]["content"]
        assert "中文" in instruction and mode in instruction
        assert ("不增加" if mode == "polish" else "适量") in instruction
        return {"text": json.dumps({"positive": '少女举着“春天”招牌', "negative":" 不要眼镜 ", "changes":[], "warnings":[]},ensure_ascii=False)}
    monkeypatch.setattr(LLMService,"complete",complete)
    result=asyncio.run(moss.assist_prompt(moss.MossPromptAssistRequest(source_text='少女，招牌写着“春天”',negative_prompt=" 不要眼镜 ",mode=mode)))
    assert result["negative"] == " 不要眼镜 "
    assert "春天" in result["positive"] and result["mode"] == mode

@pytest.mark.parametrize("positive,negative", [('少女举着春天招牌','不要眼镜'),('少女举着“春”招牌','不要眼镜'),('少女举着“春天”招牌','眼镜')])
@pytest.mark.real_rewrite_review
def test_assist_rejects_altered_quotes_or_negative(monkeypatch,positive,negative):
    moss=importlib.import_module("anima_prompt_studio_v3.api.moss")
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    async def complete(**kwargs):
        if kwargs.get("task") == "rewrite_review":
            return {"text":json.dumps({"issues":["招牌上的文字必须连同引号逐字保留。"],"conflicts":[]})}
        return {"text":json.dumps(dict(positive=positive,negative=negative,changes=[],warnings=[]))}
    monkeypatch.setattr(LLMService,"complete",complete)
    with pytest.raises(RuntimeError):
        asyncio.run(moss.assist_prompt(moss.MossPromptAssistRequest(source_text='招牌写着“春天”',negative_prompt="不要眼镜",mode="polish")))

def test_assist_sanitizes_transport_exception(monkeypatch):
    moss=importlib.import_module("anima_prompt_studio_v3.api.moss")
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    async def complete(**kwargs):
        raise RuntimeError("https://secret.example sk-secret-token")
    monkeypatch.setattr(LLMService,"complete",complete)
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(moss.assist_prompt(moss.MossPromptAssistRequest(source_text="少女",mode="polish")))
    assert "secret" not in str(exc.value)


def test_moss_import_infers_family_from_loader_not_prompt():
    from anima_prompt_studio_v3.runtime.workflow_import import profile_from_api
    w=next(w for w in packaged_workflow_profiles() if w.id == "v3_moss_image_sft_int8")
    w.api_workflow["4"]["inputs"]["text"]="anima-aesthetic-v1.1.safetensors"
    imported=profile_from_api(w.api_workflow)
    assert imported.compatible_model_profiles == [MODEL]


def test_moss_workflow_rejects_cross_family_assets():
    from anima_prompt_studio_v3.core.model_versions import workflow_models
    w=next(w for w in packaged_workflow_profiles() if w.id == "v3_moss_image_sft_int8")
    w.api_workflow["1"]["inputs"]["unet_name"]="anima-base.safetensors"
    assert workflow_models(w) == []


def test_moss_rejects_anima_llm_compile_and_tag_generator():
    from anima_prompt_studio_v3.core.requirements import compile_prompt, PromptEdit, WorkbenchError
    from anima_prompt_studio_v3.core.literal import LiteralCandidateGenerator, LiteralGenerationError
    from anima_prompt_studio_v3.domain import IntentDocument
    with pytest.raises(WorkbenchError, match="MOSS"):
        compile_prompt({"model_profile":MODEL},PromptEdit(positive="a girl",negative=""),source="llm")
    with pytest.raises(LiteralGenerationError, match="MOSS"):
        LiteralCandidateGenerator(None).generate(None,ModelProfileRegistry.built_in().get(MODEL))


def test_moss_only_baseline_recipe():
    from anima_prompt_studio_v3.core.generation_recipes import build_workflow_recipe_contract
    w=next(w for w in packaged_workflow_profiles() if w.id == "v3_moss_image_sft_int8")
    c=build_workflow_recipe_contract(w)
    assert c["default_recipe_id"] == "moss_baseline"
    assert len(c["generation_recipes"]) == 1


def test_moss_quote_protection_handles_nested_repeated_multiline():
    moss=importlib.import_module("anima_prompt_studio_v3.api.moss")
    original='招牌“春\n天「好」”，另一个“春\n天「好」”，注释" hello "'
    assert not moss.protected_quotes(original) - moss.protected_quotes(original)
    assert moss.protected_quotes(original) - moss.protected_quotes('招牌“春\n天「好」”，注释" hello "')


def test_moss_api_session_schema_and_review_only(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from anima_prompt_studio_v3.api import create_api_runtime
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    runtime=create_api_runtime(tmp_path / "missing.db")
    async def complete(**kwargs):
        return {"text": json.dumps(dict(positive="中文少女",negative="",changes=[],warnings=[]))}
    monkeypatch.setattr(LLMService,"complete",complete)
    with TestClient(runtime.app,base_url="http://127.0.0.1",raise_server_exceptions=False) as client:
        path="/api/v3/moss/prompt-assist"
        assert client.post(path,json={"source_text":"少女","mode":"polish"},headers={"Origin":"http://127.0.0.1"}).status_code == 401
        response=client.post("/api/v3/session/exchange",json={"bootstrap_token":runtime.bootstrap_token},headers={"Origin":"http://127.0.0.1"})
        headers={"Origin":"http://127.0.0.1","X-Anima-Session":response.json()["session_token"]}
        response=client.post(path,json={"source_text":"少女","mode":"polish"},headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["positive"] == "中文少女"
        assert client.post(path,json={"source_text":"少女","mode":"translate"},headers=headers).status_code == 422
        options=client.get("/api/v3/bootstrap",headers=headers).json()["model_profile_options"]
        assert next(o for o in options if o["id"] == MODEL)["family"] == "moss"
        assert all(o["family"] == "anima" for o in options if o["id"] != MODEL)


def test_moss_catalog_raw_intent_freezes_graph_and_replay(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from anima_prompt_studio_v3.api.generation_intents import GenerationIntentService
    from anima_prompt_studio_v3.api.workspace_store import WorkspaceStore
    from anima_prompt_studio_v3.runtime.generation_queue import build_generation_queue
    from anima_prompt_studio_v3.runtime.submissions import SubmissionService
    from anima_prompt_studio_v3.runtime.workflow_catalog import WorkflowCatalog
    from anima_prompt_studio_v3.runtime.environment_probe import ProbeResult
    from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    from test_workflow_catalog import capabilities
    monkeypatch.setattr(LLMService,"complete", lambda **kwargs: pytest.fail("raw generation must not call LLM"))
    database=tmp_path / "runtime.db"
    repo=SQLiteRepository(database)
    repo.save_remote_profile(RemoteProfile(id="server",display_name="test",ssh_host="example.invalid",ssh_user="test",known_host_fingerprint="SHA256:test"))
    repo.close()
    manager=WorkflowCatalog(database)
    capabilities(manager,"server")
    workflow=next(w for w in manager.library()["items"] if w["workflow_id"] == "v3_moss_image_sft_int8")
    assert next(w for w in manager.report("server")["items"] if w["workflow_id"] == workflow["workflow_id"])["state"] == "ready"
    manager.save_mapping("server",workflow["workflow_id"],workflow["revision"],{})
    queue=build_generation_queue(database,credential_store=SimpleNamespace(read_password=lambda _: "fake"))
    workspaces=WorkspaceStore(tmp_path/"workspaces.db")
    submissions=SubmissionService(workspaces,queue,lambda run:{"id":run.id},start=False)
    async def probe(candidate,deadline,epoch):
        return ProbeResult(candidate["id"],epoch,1,"online","ready",[],"strong")
    service=GenerationIntentService(workspaces,submissions,CandidateToPromptJobAdapter(),database,probe=probe)
    body={"source":{"positive_prompt":'宫廷肖像，招牌“春天”',"negative_prompt":"不要眼镜","model_profile":MODEL,"settings":{"seed":"42"}},
          "creationConfiguration":{"modelProfile":MODEL,"workflow":{"id":workflow["workflow_id"],"revision":workflow["revision"]}},
          "executionPolicy":{"mode":"pinned","environmentId":"server"}}
    try:
        record=service.store.create("moss-raw",body)
        result=service.resolve(record["id"])
        assert result["state"] == "accepted",result
        entry=submissions.store.list()[0]
        snapshot=entry["snapshot"]
        assert snapshot["job"]["positive_prompt"] == body["source"]["positive_prompt"]
        assert snapshot["job"]["negative_prompt"] == "不要眼镜"
        assert snapshot["job"]["generation_params"]["cfg"] == 2.5
        assert snapshot["workflow"]["api_workflow"]["6"]["class_type"] == "EmptyFlux2LatentImage"
        assert snapshot["job"]["generation_params"]["width"] == 1024
        assert service.resolve(record["id"])["run_id"] == result["run_id"]
        assert len(submissions.store.list()) == 1
    finally:
        service.close();submissions.close();queue.shutdown()


@pytest.mark.parametrize("bad_field,bad_value", [("checkpoint","anima-base.safetensors"),("text_encoder","qwen_3_06b_base.safetensors"),("vae","qwen_image_vae.safetensors")])
def test_cloud_catalog_moss_mapping_checks_assets(tmp_path,bad_field,bad_value):
    from anima_prompt_studio_v3.runtime.cloud_model_catalog import CloudModelCatalog
    from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
    from anima_prompt_studio_v3.remote.cloud_model_catalog import parse_catalog
    w=next(w for w in packaged_workflow_profiles() if w.id == "v3_moss_image_sft_int8")
    fields={"checkpoint":("diffusion_models","unet_name"),"text_encoder":("text_encoders","clip_name"),"vae":("vae","vae_name")}
    assets={key:category+"/"+w.runtime_assets[key] for key,(category,_) in fields.items()}
    info={}
    for node in w.api_workflow.values():
        specs=info.setdefault(node["class_type"],{"input":{"required":{}}})["input"]["required"]
        for name,value in node["inputs"].items():
            if isinstance(value,str): specs[name]=[[value]]
    def items():
        raw=parse_catalog(json.dumps({"protocol_version":1,"models":[dict(id=MODEL,display_name="MOSS",family="moss",ready=True,assets=list(assets.values()),**assets)]}).encode())["models"]
        repo=SQLiteRepository(tmp_path/"runtime.db")
        try:return CloudModelCatalog(tmp_path/"runtime.db")._items(repo,raw,info)[0]
        finally:repo.close()
    assert items()["supported"]
    assert not items()["workflow_mappings"][0]["errors"]
    category,input_name=fields[bad_field]
    assets[bad_field]=category+"/"+bad_value
    for definition in info.values():
        if input_name in definition["input"]["required"]:definition["input"]["required"][input_name]=[[bad_value]]
    assert items()["workflow_mappings"][0]["errors"]


def test_moss_assist_rejects_forced_english(monkeypatch):
    moss=importlib.import_module("anima_prompt_studio_v3.api.moss")
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    async def complete(**kwargs):return {"text":json.dumps(dict(positive="a girl",negative="",changes=[],warnings=[]))}
    monkeypatch.setattr(LLMService,"complete",complete)
    with pytest.raises(RuntimeError):
        asyncio.run(moss.assist_prompt(moss.MossPromptAssistRequest(source_text="一位少女",mode="polish")))


@pytest.mark.parametrize("name", ["LocalNaturalCandidateRequest", "WorkbenchCandidateRequest", "IntentCandidateRequest"])
def test_moss_candidate_requests_reject_before_translation_or_tag_work(name):
    from anima_prompt_studio_v3.api import models
    from pydantic import ValidationError
    request=getattr(models,name)
    data={"model_profile":MODEL}
    if name == "IntentCandidateRequest":
        data["intent"]={"source_text":"少女","source_language":"zh","graph":{"elements":[],"edges":[]}}
    else:
        data["source_text"]="少女"
        if name == "WorkbenchCandidateRequest":data["elements"]=[{"id":"e_subject","text":"少女"}]
    with pytest.raises(ValidationError,match="MOSS"):
        request.model_validate(data)


def test_moss_compiler_rechecks_dimensions_on_recovered_job():
    w=next(w for w in packaged_workflow_profiles() if w.id == "v3_moss_image_sft_int8")
    prepared=CandidateToPromptJobAdapter().prepare_direct(positive_prompt="中文",model_profile_id=MODEL)
    prepared.job.generation_params.width=1032
    with pytest.raises(ValueError,match="16"):
        V3WorkflowCompiler().render(prepared.job,w,RemoteProfile(id="test",display_name="test",ssh_host="localhost",ssh_user="test"),MODEL,"test")


@pytest.mark.parametrize("field,stale", [
    ("text_encoder", "qwen_3_06b_base.safetensors"),
    ("text_encoder_type", "stable_diffusion"),
    ("vae", "qwen_image_vae.safetensors"),
    ("checkpoint", "anima-base.safetensors"),
])
@pytest.mark.parametrize("entrypoint", ["renderer", "import", "catalog"])
def test_moss_rejects_stale_runtime_assets_at_effective_boundaries(tmp_path, field, stale, entrypoint):
    from anima_prompt_studio_v3.runtime.workflow_catalog import WorkflowCatalog
    from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
    from test_workflow_catalog import capabilities
    w=next(w for w in packaged_workflow_profiles() if w.id == "v3_moss_image_sft_int8")
    w.runtime_assets[field]=stale
    if entrypoint == "renderer":
        job=CandidateToPromptJobAdapter().prepare_direct(positive_prompt="中文原文",model_profile_id=MODEL).job
        remote=RemoteProfile(id="server",display_name="test",ssh_host="localhost",ssh_user="test")
        with pytest.raises(ValueError, match="不支持"):
            V3WorkflowCompiler().render(job,w,remote,MODEL,"test")
    elif entrypoint == "import":
        with pytest.raises(ValueError, match="兼容模型"):
            WorkflowCatalog(tmp_path/"runtime.db").import_profile(w.model_dump(mode="json"))
    else:
        # A recovered user profile bypasses import; catalog must still deny it,
        # including with the empty server mapping that previously kept overrides.
        manager=WorkflowCatalog(tmp_path/"runtime.db")
        w=w.model_copy(update={"id":"user:stale-runtime"})
        repo=SQLiteRepository(manager.database)
        repo.save_workflow_profile(w)
        repo.save_remote_profile(RemoteProfile(id="server",display_name="test",ssh_host="localhost",ssh_user="test",known_host_fingerprint="SHA256:test"))
        repo.close()
        capabilities(manager,"server")
        item=next(item for item in manager.report("server")["items"] if item["workflow_id"] == w.id)
        assert item["state"] == "invalid_inputs", item
        assert item["model_profiles"] == []
