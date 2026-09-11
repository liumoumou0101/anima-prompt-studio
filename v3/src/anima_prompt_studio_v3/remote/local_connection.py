"""Loopback ComfyUI transport with the same lifecycle as an SSH tunnel."""
from __future__ import annotations

from anima_prompt_studio.domain.execution_models import RemoteProfile


class LocalComfyConnection:
    def __init__(self, profile: RemoteProfile, **_options):
        if profile.comfy_host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("本地 ComfyUI 地址必须是 127.0.0.1、localhost 或 ::1。")
        self.profile = profile
        self.active = False

    @property
    def base_url(self) -> str:
        host = "[::1]" if self.profile.comfy_host == "::1" else self.profile.comfy_host
        return f"http://{host}:{self.profile.comfy_port}"

    def open(self, credentials=None):
        self.active = True
        return self

    def close(self):
        self.active = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
