from __future__ import annotations

import copy
import json
import re
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


@dataclass(frozen=True)
class ParsedSSHCommand:
    host: str
    port: int = 22
    user: str = "root"


def parse_ssh_command(command: str) -> ParsedSSHCommand:
    """Parse the login command copied from a cloud provider console."""
    normalized = command.strip().replace("\r", " ").replace("\n", " ")
    if not normalized:
        raise ValueError("请先从云平台复制 SSH 登录指令。")
    try:
        parts = shlex.split(normalized, posix=True)
    except ValueError as exc:
        raise ValueError("SSH 登录指令格式不完整。") from exc
    if not parts or PurePosixPath(parts[0]).name.casefold() not in {"ssh", "ssh.exe"}:
        raise ValueError("这不是 SSH 登录指令，应类似：ssh -p 23 root@1.2.3.4")

    port = 22
    destination = ""
    index = 1
    while index < len(parts):
        token = parts[index]
        if token in {"-p", "-l"}:
            if index + 1 >= len(parts):
                raise ValueError(f"SSH 参数 {token} 缺少值。")
            if token == "-p":
                try:
                    port = int(parts[index + 1])
                except ValueError as exc:
                    raise ValueError("SSH 端口不是有效数字。") from exc
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        destination = token
        index += 1

    if not destination:
        raise ValueError("SSH 登录指令中没有找到主机地址。")
    if "@" in destination:
        user, host = destination.rsplit("@", 1)
    else:
        user, host = "root", destination
    host = host.strip().strip("[]")
    if not user.strip() or not host:
        raise ValueError("SSH 用户名或主机地址为空。")
    if not 1 <= port <= 65535:
        raise ValueError("SSH 端口必须在 1 到 65535 之间。")
    return ParsedSSHCommand(host=host, port=port, user=user.strip())


def frontend_workflow_to_api(document: dict[str, Any]) -> dict[str, Any]:
    """Convert a ComfyUI frontend graph to the API prompt shape.

    Modern ComfyUI workflow files include input names and widget metadata, so a
    basic workflow can be converted without running the browser frontend.
    """
    nodes = document.get("nodes")
    links = document.get("links", [])
    if not isinstance(nodes, list):
        raise ValueError("不是 ComfyUI 前端工作流。")

    link_map: dict[int, list[Any]] = {}
    for link in links:
        if isinstance(link, list) and len(link) >= 5:
            link_map[int(link[0])] = [str(link[1]), int(link[2])]

    prompt: dict[str, Any] = {}
    for raw_node in nodes:
        if not isinstance(raw_node, dict) or raw_node.get("mode", 0) not in {0, None}:
            continue
        node_id = str(raw_node.get("id", ""))
        class_type = str(raw_node.get("type", ""))
        if not node_id or not class_type:
            continue
        widget_values = list(raw_node.get("widgets_values") or [])
        widget_index = 0
        api_inputs: dict[str, Any] = {}
        for input_info in raw_node.get("inputs") or []:
            if not isinstance(input_info, dict) or not input_info.get("name"):
                continue
            name = str(input_info["name"])
            link_id = input_info.get("link")
            if link_id is not None and int(link_id) in link_map:
                api_inputs[name] = link_map[int(link_id)]
                # Linked widgets still retain their old value in widgets_values.
                if input_info.get("widget") and widget_index < len(widget_values):
                    widget_index += 1
                continue
            if input_info.get("widget") and widget_index < len(widget_values):
                api_inputs[name] = widget_values[widget_index]
                widget_index += 1
                # Seed widgets serialize an additional control-after-generate value.
                if (
                    name in {"seed", "noise_seed"}
                    and widget_index < len(widget_values)
                    and str(widget_values[widget_index]).casefold()
                    in {"fixed", "increment", "decrement", "randomize"}
                ):
                    widget_index += 1
        prompt[node_id] = {
            "class_type": class_type,
            "inputs": api_inputs,
            "_meta": {"title": str(raw_node.get("title") or class_type)},
        }
    if not prompt:
        raise ValueError("工作流中没有可执行节点。")
    return prompt


def discover_compshare_workflows(tunnel, max_files: int = 40) -> list[tuple[str, str, dict[str, Any]]]:
    """Read the numbered workflow collection supplied by a Compshare image."""
    if tunnel.client is None:
        return []
    roots = (
        "/workspace/ComfyUI/user/default/workflows",
        "/workspace/proxy/ComfyUI/user/default/workflows",
    )
    numbered_workflow = re.compile(r"^(?:0[1-9]|1[0-9]|20)_.*\.json$", re.IGNORECASE)
    sftp = tunnel.client.open_sftp()
    try:
        for root in roots:
            try:
                names = sorted(sftp.listdir(root))
            except OSError:
                continue
            selected = [name for name in names if numbered_workflow.search(name)][:max_files]
            results: list[tuple[str, str, dict[str, Any]]] = []
            for name in selected:
                remote_path = f"{root}/{name}"
                try:
                    with sftp.open(remote_path, "r") as stream:
                        payload = json.loads(stream.read().decode("utf-8"))
                    api_workflow = (
                        payload["prompt"]
                        if isinstance(payload, dict) and isinstance(payload.get("prompt"), dict)
                        else frontend_workflow_to_api(payload)
                    )
                    results.append((name.removesuffix(".json"), remote_path, api_workflow))
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                    continue
            _append_derived_workflows(sftp, results)
            return results
    finally:
        sftp.close()
    return []


