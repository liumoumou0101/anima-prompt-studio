"""Single-run reads retain the same accepted provenance as workspace history."""

from fastapi.testclient import TestClient

from anima_prompt_studio_v3.api import create_api_runtime
from test_api import reference_db
from test_generation_submissions import harness, workspace_payload


def test_single_run_retains_accepted_source_outside_recent_workspace_page(harness, reference_db):
    store, start, _, executed, _, _ = harness
    queue, _ = start()
    workspace, request = workspace_payload(store)
    runtime = create_api_runtime(reference_db, workspace_db=store.path, generation_queue=queue)
    runtime.app.state.submission_service.close()
    with TestClient(runtime.app, base_url="http://127.0.0.1") as client:
        client.headers["Origin"] = "http://127.0.0.1"
        exchange = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token})
        client.headers["X-Anima-Session"] = exchange.json()["session_token"]
        data = request.model_dump(exclude_unset=True)
        data.update(positive_prompt="woman, blue coat", negative_prompt="blurry")
        data["settings"] = {"seed": "8798399215689017476", "width": 896, "height": 1152,
                            "steps": 31, "cfg": 5.5, "sampler": "euler", "scheduler": "normal"}
        first = client.post("/api/v3/direct-prompt/runs", json=data, headers={"Idempotency-Key": "old-blue"})
        assert first.status_code == 202, first.text
        accepted = first.json()
        data.update(workspace_revision=accepted["workspace_revision"], compiled_token=accepted["compiled_token"],
                    positive_prompt="woman, red coat")
        data["settings"]["seed"] = 42
        newer = client.post("/api/v3/direct-prompt/runs", json=data, headers={"Idempotency-Key": "new-red"})
        assert newer.status_code == 202, newer.text
        recent = client.get(f"/api/v3/workspaces/{workspace['id']}/runs", params={"limit": 1}).json()
        assert [item["id"] for item in recent["items"]] == [newer.json()["id"]]

        response = client.get(f"/api/v3/generation-runs/{accepted['id']}")
        assert response.status_code == 200, response.text
        source = response.json().get("source")
        assert source is not None, "Single-run restore must carry the accepted submission snapshot"
        assert source["workspace_revision"] == accepted["workspace_revision"]
        assert source["workspace_revision"] < newer.json()["workspace_revision"]
        assert source["positive_prompt"] == "woman, blue coat"
        assert source["negative_prompt"] == "blurry"
        assert source["model_profile"] == "anima_base_v1"
        assert {field: source["settings"][field] for field in (
            "seed", "width", "height", "steps", "cfg", "sampler", "scheduler")
        } == {"seed": "8798399215689017476", "width": 896, "height": 1152,
              "steps": 31, "cfg": 5.5, "sampler": "euler", "scheduler": "normal"}
        assert set(source) == {"workspace_revision", "positive_prompt", "negative_prompt", "model_profile", "settings"}
        older_page = client.get(f"/api/v3/workspaces/{workspace['id']}/runs", params={"limit": 1, "offset": 1}).json()
        assert source == older_page["items"][0]["source"]
        assert not executed


def test_single_run_without_submission_service_keeps_unknown_source(harness, reference_db):
    store, start, _, executed, _, _ = harness
    queue, _ = start()
    _, request = workspace_payload(store)
    runtime = create_api_runtime(reference_db, workspace_db=store.path, generation_queue=queue)
    runtime.app.state.submission_service.close()
    with TestClient(runtime.app, base_url="http://127.0.0.1") as client:
        client.headers["Origin"] = "http://127.0.0.1"
        exchange = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token})
        client.headers["X-Anima-Session"] = exchange.json()["session_token"]
        submitted = client.post("/api/v3/direct-prompt/runs", json=request.model_dump(exclude_unset=True),
                                headers={"Idempotency-Key": "legacy"})
        assert submitted.status_code == 202, submitted.text
        runtime.app.state.submission_service = None
        response = client.get(f"/api/v3/generation-runs/{submitted.json()['id']}")
        assert response.status_code == 200, response.text
        assert response.json()["source"] is None
        assert client.get("/api/v3/generation-runs/missing").status_code == 404
        assert not executed


