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
            _append_aesthetic_workflows(sftp, results)
            return results
    finally:
        sftp.close()
    return []


def _append_aesthetic_workflows(
    sftp,
    workflows: list[tuple[str, str, dict[str, Any]]],
) -> None:
    """Derive simple Aesthetic workflows from the known-good Base graph."""
    try:
        model_names = set(sftp.listdir("/workspace/ComfyUI/models/diffusion_models"))
    except OSError:
        return
    base = next((item for item in workflows if item[0].startswith("01_")), None)
    if base is None:
        return
    versions = (
        ("21_美学文生图_Aesthetic_v1.0", "anima-aesthetic-v1.0.safetensors"),
        ("22_美学文生图_Aesthetic_v1.1", "anima-aesthetic-v1.1.safetensors"),
    )
    for display_name, model_name in versions:
        if model_name not in model_names:
            continue
        workflow = copy.deepcopy(base[2])
        changed = False
        for node in workflow.values():
            if not isinstance(node, dict) or "unetloader" not in str(node.get("class_type", "")).casefold():
                continue
            inputs = node.get("inputs", {})
            if "unet_name" in inputs:
                inputs["unet_name"] = model_name
                changed = True
                break
        if changed:
            workflows.append(
                (
                    display_name,
                    f"derived://compshare/{base[0]}#{model_name}",
                    workflow,
                )
            )
