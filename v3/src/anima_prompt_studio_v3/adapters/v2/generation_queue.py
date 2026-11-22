"""Compatibility import; maintain implementation in anima_prompt_studio_v3.runtime.generation_queue."""
import sys
from ...runtime import generation_queue as _implementation

sys.modules[__name__] = _implementation
