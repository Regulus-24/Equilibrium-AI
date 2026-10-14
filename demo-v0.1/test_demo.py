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
if __name__=="__main__":unittest.main(verbosity=2)

