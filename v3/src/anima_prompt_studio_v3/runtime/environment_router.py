"""Deterministic, bounded routing; never submits or modifies creative inputs."""
from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import asdict

from .environment_probe import ProbeResult


class EnvironmentRouter:
    def __init__(self, candidates, probe, eligible, *, clock=time.monotonic, wall_clock=time.time):
        self.candidates, self.probe, self.eligible, self.clock, self.wall_clock = candidates, probe, eligible, clock, wall_clock

    async def resolve_environment(self, snapshot, policy, deadline, *, progress=None, recheck=False):
        candidates = self.candidates(snapshot, policy)
        if policy['mode'] == 'pinned':
            candidates = [c for c in candidates if c['id'] == policy['environmentId']]
        else:
            preferences = policy.get('preferredEnvironmentIds', [])
            candidates.sort(key=lambda c: (preferences.index(c['id']) if c['id'] in preferences else len(preferences),
                                           not c.get('last_success', False)))
        by_id = {c['id']: c for c in candidates}
        progress = dict(progress or {})
        old_order = progress.get('order', [])
        order = [i for i in old_order if i in by_id]
        order += [c['id'] for c in candidates if c['id'] not in order]
        checked = dict(progress.get('checked', {}))
        # A changed configuration invalidates only its own evidence.
        for key in list(checked):
            candidate = by_id.get(key)
            if (not candidate or checked[key].get('signature') != candidate.get('signature')
                    or self.wall_clock() - checked[key].get('recorded_at', 0) > 30):
                checked.pop(key)
        unchecked = [key for key in order if key not in checked]
        round_number = progress.get('round', 0)
        if not unchecked and (recheck or order):
            checked, unchecked = {}, list(order)
            round_number += 1
        async def check(candidate, budget):
            candidate_deadline = min(deadline, self.clock() + budget)
            try:
                result = await asyncio.wait_for(self.probe(candidate, candidate_deadline, candidate.get('epoch', 0)), budget)
                if result.connection_state != 'online' or result.capabilities_state != 'ready':
                    return {'probe': asdict(result), 'eligible': False, 'reasons': result.reason_codes, 'signature': candidate.get('signature'), 'recorded_at': self.wall_clock()}
                valid = self.eligible(snapshot, candidate, result)
                valid = await asyncio.wait_for(valid, max(.001, candidate_deadline - self.clock())) if inspect.isawaitable(valid) else valid
                accepted, reasons = valid
                return {'probe': asdict(result), 'eligible': bool(accepted), 'reasons': reasons, 'signature': candidate.get('signature'), 'recorded_at': self.wall_clock()}
            except (asyncio.TimeoutError, TimeoutError):
                return {'probe': asdict(ProbeResult(candidate['id'], candidate.get('epoch', 0), time.time(), 'offline', 'unchecked', ['timeout'])),
                        'eligible': False, 'reasons': ['timeout'], 'signature': candidate.get('signature'), 'recorded_at': self.wall_clock()}
            except Exception:
                return {'probe': asdict(ProbeResult(candidate['id'], candidate.get('epoch', 0), time.time(), 'offline', 'unchecked', ['probe_failed'])),
                        'eligible': False, 'reasons': ['probe_failed'], 'signature': candidate.get('signature'), 'recorded_at': self.wall_clock()}
        while unchecked and self.clock() < deadline:
            batch = unchecked[:2]
            budget = min(5., max(0., deadline - self.clock()))
            values = await asyncio.gather(*(check(by_id[key], budget) for key in batch))
            for key, value in zip(batch, values):
                checked[key] = value
            unchecked = unchecked[len(batch):]
            for key in order:
                # Later candidates cannot jump over unchecked higher preference.
                if key not in checked:
                    break
                if checked[key]['eligible']:
                    state = {'order': order, 'checked': checked, 'unchecked': unchecked, 'cursor': len(order) - len(unchecked), 'round': round_number}
                    return {'target': by_id[key], 'progress': state, 'reason': None, 'retryable': False}
        state = {'order': order, 'checked': checked, 'unchecked': unchecked, 'cursor': len(order) - len(unchecked), 'round': round_number}
        return {'target': None, 'progress': state, 'reason': 'unchecked' if unchecked else 'no_eligible_environment', 'retryable': True}