def frozen_parameter_snapshot():
    from copy import deepcopy
    values = {"width":896,"height":1152,"steps":31,"cfg":5.5,"sampler":"euler","scheduler":"normal",
              "seed":"8798399215689017476","batch_size":1,"refiner_steps":24,"refiner_cfg":3.2,
              "refiner_sampler":"euler","refiner_scheduler":"normal","refiner_denoise":.45,"upscale_factor":2}
    schema = {"version":1,"workflowId":"wf1","templateRevision":"old-template-revision","fields":[
        {"key":key,"label":key,"type":"seed" if key=="seed" else "string" if isinstance(value,str) else "number",
         "default":"-1" if key=="seed" else 18 if key=="refiner_steps" else value,"group":"workflow"}
        for key,value in values.items()]}
    params={key:value for key,value in values.items() if not key.startswith("refiner_") and key!="upscale_factor"}
    params.update(seed=8798399215689017476,denoise=.9,clip_skip=2)
    return {"workspace_revision":12,"job":{"model_profile_id":"anima_base_v1","positive_prompt":"old prompt","negative_prompt":"text",
        "generation_params":deepcopy(params),"integration_metadata":{"workflow_parameters":{"schema":schema,"values":values,"overrides":{"seed":"-1","refiner_steps":24}}}},
        "provenance":{"positive":"old prompt","negative":"text","model_profile":"anima_base_v1","requirements":None,"settings":params},
        "run":{"remote_profile_id":"remote1","workflow_profile_id":"wf1"},"workflow":{"id":"wf1"},"resources":[]}


def test_source_keeps_frozen_workflow_schema_values_and_actual_seed():
    from anima_prompt_studio_v3.api.app import _workspace_run_source
    snapshot=frozen_parameter_snapshot()
    settings=_workspace_run_source(snapshot)["settings"]
    frozen=snapshot["job"]["integration_metadata"]["workflow_parameters"]
    assert settings["parameter_schema"]==frozen["schema"]
    assert settings["workflow_parameter_overrides"]==frozen["values"]
    assert settings["seed"]=="8798399215689017476"
    assert settings["denoise"]==.9 and settings["clip_skip"]==2
    config=settings["creation_configuration"]
    assert config["workflow"]=={"id":"wf1","revision":"old-template-revision"}
    assert config["seedMode"]=="fixed"
    assert config["parameterOverrides"]["refiner_steps"]==24
    assert config["parameterOverrides"]["seed"]=="8798399215689017476"
    settings["parameter_schema"]["fields"][0]["default"]=123
    assert frozen["schema"]["fields"][0]["default"]==896


def test_source_restores_declared_parameters_from_existing_direct_job_metadata():
    from anima_prompt_studio_v3.api.app import _workspace_run_source
    snapshot=frozen_parameter_snapshot()
    frozen=snapshot["job"]["integration_metadata"]["workflow_parameters"]
    snapshot["job"]["integration_metadata"]={"parameter_schema":frozen["schema"],
        "workflow_parameter_overrides":{**frozen["values"],"seed":"-1"}}
    settings=_workspace_run_source(snapshot)["settings"]
    assert settings["workflow_parameter_overrides"]["refiner_steps"]==24
    assert settings["workflow_parameter_overrides"]["seed"]=="8798399215689017476"
    assert settings["parameter_schema"]==frozen["schema"]


def test_older_random_job_uses_the_actual_seed_recorded_in_its_run():
    from anima_prompt_studio_v3.api.app import _workspace_run_source
    snapshot=frozen_parameter_snapshot()
    snapshot["job"]["generation_params"]["seed"]=-1
    snapshot["run"]["request_json"]={"resolved_seed":9223372036854775807}
    settings=_workspace_run_source(snapshot)["settings"]
    assert settings["seed"]=="9223372036854775807"
    assert settings["creation_configuration"]["parameterOverrides"]["seed"]==settings["seed"]


def test_direct_request_keeps_reviewed_text_through_schema_and_job_for_both_families():
    from anima_prompt_studio_v3.api.models import DirectPromptSubmitRequest
    from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter
    positive, negative = "  第一段\n\n  第二段  ", " 变形\n"
    for model in ["moss_image_sft_int8","anima_base_v1"]:
        payload=DirectPromptSubmitRequest(model_profile=model,positive_prompt=positive,negative_prompt=negative,
            remote_profile_id="source-cloud",workflow_profile_id="example")
        job=CandidateToPromptJobAdapter().prepare_direct(model_profile_id=model, positive_prompt=payload.positive_prompt,
            negative_prompt=payload.negative_prompt).job
        assert (job.positive_prompt,job.negative_prompt) == (positive,negative)


