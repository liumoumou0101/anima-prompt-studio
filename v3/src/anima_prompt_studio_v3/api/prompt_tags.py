"""Authenticated local tag recognition for human-reviewed recommendation inputs."""
from fastapi import Depends
from pydantic import Field

from ..core.prompt_tag_matcher import prompt_tag_matches
from ..core.requirements import ContractModel
from ..data.store import ReferenceDataStore


class PromptTagsRequest(ContractModel):
    prompt: str = Field(max_length=20_000)
    limit: int = Field(default=50, ge=1, le=50)


def register_prompt_tag_routes(app, require_reference_db, require_session):
    @app.post("/api/v3/tags/from-prompt", dependencies=[Depends(require_session)])
    def recognize_prompt_tags(payload: PromptTagsRequest, database=Depends(require_reference_db)):
        with ReferenceDataStore(database) as store:
            return prompt_tag_matches(store, payload.prompt, limit=payload.limit)
