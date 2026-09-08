"""Read-only server checks. A passing check is not a generation guarantee."""
from datetime import datetime, timezone

from .packaged_workflows import workflow_revision


def inspect_workflows(client, profiles):
    items = []
    for profile in profiles:
        missing = client.validate_workflow_nodes(profile.api_workflow)
        invalid = client.validate_workflow_inputs(profile.api_workflow)
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
