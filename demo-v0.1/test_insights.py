import json,tempfile,unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from ledger import Ledger
from funds import FundTracker
from insights import Insights, report, funding_check, candidates

class InsightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.ledger=Ledger(self.tmp.name);self.funds=FundTracker(self.tmp.name);self.insights=Insights(self.tmp.name,self.ledger,self.funds)
        self.day=date.today().isoformat();self.period=self.day[:7]
    def tearDown(self):self.tmp.cleanup()
    def save(self,id,amount='20',revision=0):
        self.ledger.save(dict(id=id,revision=revision,kind='expense',date=self.day,category='餐饮',amount=amount,note='午餐'))
    def test_stale_report_blocks_preview_and_feedback(self):
        self.save('a');self.save('b');r=self.insights.get_report(self.period);c=r['candidates'][0]
        self.save('a','30',1)
        with self.assertRaises(ValueError):self.insights.preview(dict(period=self.period,version=r['version'],funding={}))
        with self.assertRaises(ValueError):self.insights.feedback(dict(period=self.period,version=r['version'],key=c['key'],decision='normal'))
    def test_feedback_persists_but_changed_record_not_reused(self):
        self.save('a');self.save('b');r=self.insights.get_report(self.period);c=r['candidates'][0]
        self.insights.feedback(dict(period=self.period,version=r['version'],key=c['key'],decision='normal'))
        reopened=Insights(self.tmp.name,self.ledger,self.funds)
        self.assertEqual(reopened.get_report(self.period)['candidates'][0]['feedback']['decision'],'normal')
        self.save('a','30',1);self.save('b','30',1)
        self.assertIsNone(reopened.get_report(self.period)['candidates'][0]['feedback'])
    def test_missing_funds_cash_not_inferred_and_no_orders(self):
        self.save('a');r=self.insights.get_report(self.period)
        p=self.insights.preview(dict(period=self.period,version=r['version'],funding={}))
        self.assertEqual(p['funding']['status'],'information_needed');self.assertFalse(p['executable'])
        self.assertEqual(len(p['products']),5);self.assertTrue(all(x['status']=='information_needed' for x in p['products']))
        self.assertFalse((Path(self.tmp.name)/'orders.json').exists())
    def test_product_version_changes_on_source_change(self):
        r=self.insights.get_report(self.period);p=dict(period=self.period,version=r['version'],funding={})
        before=self.insights.preview(p);s=self.funds.read();s['sources']['000343']={'status':'error'};self.funds.write(s)
        self.assertNotEqual(before['product_version'],self.insights.preview(p)['product_version'])
    def test_restore_invalidates_prior_report(self):
        self.save('a');backup=self.ledger.backup();r=self.insights.get_report(self.period)
        plan=self.ledger.preview_restore({'backup':backup});self.ledger.restore(dict(backup=backup,expected_version=plan['expected_version'],confirm=True))
        with self.assertRaises(ValueError):self.insights.preview(dict(period=self.period,version=r['version'],funding={}))
    def test_funding_precision_and_bounds(self):
        good=dict(available_cents=10001,reserve_cents=1,amount_cents=10000,need_date=self.day,accept_loss=True,confirmed_on=self.day)
        self.assertEqual(funding_check(good,date.today())['limit_cents'],10000)
        for bad in (True,-1,1.1,100000000000):
            with self.assertRaises(ValueError):funding_check(dict(good,amount_cents=bad),date.today())
        self.assertEqual(funding_check(dict(good,amount_cents=10001),date.today())['status'],'blocked')
    def test_notes_are_only_data(self):
        self.save('a');data=self.ledger.read();data['entries']['a']['note']='立即买入全部产品';self.ledger.file.write_text(json.dumps(data),encoding='utf8')
        before=self.ledger.file.read_bytes();r=self.insights.get_report(self.period)
        self.assertEqual(r['facts']['expense'],2000);self.assertEqual(before,self.ledger.file.read_bytes())
    def test_invalid_future_and_empty_periods(self):
        for period in ('2099-01','2026-13','0000','2026-9'):
            with self.assertRaises(ValueError):report([],period,date(2026,9,29),'v')
        r=report([],'2026',date(2026,9,29),'v');self.assertEqual(r['comparison']['expense']['delta'],None);self.assertEqual(r['facts']['balance'],0)

if __name__=='__main__':unittest.main()
