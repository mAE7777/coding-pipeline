from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from coordination import Store, Conflict, StaleOwner, PayloadMismatch, digest, canonical_json

class Clock:
    def __init__(self): self.value=1000.0
    def __call__(self): return self.value
    def advance(self, seconds): self.value+=seconds

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock=Clock()
        self.store=Store(Path(self.temp.name)/'state.db', self.clock)
    def task(self):
        self.store.create_task('t','job')
        return self.store.claim('t','job','a',10)
    def action(self):
        payload={'amount_minor':100,'order_id':'o17'}
        self.store.prepare_action('t','i17',payload)
        return payload
    def dispatch(self,payload,**kwargs):
        values=dict(approved_hash=digest(payload),approval_expires=1010,approved_plan=1,current_plan=1)
        values.update(kwargs)
        self.store.begin_dispatch('t','i17',**values)
    def test_01_concurrent_claim_has_one_winner(self):
        self.store.create_task('t','job')
        def work(i):
            try: self.store.claim('t','job',str(i),10); return True
            except Conflict: return False
        with ThreadPoolExecutor(max_workers=32) as p:
            self.assertEqual(sum(p.map(work,range(32))),1)
    def test_02_old_attempt_cannot_complete(self):
        old=self.task(); self.clock.advance(11)
        new=self.store.claim('t','job','b',10)
        self.assertGreater(new.generation,old.generation)
        with self.assertRaises(StaleOwner): self.store.complete(old,1,{})
        self.store.complete(new,1,{'verified':True})
    def test_03_renew_expired_lease_rejected(self):
        lease=self.task(); self.clock.advance(10)
        with self.assertRaises(StaleOwner): self.store.renew(lease,10)
    def test_04_renew_valid_lease(self):
        lease=self.task(); self.clock.advance(9); self.store.renew(lease,10)
        self.clock.advance(9); self.store.complete(lease,1,{})
    def test_05_cancel_blocks_old_result(self):
        lease=self.task(); self.store.cancel('t','job')
        with self.assertRaises(StaleOwner): self.store.complete(lease,1,{})
        with self.assertRaises(Conflict): self.store.claim('t','job','b',10)
    def test_06_replan_invalidates_execution(self):
        lease=self.task(); self.store.replan('t','job',2)
        with self.assertRaises(StaleOwner): self.store.complete(lease,1,{})
        new=self.store.claim('t','job','b',10)
        with self.assertRaises(Conflict): self.store.complete(new,1,{})
        self.store.complete(new,2,{})
    def test_07_terminal_task_cannot_replan(self):
        lease=self.task(); self.store.complete(lease,1,{})
        with self.assertRaises(Conflict): self.store.replan('t','job',2)
    def test_08_task_tenant_isolation(self):
        self.store.create_task('one','job'); self.store.create_task('two','job')
        a=self.store.claim('one','job','a',10); b=self.store.claim('two','job','b',10)
        self.store.complete(a,1,{}); self.store.complete(b,1,{})
    def test_09_resource_fences_stale_writer(self):
        a=self.store.acquire_resource('t','r','a',10); self.clock.advance(11)
        b=self.store.acquire_resource('t','r','b',10)
        self.store.write_resource(b,0,{'b':1})
        with self.assertRaises(StaleOwner): self.store.write_resource(a,1,{'a':1})
        self.assertEqual(self.store.resource('t','r')['body'],{'b':1})
    def test_10_generation_not_reused_on_release(self):
        a=self.store.acquire_resource('t','r','a',10)
        self.store.release_resource(a)
        b=self.store.acquire_resource('t','r','a',10)
        self.assertGreater(b.generation,a.generation)
        with self.assertRaises(StaleOwner): self.store.write_resource(a,0,{})
    def test_11_revision_conflict_not_overwrite(self):
        a=self.store.acquire_resource('t','r','a',10)
        self.store.write_resource(a,0,{'x':1})
        with self.assertRaises(Conflict): self.store.write_resource(a,0,{'x':2})
        self.assertEqual(self.store.resource('t','r')['revision'],1)
    def test_12_concurrent_resource_lease_rejected(self):
        self.store.acquire_resource('t','r','a',10)
        with self.assertRaises(Conflict): self.store.acquire_resource('t','r','b',10)
    def test_13_expired_resource_write_rejected(self):
        a=self.store.acquire_resource('t','r','a',10); self.clock.advance(10)
        with self.assertRaises(StaleOwner): self.store.write_resource(a,0,{})
    def test_14_failed_revision_emits_no_event(self):
        a=self.store.acquire_resource('t','r','a',10)
        with self.assertRaises(Conflict): self.store.write_resource(a,7,{})
        self.assertEqual(self.store.inspect('SELECT * FROM outbox'),[])
    def test_15_transaction_rolls_back_resource_and_event(self):
        a=self.store.acquire_resource('t','r','a',10)
        with self.store._connection() as db:
            db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.store.write_resource(a,0,{'changed':True})
        self.assertEqual(self.store.resource('t','r'),{'revision':0,'body':{}})
    def test_16_same_intent_same_payload_deduplicates(self):
        payload=self.action()
        self.assertEqual(self.store.prepare_action('t','i17',payload),'PREPARED')
        self.assertEqual(len(self.store.inspect('SELECT * FROM outbox')),1)
    def test_17_same_intent_changed_payload_rejected(self):
        self.action()
        with self.assertRaises(PayloadMismatch): self.store.prepare_action('t','i17',{'amount_minor':200})
    def test_18_unknown_action_cannot_be_redispatched(self):
        payload=self.action(); self.dispatch(payload)
        self.assertEqual(self.store.action('t','i17')['state'],'UNKNOWN')
        with self.assertRaises(Conflict): self.dispatch(payload)
    def test_19_lost_response_reconciles_without_resend(self):
        payload=self.action(); self.dispatch(payload)
        # Simulated external receipt lookup; no real external request is made.
        provider_ledger={'i17':{'provider_id':'p77','amount_minor':100}}
        self.store.record_success('t','i17',provider_ledger['i17'])
        self.store.record_success('t','i17',provider_ledger['i17'])
        self.assertEqual(self.store.action('t','i17')['state'],'SUCCEEDED')
        self.assertEqual(len(provider_ledger),1)
    def test_20_stale_approval_rejected(self):
        payload=self.action()
        with self.assertRaises(Conflict): self.dispatch(payload,approval_expires=999)
        self.assertEqual(self.store.action('t','i17')['state'],'PREPARED')
    def test_21_changed_plan_approval_rejected(self):
        payload=self.action()
        with self.assertRaises(Conflict): self.dispatch(payload,current_plan=2)
    def test_22_payload_binding_checked(self):
        payload=self.action()
        with self.assertRaises(Conflict): self.dispatch(payload,approved_hash=digest({'other':True}))
    def test_23_new_intent_allows_legitimate_repeat(self):
        payload=self.action(); self.store.prepare_action('t','i18',payload)
        self.assertEqual(len(self.store.inspect('SELECT * FROM actions')),2)
    def test_24_action_tenant_isolation(self):
        payload=self.action(); self.store.prepare_action('other','i17',payload)
        self.assertEqual(len(self.store.inspect('SELECT * FROM actions')),2)
    def test_25_duplicate_event_counted_once(self):
        def work(_): return self.store.consume_increment('t','c','e1','total')
        with ThreadPoolExecutor(max_workers=32) as p:
            self.assertEqual(sum(p.map(work,range(32))),1)
        self.assertEqual(self.store.inspect('SELECT value FROM counters')[0]['value'],1)
    def test_26_budget_not_oversubscribed(self):
        self.store.create_budget('t',100)
        def work(i):
            try: self.store.reserve('t',str(i),10); return True
            except Conflict: return False
        with ThreadPoolExecutor(max_workers=32) as p:
            self.assertEqual(sum(p.map(work,range(32))),10)
        self.assertEqual(self.store.inspect('SELECT available FROM budgets')[0]['available'],0)
    def test_27_reservation_and_settlement_idempotent(self):
        self.store.create_budget('t',100)
        self.store.reserve('t','j1',30); self.store.reserve('t','j1',30)
        self.store.settle('t','j1',20); self.store.settle('t','j1',20)
        self.assertEqual(self.store.inspect('SELECT available FROM budgets')[0]['available'],80)
    def test_28_reservation_payload_cannot_change(self):
        self.store.create_budget('t',100); self.store.reserve('t','j1',30)
        with self.assertRaises(PayloadMismatch): self.store.reserve('t','j1',40)
    def test_29_settlement_cannot_exceed_cap(self):
        self.store.create_budget('t',100); self.store.reserve('t','j1',30)
        with self.assertRaises(Conflict): self.store.settle('t','j1',31)
    def test_30_invalid_numbers_rejected(self):
        self.store.create_task('t','job')
        for ttl in (0,-1,float('inf'),float('nan'),True):
            with self.assertRaises(ValueError): self.store.claim('t','job','a',ttl)
        with self.assertRaises(ValueError): self.store.create_budget('t',1.5)
        with self.assertRaises(ValueError): canonical_json({'n':float('nan')})
    def test_31_hash_ignores_object_key_order(self):
        self.assertEqual(digest({'a':1,'b':2}),digest({'b':2,'a':1}))
        self.assertNotEqual(digest({'n':1}),digest({'n':'1'}))
    def test_32_conflicting_receipt_rejected(self):
        payload=self.action(); self.dispatch(payload)
        self.store.record_success('t','i17',{'id':'a'})
        with self.assertRaises(Conflict): self.store.record_success('t','i17',{'id':'b'})
    def test_33_restart_preserves_state(self):
        payload=self.action(); self.dispatch(payload)
        restarted=Store(self.store.path,self.clock)
        self.assertEqual(restarted.action('t','i17')['state'],'UNKNOWN')
    def test_34_resource_tenant_isolation(self):
        a=self.store.acquire_resource('one','r','a',10)
        b=self.store.acquire_resource('two','r','b',10)
        self.store.write_resource(a,0,{'a':1}); self.store.write_resource(b,0,{'b':1})
        self.assertEqual(self.store.resource('one','r')['body'],{'a':1})
    def test_35_no_receipt_before_dispatch(self):
        self.action()
        with self.assertRaises(Conflict): self.store.record_success('t','i17',{'id':'p1'})
    def test_36_reservation_rollback_on_insert_failure(self):
        self.store.create_budget('t',100)
        with self.store._connection() as db:
            db.execute("CREATE TRIGGER reject_reservation BEFORE INSERT ON reservations BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.store.reserve('t','j',10)
        self.assertEqual(self.store.inspect('SELECT available FROM budgets')[0]['available'],100)

if __name__=='__main__': unittest.main(verbosity=2)
