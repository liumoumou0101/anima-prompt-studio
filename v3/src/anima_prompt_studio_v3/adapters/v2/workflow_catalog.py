"""Compatibility import; maintain implementation in anima_prompt_studio_v3.runtime.workflow_catalog."""
import sys
from ...runtime import workflow_catalog as _implementation

sys.modules[__name__] = _implementation
