"""Stub 替代提示词小助手的 ComfyUI ``server`` 模块。

移植的 LLM 服务层会懒加载 ``is_streaming_progress_enabled``，本模块提供
稳定的等价实现。ANIMA V3 当前不提供流式进度展示，故返回常量。
"""


def is_streaming_progress_enabled() -> bool:
    """返回前端是否应接收流式进度更新。"""
    return False
