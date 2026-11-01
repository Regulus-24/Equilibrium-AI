import json, tempfile, time, unittest
from pathlib import Path
from server import Store, Conflict, summary, digest
class DemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def plan(self): return self.store.plan({"card_id":"demo-card-0428"})
    def approval(self,p):return {"plan_id":p["plan"]["id"],"plan_hash":p["plan_hash"],"confirm":True}
    def test_accounting(self):
        self.assertEqual(summary()["net_expense"],690900);self.assertEqual(summary()["income"],1200000)
        self.assertEqual(summary()["categories"]["购物"],66000)
    def test_preview_and_required_confirmation(self):
        p=self.plan();self.assertEqual(self.store.public()["card"]["status"],"ACTIVE")
        bad=self.approval(p);bad["confirm"]=False
        with self.assertRaises(ValueError):self.store.approve(bad)
        self.assertEqual(self.store.public()["card"]["status"],"ACTIVE")
    def test_hash_and_extra_fields(self):
        p=self.plan();bad=self.approval(p);bad["plan_hash"]="0"*64
        with self.assertRaises(Conflict):self.store.approve(bad)
        bad=self.approval(p);bad["action"]="UNLOCK"
        with self.assertRaises(ValueError):self.store.approve(bad)
        self.assertEqual(self.store.public()["card"]["status"],"ACTIVE")
    def test_expiry(self):
        p=self.plan();state=self.store.read();saved=state["plans"][p["plan"]["id"]]
        saved["plan"]["expires_at"]=time.time()-1;saved["hash"]=digest(saved["plan"]);self.store.write(state)
        p["plan_hash"]=saved["hash"]
        with self.assertRaises(Conflict):self.store.approve(self.approval(p))
    def test_changed_card(self):
        p=self.plan();state=self.store.read();state["card"]["version"]+=1;self.store.write(state)
        with self.assertRaises(Conflict):self.store.approve(self.approval(p))
    def test_idempotency_and_restart(self):
        p=self.plan();result=self.store.approve(self.approval(p));restarted=Store(self.tmp.name)
        again=restarted.approve(self.approval(p));self.assertTrue(again["replayed"])
        self.assertEqual(result["receipt"]["id"],again["receipt"]["id"])
        self.assertEqual(len(restarted.public()["receipts"]),1)
        self.assertEqual(restarted.public()["card"]["version"],2)
        self.assertEqual(restarted.public()["events"][-1]["event"],"state.verified")
    def test_unknown_card(self):
        with self.assertRaises(ValueError):self.store.plan({"card_id":"another-users-card"})
    def test_no_loss(self):
        result=self.store.compare({"days":90,"accept_loss":False})
        self.assertFalse(any(p["eligible"] for p in result["products"]))
        self.assertFalse(result["purchasing_enabled"])
    def test_cash_date(self):
        result=self.store.compare({"days":90,"accept_loss":True})
        self.assertTrue(result["products"][0]["eligible"]);self.assertFalse(result["products"][1]["eligible"])
    def test_feedback_survives_reset(self):
        self.store.feedback({"useful":"maybe","note":"TEST ONLY"});self.store.reset()
        rows=json.loads((Path(self.tmp.name)/"feedback.json").read_text(encoding="utf8"))
        self.assertEqual(len(rows),1)
    def test_cross_scene_summary_links_suspicious_transaction_to_card(self):
        result=self.store.cross_scene_summary("2026-09")
        self.assertEqual(result["action"],"preview_temporary_lock")
        self.assertEqual(result["suspicious_transactions"][0]["id"],"T09")
        self.assertEqual(result["card"]["status"],"ACTIVE")
    def test_card_summary_exposes_billing_cycle_and_suspicious_rows(self):
        result=self.store.card_summary("2026-09")
        self.assertEqual(result["transaction_count"],8)
        self.assertEqual(result["suspicious"][0]["id"],"T09")
        self.assertEqual(result["card"]["payment_due_day"],10)
        self.assertIn("next_payment_due",result)
    def test_card_binding_is_separate_from_legacy_ledger_schema(self):
        self.store.ledger.save({"id":"manual-1","revision":0,"kind":"expense","amount":"12.5","date":"2026-10-01","category":"餐饮","note":"午餐"})
        result=self.store.save_binding({"entry_id":"manual-1","card_id":"demo-card-0428","card_last4":"0428","status":"linked","source":"manual"})
        self.assertEqual(result["binding"]["card_last4"],"0428")
        self.assertEqual(self.store.ledger.public()["entries"][0]["id"],"manual-1")
    def test_case_state_machine_keeps_timeline_and_rejects_invalid_transition(self):
        self.store.ledger.save({"id":"case-tx","revision":0,"kind":"expense","amount":"12.5","date":"2026-10-01","category":"餐饮","note":"待核实"})
        version=self.store.ledger.public()["version"]
        case=self.store.create_case({"period":"2026-10","ledger_version":version,"transaction_ids":["case-tx"]})
        self.assertEqual(case["status"],"OPEN")
        case=self.store.transition_case({"case_id":case["id"],"action":"review"})
        self.assertEqual(case["status"],"UNDER_REVIEW")
        with self.assertRaises(ValueError): self.store.transition_case({"case_id":case["id"],"action":"locked"})
        case=self.store.transition_case({"case_id":case["id"],"action":"submit"})
        self.assertEqual(case["status"],"SUBMITTED")
        self.assertEqual(len(case["timeline"]),3)
    def test_reminders_include_card_due(self):
        result=self.store.reminders("2026-09")
        self.assertEqual(result["period"],"2026-09")
        self.assertEqual(result["items"][0]["type"],"card_payment_due")
if __name__=="__main__":unittest.main(verbosity=2)
