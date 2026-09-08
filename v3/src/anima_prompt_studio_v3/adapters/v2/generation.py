"""Compatibility import; maintain implementation in anima_prompt_studio_v3.runtime.generation."""
import sys
from ...runtime import generation as _implementation

sys.modules[__name__] = _implementation
