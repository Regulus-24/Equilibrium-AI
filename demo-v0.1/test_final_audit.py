import tempfile, unittest
from datetime import date,timedelta
from pathlib import Path
from server import Store
from funds import market_version
from vendor.io_utils import atomic_write_json

class FinalAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def test_empty_market_preview_stays_valid(self):
        s=self.store;r=s.insights.get_report(date.today().strftime('%Y-%m'))
        p=s.insights.preview({'period':r['period'],'version':r['version'],'funding':{}})
        self.assertEqual(p['product_version'],s.funds.public()['market_version'])
    def test_market_failure_and_day_change_invalidate(self):
        s=self.store.funds;d=s.read();today=s.clock().date();before=market_version(d,today)
        d['sources']['000343']={'status':'error'}
        self.assertNotEqual(before,market_version(d,today))
        self.assertNotEqual(market_version(d,today),market_version(d,today+timedelta(days=1)))
    def test_demo_preserves_other_cases_bindings(self):
        s=self.store
        atomic_write_json(s.cases_file,{'version':1,'items':{'user-case':{'id':'user-case'}}})
        atomic_write_json(s.bindings_file,{'version':1,'items':{'user-binding':{'card_last4':'0428'}}})
        s.demo_seed();s.demo_clear()
        self.assertEqual(s.cases(),[{'id':'user-case'}]);self.assertIn('user-binding',s.bindings())
    def test_unspent_category_budget_visible(self):
        s=self.store;r=s.save_budgets({'period':'2026-11','version':1,'total_cents':100000,'categories':{'餐饮':50000}})
        self.assertEqual(r['categories'][0]['remaining_cents'],50000)
    def test_separate_import_files_do_not_share_row_ids(self):
        from ledger_import import preview_bytes
        ledger=self.store.ledger
        ids=[]
        for amount in (12,13):
            raw=f"日期,收支类型,金额,分类\n2026-10-03,支出,{amount},交通\n".encode()
            preview=preview_bytes('test.csv',raw,ledger.public()['entries'])
            ids.append(preview['rows'][0]['id'])
            ledger.import_rows({'version':ledger.public()['version'],'rows':preview['rows'],'confirm':True})
        self.assertNotEqual(*ids)
        self.assertEqual(len(ledger.public()['entries']),2)
    def test_case_conflict_preserves_timeline(self):
        from server import Conflict
        s=self.store;s.demo_seed()
        s.transition_case({'case_id':'case-demo-0428','action':'review'})
        before=s.cases()
        with self.assertRaises(Conflict):s.transition_case({'case_id':'case-demo-0428','action':'review'})
        self.assertEqual(s.cases(),before)
    def test_all_terminal_case_paths_reject_replay(self):
        from server import Conflict
        s=self.store
        for actions in [('mark_normal',),('review','submit','close'),('close',)]:
            s.demo_seed()
            for action in actions:s.transition_case({'case_id':'case-demo-0428','action':action})
            with self.assertRaises(Conflict):s.transition_case({'case_id':'case-demo-0428','action':actions[-1]})
    def test_case_lock_requires_verified_card(self):
        from server import Conflict
        s=self.store;s.demo_seed()
        s.transition_case({'case_id':'case-demo-0428','action':'lock_previewed'})
        before=s.cases()
        with self.assertRaises(Conflict):s.transition_case({'case_id':'case-demo-0428','action':'locked'})
        self.assertEqual(before,s.cases())
        plan=s.plan({'card_id':'demo-card-0428'})
        s.approve({'plan_id':plan['plan']['id'],'plan_hash':plan['plan_hash'],'confirm':True})
        result=s.transition_case({'case_id':'case-demo-0428','action':'locked'})
        self.assertEqual(result['status'],'LOCKED')
    def test_cancelled_lock_preview_can_close_case(self):
        s=self.store;s.demo_seed()
        s.transition_case({'case_id':'case-demo-0428','action':'lock_previewed'})
        s.transition_case({'case_id':'case-demo-0428','action':'close'})
        self.assertEqual(s.public()['card']['status'],'ACTIVE')
    def test_ics_content(self):
        text=self.store.reminders_ics();self.assertTrue(text.startswith('BEGIN:VCALENDAR\r\n'));self.assertIn('BEGIN:VEVENT',text)

if __name__=='__main__':unittest.main()
