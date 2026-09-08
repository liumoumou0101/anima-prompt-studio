"""Compatibility import; maintain implementation in anima_prompt_studio_v3.runtime.packaged_workflows."""
import sys
from ...runtime import packaged_workflows as _implementation

sys.modules[__name__] = _implementation
