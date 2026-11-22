"""Durable logical requests. Leases fence resolvers; acceptance shares the submission CAS."""
from __future__ import annotations

import json
import time
from uuid import uuid4

from ..core.requirements import digest
from .generation_submissions import IdempotencyConflict


class LeaseLost(RuntimeError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


class IntentStore:
    def __init__(self, workspaces, *, clock=time.time):
        self.workspaces, self.clock = workspaces, clock
        with workspaces._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS generation_intents(
                id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE, logical_hash TEXT NOT NULL,
                request_json TEXT NOT NULL, state TEXT NOT NULL,
                lease_owner TEXT, lease_epoch INTEGER NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0,
                candidate_progress_json TEXT NOT NULL DEFAULT '{}', resolved_target_json TEXT,
                submission_id TEXT UNIQUE, run_id TEXT UNIQUE, result_json TEXT,
                reason TEXT, retryable INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL, updated_at REAL NOT NULL)""")

    @staticmethod
    def record(row):
        if row is None:
            return None
        item = dict(row)
        for column, name in [('request_json', 'request'), ('candidate_progress_json', 'candidate_progress'),
                             ('resolved_target_json', 'resolved_target'), ('result_json', 'response')]:
            value = item.pop(column)
            item[name] = json.loads(value) if value is not None else None
        item['retryable'] = bool(item['retryable'])
        return item

    def create(self, key, body):
        key = key.strip()
        if not key or len(key) > 256:
            raise ValueError('幂等键必须是 1–256 个字符。')
        logical_hash = digest(body)
        with self.workspaces._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM generation_intents WHERE idempotency_key=?', (key,)).fetchone()
            if row:
                if row['logical_hash'] != logical_hash:
                    raise IdempotencyConflict('同一幂等键不能用于不同请求。')
                return self.record(row)
            now = self.clock()
            intent_id = 'intent_' + uuid4().hex
            db.execute('INSERT INTO generation_intents(id,idempotency_key,logical_hash,request_json,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                       (intent_id, key, logical_hash, encoded(body), 'resolving', now, now))
            return self.record(db.execute('SELECT * FROM generation_intents WHERE id=?', (intent_id,)).fetchone())

    def get(self, intent_id):
        with self.workspaces._connect() as db:
            row = db.execute('SELECT * FROM generation_intents WHERE id=?', (intent_id,)).fetchone()
        if row is None:
            raise KeyError(intent_id)
        return self.record(row)

    def acquire(self, intent_id, owner, *, seconds=25):
        with self.workspaces._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM generation_intents WHERE id=?', (intent_id,)).fetchone()
            if row is None:
                raise KeyError(intent_id)
            if row['state'] in {'accepted', 'canceled'} or not row['retryable'] or row['lease_until'] > self.clock():
                return None
            epoch = row['lease_epoch'] + 1
            db.execute("UPDATE generation_intents SET state='resolving',lease_owner=?,lease_epoch=?,lease_until=?,updated_at=? WHERE id=?",
                       (owner, epoch, self.clock() + seconds, self.clock(), intent_id))
            return epoch

    def guard(self, db, intent_id, epoch):
        row = db.execute('SELECT * FROM generation_intents WHERE id=?', (intent_id,)).fetchone()
        if row is None or row['state'] != 'resolving' or row['lease_epoch'] != epoch or row['lease_until'] <= self.clock():
            raise LeaseLost('生成意图的解析租约已失效。')
        return row

    def block(self, intent_id, epoch, progress, reason, retryable):
        with self.workspaces._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.guard(db, intent_id, epoch)
            db.execute("UPDATE generation_intents SET state='blocked',candidate_progress_json=?,reason=?,retryable=?,lease_until=0,updated_at=? WHERE id=?",
                       (encoded(progress), reason, retryable, self.clock(), intent_id))

    def acceptance(self, intent_id, epoch, target, progress, verify=None):
        """Called inside SubmissionStore's transaction before and after its insert."""
        def hook(db, entry=None):
            self.guard(db, intent_id, epoch)
            if entry is None:
                if verify:
                    verify(db)
                return
            db.execute("UPDATE generation_intents SET state='accepted',candidate_progress_json=?,resolved_target_json=?,submission_id=?,run_id=?,result_json=?,reason=NULL,retryable=0,lease_until=0,updated_at=? WHERE id=?",
                       (encoded(progress), encoded(target), entry['submission_id'], entry['run_id'], encoded(entry['response']), self.clock(), intent_id))
        return hook

    def cancel(self, intent_id):
        with self.workspaces._connect() as db:
            db.execute("UPDATE generation_intents SET state='canceled',retryable=0,lease_until=0,lease_epoch=lease_epoch+1,updated_at=? WHERE id=? AND state IN ('resolving','blocked')",
                       (self.clock(), intent_id))
        return self.get(intent_id)

    def recover_expired(self, intent_id):
        """A read after restart exposes interrupted resolution; it never resubmits."""
        with self.workspaces._connect() as db:
            db.execute("UPDATE generation_intents SET state='blocked',reason='resolution_interrupted',retryable=1,lease_until=0,updated_at=? "
                       "WHERE id=? AND state='resolving' AND ((lease_owner IS NOT NULL AND lease_until<=?) OR (lease_owner IS NULL AND created_at<?))",
                       (self.clock(), intent_id, self.clock(), self.clock() - 30))
        return self.get(intent_id)
