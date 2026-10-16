"""Single-host teaching implementation. No network calls or production credentials.

SQLite serializes short write transactions. This is not a distributed lock service.
The caller identity and authorization represented here are trusted application inputs;
a production service must authenticate and authorize them before calling this module.
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Iterator
import json
import math
import sqlite3
import time

class Conflict(RuntimeError):
    """The proposed transition is not valid against current state."""

class StaleOwner(Conflict):
    """Ownership, generation, or lease is no longer valid."""

class PayloadMismatch(Conflict):
    """One business intent must not be reused with another payload."""


def canonical_json(value: Any) -> str:
    # This is this application's JSON encoding, not RFC 8785 canonical JSON.
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _positive_seconds(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("duration must be finite and positive")


def _integer(value: int, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"expected integer >= {minimum}")


@dataclass(frozen=True)
class Lease:
    tenant: str
    key: str
    owner: str
    generation: int


class Store:
    def __init__(self, path: str | Path, clock: Callable[[], float] = time.time):
        self.path = str(path)
        self.clock = clock
        if self.path == ":memory:":
            raise ValueError("use a file: separate connections must share durable state")
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript('''
            CREATE TABLE IF NOT EXISTS tasks(
              tenant TEXT NOT NULL, key TEXT NOT NULL, plan INTEGER NOT NULL,
              state TEXT NOT NULL DEFAULT 'READY', owner TEXT,
              generation INTEGER NOT NULL DEFAULT 0, expires REAL,
              result TEXT, PRIMARY KEY(tenant,key));
            CREATE TABLE IF NOT EXISTS resources(
              tenant TEXT NOT NULL, key TEXT NOT NULL, owner TEXT,
              generation INTEGER NOT NULL DEFAULT 0, expires REAL,
              revision INTEGER NOT NULL DEFAULT 0, body TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY(tenant,key));
            CREATE TABLE IF NOT EXISTS actions(
              tenant TEXT NOT NULL, intent TEXT NOT NULL, payload_hash TEXT NOT NULL,
              payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PREPARED',
              receipt TEXT, PRIMARY KEY(tenant,intent));
            CREATE TABLE IF NOT EXISTS outbox(
              id INTEGER PRIMARY KEY AUTOINCREMENT, tenant TEXT NOT NULL,
              kind TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS inbox(
              tenant TEXT NOT NULL, consumer TEXT NOT NULL, event_id TEXT NOT NULL,
              PRIMARY KEY(tenant,consumer,event_id));
            CREATE TABLE IF NOT EXISTS counters(
              tenant TEXT NOT NULL, key TEXT NOT NULL, value INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY(tenant,key));
            CREATE TABLE IF NOT EXISTS budgets(
              tenant TEXT PRIMARY KEY, available INTEGER NOT NULL CHECK(available>=0));
            CREATE TABLE IF NOT EXISTS reservations(
              tenant TEXT NOT NULL, key TEXT NOT NULL, amount INTEGER NOT NULL,
              state TEXT NOT NULL DEFAULT 'RESERVED', actual INTEGER,
              PRIMARY KEY(tenant,key));
            ''')

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def create_task(self, tenant: str, key: str, plan: int = 1) -> None:
        _integer(plan, 1)
        with self._tx() as db:
            db.execute("INSERT INTO tasks(tenant,key,plan) VALUES(?,?,?)", (tenant,key,plan))

    def claim(self, tenant: str, key: str, owner: str, ttl: float) -> Lease:
        _positive_seconds(ttl)
        with self._tx() as db:
            now = self.clock()
            row = db.execute("SELECT * FROM tasks WHERE tenant=? AND key=?", (tenant,key)).fetchone()
            if row is None or not (row['state']=='READY' or
                    (row['state']=='RUNNING' and row['expires'] <= now)):
                raise Conflict("task unavailable")
            generation = row['generation'] + 1
            db.execute("UPDATE tasks SET state='RUNNING',owner=?,generation=?,expires=? WHERE tenant=? AND key=?",
                       (owner,generation,now+ttl,tenant,key))
            return Lease(tenant,key,owner,generation)

    def _task_owner(self, db: sqlite3.Connection, lease: Lease) -> sqlite3.Row:
        row = db.execute("SELECT * FROM tasks WHERE tenant=? AND key=?", (lease.tenant,lease.key)).fetchone()
        if row is None or row['state']!='RUNNING' or row['owner']!=lease.owner or \
                row['generation']!=lease.generation or row['expires'] <= self.clock():
            raise StaleOwner("task owner is no longer current")
        return row

    def renew(self, lease: Lease, ttl: float) -> None:
        _positive_seconds(ttl)
        with self._tx() as db:
            self._task_owner(db,lease)
            db.execute("UPDATE tasks SET expires=? WHERE tenant=? AND key=?",
                       (self.clock()+ttl,lease.tenant,lease.key))

    def complete(self, lease: Lease, expected_plan: int, result: Any) -> None:
        body = canonical_json(result)
        with self._tx() as db:
            row = self._task_owner(db,lease)
            if row['plan'] != expected_plan:
                raise Conflict("plan changed")
            # Caller must independently verify acceptance before this transition.
            db.execute("UPDATE tasks SET state='SUCCEEDED',result=?,owner=NULL,expires=NULL WHERE tenant=? AND key=?",
                       (body,lease.tenant,lease.key))

    def cancel(self, tenant: str, key: str) -> None:
        with self._tx() as db:
            cur = db.execute("UPDATE tasks SET state='CANCELED',owner=NULL,expires=NULL,generation=generation+1 "
                             "WHERE tenant=? AND key=? AND state IN ('READY','RUNNING')", (tenant,key))
            if cur.rowcount != 1:
                raise Conflict("cannot cancel this task state")

    def replan(self, tenant: str, key: str, new_plan: int) -> None:
        _integer(new_plan,1)
        with self._tx() as db:
            row = db.execute("SELECT * FROM tasks WHERE tenant=? AND key=?", (tenant,key)).fetchone()
            if row is None or row['state'] not in ('READY','RUNNING') or new_plan <= row['plan']:
                raise Conflict("new plan must advance a nonterminal task")
            db.execute("UPDATE tasks SET plan=?,state='READY',owner=NULL,expires=NULL,generation=generation+1 "
                       "WHERE tenant=? AND key=?", (new_plan,tenant,key))

    def acquire_resource(self, tenant: str, key: str, owner: str, ttl: float) -> Lease:
        _positive_seconds(ttl)
        with self._tx() as db:
            db.execute("INSERT OR IGNORE INTO resources(tenant,key) VALUES(?,?)", (tenant,key))
            row = db.execute("SELECT * FROM resources WHERE tenant=? AND key=?", (tenant,key)).fetchone()
            now = self.clock()
            if row['owner'] is not None and row['expires'] > now:
                raise Conflict("resource leased")
            generation = row['generation'] + 1
            db.execute("UPDATE resources SET owner=?,generation=?,expires=? WHERE tenant=? AND key=?",
                       (owner,generation,now+ttl,tenant,key))
            return Lease(tenant,key,owner,generation)

    def _resource_owner(self, db: sqlite3.Connection, lease: Lease) -> sqlite3.Row:
        row = db.execute("SELECT * FROM resources WHERE tenant=? AND key=?", (lease.tenant,lease.key)).fetchone()
        if row is None or row['owner']!=lease.owner or row['generation']!=lease.generation or \
                row['expires'] is None or row['expires'] <= self.clock():
            raise StaleOwner("resource fence rejected")
        return row

    def resource(self, tenant: str, key: str) -> dict[str,Any]:
        with self._connection() as db:
            row = db.execute("SELECT revision,body FROM resources WHERE tenant=? AND key=?", (tenant,key)).fetchone()
            if row is None:
                raise Conflict("resource unavailable")
            return dict(revision=row['revision'],body=json.loads(row['body']))

    def write_resource(self, lease: Lease, expected_revision: int, body: Any) -> int:
        encoded = canonical_json(body)
        with self._tx() as db:
            row = self._resource_owner(db,lease)
            if row['revision'] != expected_revision:
                raise Conflict("revision changed")
            revision = row['revision'] + 1
            db.execute("UPDATE resources SET revision=?,body=? WHERE tenant=? AND key=?",
                       (revision,encoded,lease.tenant,lease.key))
            # Local mutation and notification intent share one transaction.
            db.execute("INSERT INTO outbox(tenant,kind,body) VALUES(?,?,?)",
                       (lease.tenant,'resource.updated',canonical_json(dict(key=lease.key,revision=revision))))
            return revision

    def release_resource(self, lease: Lease) -> None:
        with self._tx() as db:
            self._resource_owner(db,lease)
            db.execute("UPDATE resources SET owner=NULL,expires=NULL WHERE tenant=? AND key=?", (lease.tenant,lease.key))
            # Keep the row and generation; deleting it would allow generation reuse.

    def prepare_action(self, tenant: str, intent: str, payload: Any) -> str:
        encoded, hashed = canonical_json(payload), digest(payload)
        with self._tx() as db:
            row = db.execute("SELECT * FROM actions WHERE tenant=? AND intent=?", (tenant,intent)).fetchone()
            if row:
                if row['payload_hash'] != hashed:
                    raise PayloadMismatch("intent payload changed")
                return row['state']
            db.execute("INSERT INTO actions(tenant,intent,payload_hash,payload) VALUES(?,?,?,?)",
                       (tenant,intent,hashed,encoded))
            db.execute("INSERT INTO outbox(tenant,kind,body) VALUES(?,?,?)",
                       (tenant,'action.prepared',canonical_json(dict(intent=intent,payload_hash=hashed))))
            return 'PREPARED'

    def begin_dispatch(self, tenant: str, intent: str, approved_hash: str,
                       approval_expires: float, approved_plan: int, current_plan: int) -> None:
        # The caller must obtain approval fields from a trusted authorization service.
        # Mark UNKNOWN *before* network access: a crash afterward requires reconciliation.
        with self._tx() as db:
            row = db.execute("SELECT * FROM actions WHERE tenant=? AND intent=?", (tenant,intent)).fetchone()
            if row is None or row['state'] != 'PREPARED':
                raise Conflict("not dispatchable; reconcile existing action")
            if not math.isfinite(approval_expires) or approval_expires <= self.clock() or approved_plan != current_plan or \
                    approved_hash != row['payload_hash']:
                raise Conflict("approval is stale or does not bind this payload")
            db.execute("UPDATE actions SET state='UNKNOWN' WHERE tenant=? AND intent=?", (tenant,intent))

    def record_success(self, tenant: str, intent: str, receipt: Any) -> None:
        # Accept only a verified, correlated provider receipt at the application boundary.
        encoded = canonical_json(receipt)
        with self._tx() as db:
            row = db.execute("SELECT state,receipt FROM actions WHERE tenant=? AND intent=?", (tenant,intent)).fetchone()
            if row is None or row['state'] not in ('UNKNOWN','SUCCEEDED'):
                raise Conflict("receipt does not match a dispatched action")
            if row['state']=='SUCCEEDED':
                if row['receipt'] != encoded:
                    raise Conflict("receipt conflict")
                return
            db.execute("UPDATE actions SET state='SUCCEEDED',receipt=? WHERE tenant=? AND intent=?", (encoded,tenant,intent))

    def action(self, tenant: str, intent: str) -> dict[str,Any]:
        with self._connection() as db:
            row = db.execute("SELECT state,payload_hash,receipt FROM actions WHERE tenant=? AND intent=?", (tenant,intent)).fetchone()
            if row is None:
                raise Conflict("action unavailable")
            return dict(row)

    def consume_increment(self, tenant: str, consumer: str, event_id: str, key: str) -> bool:
        with self._tx() as db:
            cur = db.execute("INSERT OR IGNORE INTO inbox VALUES(?,?,?)", (tenant,consumer,event_id))
            if cur.rowcount == 0:
                return False
            db.execute("INSERT INTO counters VALUES(?,?,1) ON CONFLICT(tenant,key) DO UPDATE SET value=value+1", (tenant,key))
            return True

    def create_budget(self, tenant: str, amount: int) -> None:
        _integer(amount)
        with self._tx() as db:
            db.execute("INSERT INTO budgets VALUES(?,?)", (tenant,amount))

    def reserve(self, tenant: str, key: str, amount: int) -> None:
        _integer(amount,1)
        with self._tx() as db:
            old = db.execute("SELECT amount FROM reservations WHERE tenant=? AND key=?", (tenant,key)).fetchone()
            if old:
                if old['amount'] != amount:
                    raise PayloadMismatch("reservation amount changed")
                return
            cur = db.execute("UPDATE budgets SET available=available-? WHERE tenant=? AND available>=?", (amount,tenant,amount))
            if cur.rowcount != 1:
                raise Conflict("insufficient budget")
            db.execute("INSERT INTO reservations(tenant,key,amount) VALUES(?,?,?)", (tenant,key,amount))

    def settle(self, tenant: str, key: str, actual: int) -> None:
        _integer(actual)
        with self._tx() as db:
            row = db.execute("SELECT * FROM reservations WHERE tenant=? AND key=?", (tenant,key)).fetchone()
            if row is None or actual > row['amount']:
                raise Conflict("missing reservation or usage exceeds reserved hard cap")
            if row['state']=='SETTLED':
                if row['actual']!=actual:
                    raise PayloadMismatch("settlement changed")
                return
            db.execute("UPDATE budgets SET available=available+? WHERE tenant=?", (row['amount']-actual,tenant))
            db.execute("UPDATE reservations SET state='SETTLED',actual=? WHERE tenant=? AND key=?", (actual,tenant,key))

    def inspect(self, sql: str, args: tuple = ()) -> list[dict[str,Any]]:
        """Trusted test/debug API, NOT an agent-facing SQL tool."""
        with self._connection() as db:
            return [dict(r) for r in db.execute(sql,args)]
