"""Gallery enlargement talks to the current Comfy runtime without a generation template."""
from io import BytesIO
import json
import time

from PIL import Image
import pytest

from anima_prompt_studio.domain.execution_models import WorkflowProfile
from anima_prompt_studio_v3.adapters.v2.gallery import build_v2_gallery_service
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_http_comfy_runtime import http_profile, protocol
from test_v2_gallery_adapter import make_gallery


def png(width, height):
    stream = BytesIO()
    Image.new("RGB", (width, height), (50, 100, 180)).save(stream, format="PNG")
    return stream.getvalue()


@pytest.mark.parametrize("template, spec, model, missing, error", [
    (None, [["z.pth", "a.pth"]], "a.pth", None, None),
    ("z.pth", ["COMBO", {"options": ["a.pth", "z.pth"]}], "z.pth", None, None),
    ("removed.pth", [["other.pth"]], "other.pth", None, None),
    (None, [[]], None, None, "upscale_models"),
    (None, [["a.pth"]], None, "ImageUpscaleWithModel", "ImageUpscaleWithModel"),
])
def test_gallery_uses_live_super_resolution_assets_and_registers_result(
    tmp_path, protocol, template, spec, model, missing, error,
):
    database, root, image = make_gallery(tmp_path)
    source = png(174, 92)
    image.write_bytes(source)
    repo = SQLiteRepository(database)
    repo.set_setting("generation_output_root", str(root))
    repo.save_remote_profile(http_profile())
    if template:
        repo.save_workflow_profile(WorkflowProfile(id="my-upscaler", display_name="自己的超分", bindings={},
            api_workflow={"1": {"class_type": "LoadImage", "inputs": {"image": "unused.png"}},
                          "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": template}},
                          "3": {"class_type": "ImageUpscaleWithModel", "inputs": {}},
                          "4": {"class_type": "SaveImage", "inputs": {}}}))
    repo.close()
    calls, state, credentials = protocol
    info = {name: {} for name in ("LoadImage", "ImageScale", "ImageUpscaleWithModel", "SaveImage")}
    info["LoadImage"] = {"input": {"required": {"image": [["unrelated.png"]]}}}
    info["UpscaleModelLoader"] = {"input": {"required": {"model_name": spec}}}
    info.pop(missing, None)
    state.update(object_info=info, view_data=png(261, 138))
    service = build_v2_gallery_service(database, credential_store=credentials)
    try:
        cfg = service.process_configuration()
        assert cfg["available"], cfg["reason"]
        submitted = service.submit_process([image.relative_to(root).as_posix()], "upscale")
        assert not submitted["failed"], submitted["failed"]
        job_id = submitted["jobs"][0]["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = service.process_manager.get(job_id)
            if job["state"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert image.read_bytes() == source
        if error:
            assert job["state"] == "failed" and error in (job["error"] or job["message"])
            assert "uploaded_body" not in state and "submitted_graph" not in state
            return
        assert job["state"] == "completed", job["error"]
        graph = {n["class_type"]: n["inputs"] for n in state["submitted_graph"].values()}
        assert len(graph) == 5
        assert graph["UpscaleModelLoader"]["model_name"] == model
        assert graph["ImageScale"]["width"] == 261 and graph["ImageScale"]["height"] == 138
        assert graph["LoadImage"]["image"].startswith("anima_gallery/") and source in state["uploaded_body"]
        output = root / job["resultPath"]
        assert output != image and output.read_bytes() == state["view_data"]
        manifest = json.loads((output.parent / "manifest.json").read_text(encoding="utf-8"))
        metadata = manifest["generation_run"]["request_json"]["render_metadata"]
        assert metadata["upscale_model"] == model and not metadata["diffusion_redraw"]
        assert any(item["path"] == job["resultPath"] for item in service.list_assets(refresh=True)["items"])
    finally:
        service.shutdown()
