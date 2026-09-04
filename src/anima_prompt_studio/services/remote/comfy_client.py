from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from anima_prompt_studio.domain.execution_models import EnvironmentReport, RemoteArtifact


class ComfyAPIError(RuntimeError):
    def __init__(self, message: str, *, code: str = "comfy_api_error", details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class ComfyUIClient:
    MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
    MAX_UPLOAD_BYTES = 100 * 1024 * 1024

    def __init__(
        self,
        base_url: str,
        session=None,
        timeout: tuple[float, float] = (10.0, 60.0),
    ) -> None:
        self.base_url = base_url.rstrip("/")
        if session is None:
            try:
                import requests
            except ImportError as exc:
                raise RuntimeError("远程生图依赖未安装，请运行 pip install -e .[remote]") from exc
            session = requests.Session()
        self.session = session
        self.timeout = timeout
        self._object_info_cache: dict[str, Any] | None = None

    def validate_environment(self) -> EnvironmentReport:
        stats = self._get_json("/system_stats")
        queue = self._get_json("/queue")
        devices: list[str] = []
        for device in stats.get("devices", []):
            name = device.get("name") or device.get("type")
            if name:
                devices.append(str(name))
        running = queue.get("queue_running", [])
        pending = queue.get("queue_pending", [])
        warnings: list[str] = []
        arguments = stats.get("system", {}).get("argv", stats.get("system", {}).get("arguments", []))
        if isinstance(arguments, list):
            rendered_arguments = " ".join(str(item) for item in arguments)
            if "--listen 0.0.0.0" in rendered_arguments:
                warnings.append("ComfyUI 正在监听 0.0.0.0；请关闭公网端口，仅通过 SSH 隧道访问。")
        return EnvironmentReport(
            system_stats=stats,
            queue_running=len(running) if isinstance(running, list) else 0,
            queue_pending=len(pending) if isinstance(pending, list) else 0,
            devices=devices,
            warnings=warnings,
        )

    def validate_workflow_nodes(self, workflow: dict[str, Any]) -> list[str]:
        object_info = self._object_info()
        required = {
            str(node.get("class_type"))
            for node in workflow.values()
            if isinstance(node, dict) and node.get("class_type")
        }
        return sorted(required - set(object_info))

    def validate_workflow_inputs(self, workflow: dict[str, Any]) -> list[str]:
        """Validate enum-backed inputs such as model files before queueing."""
        object_info = self._object_info()
        errors: list[str] = []
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type", ""))
            definition = object_info.get(class_type, {})
            input_groups = definition.get("input", {}) if isinstance(definition, dict) else {}
            specifications: dict[str, Any] = {}
            for group_name in ("required", "optional"):
                group = input_groups.get(group_name, {}) if isinstance(input_groups, dict) else {}
                if isinstance(group, dict):
                    specifications.update(group)
            for input_name, value in node.get("inputs", {}).items():
                if isinstance(value, (list, tuple, dict)):
                    continue
                spec = specifications.get(input_name)
                choices = spec[0] if isinstance(spec, (list, tuple)) and spec else None
                if not isinstance(choices, (list, tuple)) or value in choices:
                    continue
                preview = ", ".join(str(item) for item in choices[:5])
                suffix = "…" if len(choices) > 5 else ""
                errors.append(
                    f"节点 {node_id} ({class_type}) 的 {input_name}={value!r} 不可用"
                    f"；可选：{preview}{suffix}"
                )
        return errors

    def _object_info(self) -> dict[str, Any]:
        if self._object_info_cache is None:
            self._object_info_cache = self._get_json("/object_info")
        return self._object_info_cache

    def submit(self, workflow: dict[str, Any], client_id: str, prompt_id: str) -> str:
        result = self._post_json(
            "/prompt",
            {"prompt": workflow, "client_id": client_id, "prompt_id": prompt_id},
        )
        if result.get("error") or result.get("node_errors"):
            raise ComfyAPIError(
                "ComfyUI 拒绝了工作流，请检查模型、节点和参数。",
                code="workflow_rejected",
                details=result,
            )
        returned = result.get("prompt_id") or prompt_id
        if not returned:
            raise ComfyAPIError("ComfyUI 未返回 prompt_id。", code="missing_prompt_id", details=result)
        return str(returned)

    def upload_image(
        self,
        image_path: Path,
        *,
        subfolder: str = "anima_gallery",
        remote_name: str = "",
    ) -> str:
        """Upload a local gallery image to ComfyUI and return its LoadImage name."""
        source = image_path.expanduser().resolve()
        try:
            size = source.stat().st_size
        except OSError as exc:
            raise ComfyAPIError(f"无法读取待处理图片：{exc}", code="source_unreadable") from exc
        if size <= 0:
            raise ComfyAPIError("待处理图片是空文件。", code="source_empty")
        if size > self.MAX_UPLOAD_BYTES:
            raise ComfyAPIError("待处理图片超过 100 MB 上传限制。", code="source_too_large")
        filename = remote_name or source.name
        try:
            with source.open("rb") as stream:
                response = self.session.post(
                    f"{self.base_url}/upload/image",
                    files={"image": (filename, stream, "application/octet-stream")},
                    data={"type": "input", "subfolder": subfolder, "overwrite": "true"},
                    timeout=self.timeout,
                )
            self._raise_for_status(response, "/upload/image")
            result = response.json()
        except ComfyAPIError:
            raise
        except Exception as exc:
            raise ComfyAPIError(f"上传原图到 ComfyUI 失败：{exc}", code="upload_failed") from exc
        if not isinstance(result, dict) or not result.get("name"):
            raise ComfyAPIError("ComfyUI 未返回上传文件名。", code="invalid_upload_response")
        uploaded_subfolder = str(result.get("subfolder") or subfolder).strip("/\\")
        uploaded_name = str(result["name"])
        return f"{uploaded_subfolder}/{uploaded_name}" if uploaded_subfolder else uploaded_name

    def get_history_entry(self, prompt_id: str) -> dict[str, Any] | None:
        result = self._get_json(f"/history/{prompt_id}")
        if prompt_id in result and isinstance(result[prompt_id], dict):
            return result[prompt_id]
        if result.get("prompt_id") == prompt_id:
            return result
        return None

    def get_queue(self) -> dict[str, Any]:
        return self._get_json("/queue")

    def wait_for_completion(
        self,
        prompt_id: str,
        *,
        on_state: Callable[[str, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        timeout_seconds: float = 24 * 60 * 60,
        poll_interval: float = 1.5,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> dict[str, Any]:
        deadline = clock() + timeout_seconds
        last_state = ""
        consecutive_missing = 0
        while clock() < deadline:
            if is_cancelled and is_cancelled():
                queue_state = self._prompt_queue_state(self.get_queue(), prompt_id)
                if queue_state == "running":
                    raise ComfyAPIError(
                        "任务已经在云端运行。为避免影响共享 ComfyUI，未发送全局中断；可稍后恢复并下载结果。",
                        code="running_cancel_unsupported",
                    )
                self.cancel_pending(prompt_id)
                raise ComfyAPIError("排队任务已取消。", code="canceled")
            entry = self.get_history_entry(prompt_id)
            if entry:
                error_message = self._history_error(entry)
                if error_message:
                    raise ComfyAPIError(error_message, code="execution_failed", details=entry)
                status = entry.get("status", {})
                if status.get("completed") is True or entry.get("outputs"):
                    if on_state:
                        on_state("completed", "云端生图完成")
                    return entry
            queue_state = self._prompt_queue_state(self.get_queue(), prompt_id)
            if queue_state == "missing":
                consecutive_missing += 1
                if consecutive_missing >= 20:
                    raise ComfyAPIError(
                        "远端队列和历史中都找不到该任务，ComfyUI 历史可能已被清理。",
                        code="remote_missing",
                    )
            else:
                consecutive_missing = 0
            if queue_state != last_state and on_state:
                if queue_state == "running":
                    on_state(queue_state, "云端正在执行")
                elif queue_state == "queued":
                    on_state(queue_state, "已进入云端队列")
            last_state = queue_state
            sleep(poll_interval)
        raise ComfyAPIError("等待 ComfyUI 任务完成超时。", code="timeout")

    def list_output_artifacts(self, history_entry: dict[str, Any]) -> list[RemoteArtifact]:
        artifacts: list[RemoteArtifact] = []
        seen: set[tuple[str, str, str]] = set()
        for node_id, output in history_entry.get("outputs", {}).items():
            if not isinstance(output, dict):
                continue
            for raw in output.get("images", []):
                if not isinstance(raw, dict) or not raw.get("filename"):
                    continue
                key = (str(raw["filename"]), str(raw.get("subfolder", "")), str(raw.get("type", "output")))
                if key in seen:
                    continue
                seen.add(key)
                artifacts.append(
                    RemoteArtifact(
                        node_id=str(node_id),
                        filename=key[0],
                        subfolder=key[1],
                        folder_type=key[2],
                    )
                )
        return artifacts

    def download_artifact(self, artifact: RemoteArtifact) -> tuple[bytes, str]:
        params = {
            "filename": artifact.filename,
            "subfolder": artifact.subfolder,
            "type": artifact.folder_type,
        }
        response = self.session.get(
            f"{self.base_url}/view?{urlencode(params)}",
            timeout=self.timeout,
        )
        self._raise_for_status(response, "/view")
        content = bytes(response.content)
        if not content:
            raise ComfyAPIError(f"下载到空文件：{artifact.filename}", code="empty_download")
        if len(content) > self.MAX_ARTIFACT_BYTES:
            raise ComfyAPIError(
                f"输出文件超过 512 MB 安全限制：{artifact.filename}",
                code="download_too_large",
            )
        content_type = str(response.headers.get("Content-Type", "application/octet-stream"))
        return content, content_type

    def cancel_pending(self, prompt_id: str) -> None:
        self._post_json("/queue", {"delete": [prompt_id]})

    def _get_json(self, path: str) -> dict[str, Any]:
        try:
            response = self.session.get(f"{self.base_url}{path}", timeout=self.timeout)
            self._raise_for_status(response, path)
            result = response.json()
        except ComfyAPIError:
            raise
        except Exception as exc:
            raise ComfyAPIError(f"无法访问 ComfyUI {path}：{exc}", code="connection_error") from exc
        if not isinstance(result, dict):
            raise ComfyAPIError(f"ComfyUI {path} 返回了无效数据。", code="invalid_response")
        return result

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
            self._raise_for_status(response, path)
            result = response.json()
        except ComfyAPIError:
            raise
        except Exception as exc:
            raise ComfyAPIError(f"无法提交到 ComfyUI {path}：{exc}", code="connection_error") from exc
        if not isinstance(result, dict):
            raise ComfyAPIError(f"ComfyUI {path} 返回了无效数据。", code="invalid_response")
        return result

    @staticmethod
    def _raise_for_status(response, path: str) -> None:
        try:
            response.raise_for_status()
        except Exception as exc:
            detail = ""
            try:
                detail = str(response.json())[:1000]
            except Exception:
                detail = str(getattr(response, "text", ""))[:1000]
            raise ComfyAPIError(
                f"ComfyUI {path} 请求失败（HTTP {getattr(response, 'status_code', '?')}）：{detail}",
                code="http_error",
            ) from exc

    @staticmethod
    def _prompt_queue_state(queue: dict[str, Any], prompt_id: str) -> str:
        for item in queue.get("queue_running", []):
            if prompt_id in item:
                return "running"
        for item in queue.get("queue_pending", []):
            if prompt_id in item:
                return "queued"
        return "missing"

    @staticmethod
    def _history_error(entry: dict[str, Any]) -> str:
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            messages = status.get("messages", [])
            for message in reversed(messages):
                if isinstance(message, (list, tuple)) and message and message[0] == "execution_error":
                    payload = message[1] if len(message) > 1 and isinstance(message[1], dict) else {}
                    return str(payload.get("exception_message") or "ComfyUI 工作流执行失败。")
            return "ComfyUI 工作流执行失败。"
        return ""