def _append_derived_workflows(
    sftp,
    workflows: list[tuple[str, str, dict[str, Any]]],
) -> None:
    """Derive isolated model baselines from the known-good Base graph.

    These graphs are validation baselines.  They deliberately do not inherit
    the old Turbo LoRA or optimization nodes from workflow 02.
    """
    try:
        model_names = set(sftp.listdir("/workspace/ComfyUI/models/diffusion_models"))
    except OSError:
        return
    try:
        text_encoder_names = set(sftp.listdir("/workspace/ComfyUI/models/text_encoders"))
    except OSError:
        text_encoder_names = set()
    try:
        vae_names = set(sftp.listdir("/workspace/ComfyUI/models/vae"))
    except OSError:
        vae_names = set()
    base = next((item for item in workflows if item[0].startswith("01_")), None)
    if base is None:
        return
    versions = (
        ("21_美学文生图_Aesthetic_v1.0", "anima-aesthetic-v1.0.safetensors", None, None, None),
        ("22_美学文生图_Aesthetic_v1.1", "anima-aesthetic-v1.1.safetensors", None, None, None),
        (
            "23_Turbo_v1.1_验证基线",
            "anima-turbo-v1.1.safetensors",
            "qwen_3_06b_base.safetensors",
            (10, 1.0, "er_sde", "simple"),
            3.0,
        ),
        (
            "24_AnimaYume_v1.0_Final_验证基线",
            "animayume_v10BaseFinal.safetensors",
            "qwen_3_06b_base.safetensors",
            (30, 5.5, "euler_ancestral", "normal"),
            3.0,
        ),
        (
            "25_MiaoMiao_Harem_ANIMA_v1.6_验证基线",
            "miaomiaoHarem_anima16.safetensors",
            "miaomiaoHarem_anima16_txt.safetensors",
            (30, 4.5, "euler", "normal"),
            3.0,
        ),
    )
    for display_name, model_name, text_encoder_name, sampling, shift in versions:
        if model_name not in model_names:
            continue
        if text_encoder_name and text_encoder_name not in text_encoder_names:
            continue
        if text_encoder_name and "qwen_image_vae.safetensors" not in vae_names:
            continue
        workflow = copy.deepcopy(base[2])
        changed = _set_first_node_input(workflow, "unetloader", "unet_name", model_name)
        if text_encoder_name:
            changed = _set_first_node_input(workflow, "cliploader", "clip_name", text_encoder_name) and changed
            changed = _set_first_node_input(workflow, "vaeloader", "vae_name", "qwen_image_vae.safetensors") and changed
        if sampling:
            for input_name, value in zip(
                ("steps", "cfg", "sampler_name", "scheduler"),
                sampling,
                strict=True,
            ):
                changed = _set_first_node_input(workflow, "ksampler", input_name, value) and changed
        if shift is not None:
            changed = _set_first_node_input(workflow, "modelsamplingaura", "shift", shift) and changed
        if changed:
            workflows.append(
                (
                    display_name,
                    f"derived://compshare/{base[0]}#{model_name}",
                    workflow,
                )
            )
    _append_community_optimization_experiments(workflows)


def _append_community_optimization_experiments(
    workflows: list[tuple[str, str, dict[str, Any]]],
) -> None:
    """Add opt-in A/B graphs using the community NAG + Replay chain.

    Baselines 23-25 remain the preferred workflows.  The old Turbo LoRA is
    intentionally excluded because it targets a different model recipe.
    """
    experiments = (
        ("23_", "26_Turbo_v1.1_社区优化实验", "anima-turbo-v1.1"),
        ("24_", "27_AnimaYume_社区优化实验", "animayume-v1.0-final"),
        ("25_", "28_MiaoMiao_社区优化实验", "miaomiao-harem-anima-v1.6"),
    )
    for source_prefix, display_name, slug in experiments:
        source = next((item for item in workflows if item[0].startswith(source_prefix)), None)
        if source is None:
            continue
        workflow = copy.deepcopy(source[2])
        sampler = next(
            (
                str(node_id)
                for node_id, node in workflow.items()
                if isinstance(node, dict) and str(node.get("class_type", "")) == "KSampler"
            ),
            "",
        )
        if not sampler:
            continue
        original_model = workflow[sampler].get("inputs", {}).get("model")
        if not isinstance(original_model, (list, tuple)):
            continue
        workflow["901"] = {
            "class_type": "AnimaNormalizedAttentionGuidance",
            "inputs": {
                "model": list(original_model),
                "scale": 2,
                "tau": 2.5,
                "alpha": 0.5,
                "start_percent": 0,
                "end_percent": 0.5,
                "only_anima": True,
                "optimize_outside_range": True,
            },
            "_meta": {"title": "Community NAG A/B"},
        }
        workflow["902"] = {
            "class_type": "AnimaLayerReplayPatcher",
            "inputs": {
                "model": ["901", 0],
                "enable_replay": True,
                "block_indices": "3,4,5",
                "denoise_start_pct": 0.5,
                "denoise_end_pct": 1,
                "enable_spectrum": False,
                "spectrum_w": 0.2,
                "spectrum_m": 16,
                "spectrum_lam": 0.5,
                "spectrum_warmup_steps": 6,
                "spectrum_window_size": 2,
                "spectrum_flex_window": 0,
            },
            "_meta": {"title": "Community Layer Replay A/B"},
        }
        workflow[sampler]["inputs"]["model"] = ["902", 0]
        workflows.append(
            (
                display_name,
                f"derived://compshare/{source[0]}#{slug}-nag-replay-experiment",
                workflow,
            )
        )


def _set_first_node_input(
    workflow: dict[str, Any],
    class_name_fragment: str,
    input_name: str,
    value: Any,
) -> bool:
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        if class_name_fragment.casefold() not in str(node.get("class_type", "")).casefold():
            continue
        inputs = node.get("inputs", {})
        if input_name in inputs:
            inputs[input_name] = value
            return True
    return False