def test_http_moss_source_workspace_submits_exact_frozen_controls_to_the_queue(harness, reference_db):
    from anima_prompt_studio.domain.execution_models import GenerationRun
    from anima_prompt_studio_v3.runtime.packaged_workflows import packaged_workflow_profiles
    from anima_prompt_studio_v3.core.workflow_parameters import BASE_FIELDS, build_workflow_parameter_schema
    from anima_prompt_studio_v3.api.generation_intents import install_generation_intents
    from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter
    from test_generation_intents import fake_candidates, fake_probe
    store,start,saved,executed,_,_=harness
    queue,submissions=start()
    model,workflow="moss_image_sft_int8","v3_moss_image_sft_int8"
    profile=next(item for item in packaged_workflow_profiles() if item.id==workflow)
    frozen=profile.model_dump(mode="json")
    schema=build_workflow_parameter_schema(profile)
    params={field["key"]:field["default"] for field in schema["fields"] if field["key"] in BASE_FIELDS}
    params.update(width=1024,height=1024,steps=27,cfg=2.75,seed=9223372036854775807,batch_size=1)
    positive,negative="  原始中文第一段\n\n第二段。  "," 模糊\n"
    job={"model_profile_id":model,"positive_prompt":positive,"negative_prompt":negative,"generation_params":params}
    origin=GenerationRun(id="run-moss-source",prompt_job_id="original-job",remote_profile_id="remote-1",workflow_profile_id=workflow,
        request_json={"workflow_snapshot":frozen,"prompt_job":job})
    saved[origin.id]=origin
    lora={"logical_id":"paint","file_name":"paint.safetensors","weight":0.7}
    submissions.store.accept(submission_id="seed-source",key="seed-source",payload_hash="original",run_id=origin.id,
        snapshot={"job":job,"run":origin.model_dump(mode="json"),"workflow":frozen,"resources":[lora],
            "provenance":{"positive":positive,"negative":negative,"model_profile":model,"settings":{"seed":-1}}},response={"id":origin.id})
    runtime=create_api_runtime(reference_db,workspace_db=store.path,generation_queue=queue)
    runtime.app.state.submission_service.close()
    intents=install_generation_intents(runtime.app,store,runtime.app.state.submission_service,CandidateToPromptJobAdapter(),None,lambda:None)
    intents.probe.close();intents.probe=fake_probe;intents.candidates_override=fake_candidates
    with TestClient(runtime.app,base_url="http://127.0.0.1") as client:
        client.headers["Origin"]="http://127.0.0.1"
        exchange=client.post("/api/v3/session/exchange",json={"bootstrap_token":runtime.bootstrap_token})
        client.headers["X-Anima-Session"]=exchange.json()["session_token"]
        continued=client.post(f"/api/v3/generation-runs/{origin.id}/workspace",json={})
        assert continued.status_code==201,continued.text
        workspace=continued.json();draft=workspace["draft"];settings=draft["generation_settings"]
        values={key:settings[key] for key in (*BASE_FIELDS,"preset_id","parameter_schema","workflow_parameter_overrides")}
        source={"submission_kind":"conversational","use_current_prompt":True,"workspace_id":workspace["id"],
            "workspace_revision":workspace["revision"],"compiled_token":draft["compiled"]["compiled_token"],
            "positive_prompt":draft["compiled"]["positive"],"negative_prompt":draft["compiled"]["negative"],
            "model_profile":model,"workflow_snapshot_run_id":origin.id,"settings":values}
        request={"source":source,"creationConfiguration":settings["creation_configuration"],
            "executionPolicy":{"mode":"pinned","environmentId":"remote-1"}}
        accepted=client.post("/api/v3/generation-intents",json=request,headers={"Idempotency-Key":"continue-moss"})
        assert accepted.status_code==202,accepted.text
        intent_id=accepted.json()["id"];intents.jobs[intent_id].result(timeout=5)
        receipt=client.get(f"/api/v3/generation-intents/{intent_id}").json()
        assert receipt["state"]=="accepted",receipt
        snapshot=submissions.store.for_runs([receipt["run_id"]])[0]["snapshot"]
        assert snapshot["workflow"]==frozen
        assert snapshot["job"]["model_profile_id"]==model
        assert (snapshot["job"]["positive_prompt"],snapshot["job"]["negative_prompt"])==(positive,negative)
        assert snapshot["job"]["integration_metadata"]["parameter_schema"]==schema
        assert all(snapshot["job"]["generation_params"][key]==value for key,value in params.items())
        assert snapshot["resources"][0]["logical_id"]=="paint"
        assert not executed
