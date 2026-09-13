"""Read-only server checks. A passing check is not a generation guarantee."""
from datetime import datetime, timezone

from .packaged_workflows import workflow_revision
from ..core.model_versions import requires_expanded_anima, expanded_anima_version_error


def inspect_workflows(client, profiles):
    items = []
    profiles = list(profiles)
    version = None
    if any(requires_expanded_anima(p) for p in profiles):
        version = client.validate_environment().system_stats.get("system", {}).get("comfyui_version")
    for profile in profiles:
        missing = client.validate_workflow_nodes(profile.api_workflow)
        invalid = client.validate_workflow_inputs(profile.api_workflow)
        if requires_expanded_anima(profile) and (error := expanded_anima_version_error(version)):
            invalid.append(error)
        items.append({
            "workflow_id": profile.id,
            "display_name": profile.display_name,
            "revision": workflow_revision(profile),
            "model_profiles": profile.compatible_model_profiles,
            "state": "missing_nodes" if missing else "invalid_inputs" if invalid else "checks_passed",
            "missing_nodes": missing,
            "invalid_inputs": invalid,
        })
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "items": items,
            "scope": "template_nodes_and_enum_inputs", "generation_verified": False}
