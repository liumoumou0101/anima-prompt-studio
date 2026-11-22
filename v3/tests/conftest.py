"""Keep legacy unit tests isolated from the new external semantic review call.

Integration tests marked real_rewrite_review exercise the real reviewer, mocking
only its external transport. Other tests retain their original component scope.
There are no production flags or alternate production implementations.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_rewrite_review(request, monkeypatch):
    if request.node.get_closest_marker('real_rewrite_review'):
        return
    from anima_prompt_studio_v3.core import rewrite_review

    async def accepted(context, candidate, *, timeout_s=45):
        return {'issues': [], 'conflicts': []}

    monkeypatch.setattr(rewrite_review, 'review_rewrite', accepted)
