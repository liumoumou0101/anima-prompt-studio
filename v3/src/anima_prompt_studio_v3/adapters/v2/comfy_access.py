"""Compatibility import; maintain implementation in anima_prompt_studio_v3.runtime.comfy_access."""
import sys
from ...runtime import comfy_access as _implementation

sys.modules[__name__] = _implementation
