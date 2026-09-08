"""Conservative conversion of a single-sampler ComfyUI API graph."""
from anima_prompt_studio.domain.execution_models import WorkflowProfile, WorkflowBinding, LoRASlotBinding
from anima_prompt_studio_v3.runtime.workflow_compatibility import infer_workflow_model_profiles


def profile_from_api(document):
    graph = document.get("prompt", document)
    if not isinstance(graph, dict) or not graph or len(graph) > 2000:
        raise ValueError("请选择 ComfyUI API 格式 JSON；编辑器格式需要先导出为 API 格式。")
    if any(not isinstance(node, dict) or not isinstance(node.get("inputs"), dict)
           or not isinstance(node.get("class_type"), str) for node in graph.values()):
        raise ValueError("API 工作流节点须声明 class_type 和 inputs。")

    def single(class_type, required=True):
        matches = [(str(k), n) for k, n in graph.items() if isinstance(n, dict) and n.get("class_type") == class_type]
        if len(matches) > 1 or required and not matches:
            raise ValueError(f"不能唯一识别 {class_type}；请使用含明确 bindings 的工作流配置格式。")
        return matches[0] if matches else None

    bindings = {}
    def bind(field, node, input_name):
        if node and input_name in node[1].get("inputs", {}):
            bindings[field] = WorkflowBinding(node_id=node[0], input_name=input_name)

    sampler = single("KSampler")
    for field, name in {"seed": "seed", "steps": "steps", "cfg": "cfg", "sampler": "sampler_name", "scheduler": "scheduler"}.items():
        bind(field, sampler, name)
    for field, name in (("positive_prompt", "positive"), ("negative_prompt", "negative")):
        link = sampler[1].get("inputs", {}).get(name)
        if not isinstance(link, list) or len(link) != 2 or link[0] not in graph or graph[link[0]].get("class_type") != "CLIPTextEncode":
            raise ValueError("提示词链不是直接 CLIPTextEncode，请提供明确的 bindings。")
        bind(field, (link[0], graph[link[0]]), "text")
    unet = single("UNETLoader", False)
    checkpoint = single("CheckpointLoaderSimple", False)
    if bool(unet) == bool(checkpoint):
        raise ValueError("不能唯一识别模型加载器，请提供明确的 bindings。")
    loader = unet or checkpoint
    bind("checkpoint", loader, "unet_name" if loader[1]["class_type"] == "UNETLoader" else "ckpt_name")
    latent = single("EmptyLatentImage")
    for field in ("width", "height", "batch_size"):
        bind(field, latent, field)
    bind("filename_prefix", single("SaveImage"), "filename_prefix")
    encoder = single("CLIPLoader", False)
    bind("text_encoder", encoder, "clip_name")
    bind("text_encoder_type", encoder, "type")
    bind("vae", single("VAELoader", False), "vae_name")
    bind("model_shift", single("ModelSamplingAuraFlow", False), "shift")
    assets = {key: graph[b.node_id]["inputs"][b.input_name] for key, b in bindings.items()
              if key in {"checkpoint", "text_encoder", "text_encoder_type", "vae", "model_shift"}}
    loras = [LoRASlotBinding(node_id=str(k)) for k, n in graph.items() if isinstance(n, dict) and n.get("class_type") == "LoraLoader"]
    return WorkflowProfile(id="import-preview", display_name="导入的 API 工作流", api_workflow=graph,
                           bindings=bindings, runtime_assets=assets, lora_slots=loras, workflow_kind="txt2img_basic",
                           compatible_model_profiles=infer_workflow_model_profiles(graph, "user-import"))
