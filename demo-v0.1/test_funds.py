import json, tempfile, unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from funds import FundTracker, FundConflict, CST, parse_history, performance, estimate

def quote(day,value="1",annual="3.6"):
    return dict(date=day,per10k=value,annual7=annual,nav=None)

def trade(ident="one",mode="actual",kind="buy",day="2026-01-01",amount="10000",units="10000",status="confirmed"):
    return dict(id=ident,revision=0,code="000343",mode=mode,kind=kind,status=status,date=day,
                amount=amount,units=units,note="测试",created_at="2026-01-01T00:00:00+08:00")

class FundTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.current=datetime(2026,9,29,8,59,tzinfo=CST);self.calls=[]
        def fetch(code):self.calls.append(code);return [quote("2026-09-28")],"verified test fixture"
        self.f=FundTracker(self.temp.name,fetcher=fetch,clock=lambda:self.current)
    def tearDown(self):self.temp.cleanup()
    def settings(self,enabled=True,time="09:00",watchlist=None):
        return self.f.settings(dict(version=self.f.public()["version"],enabled=enabled,time=time,watchlist=watchlist or ["000343"]))
    def test_schedule_persistence_and_catchup(self):
        self.settings();self.assertFalse(self.f.due());self.current+=timedelta(minutes=1);self.assertTrue(self.f.due())
        self.f.sync("scheduled");self.assertFalse(self.f.due());self.assertEqual(self.calls,["000343"])
        again=FundTracker(self.temp.name,fetcher=self.f.fetcher,clock=lambda:self.current)
        self.assertFalse(again.due());self.current+=timedelta(days=1,hours=2);self.assertTrue(again.due())
    def test_failure_retry_bounded_preserves_history(self):
        self.settings();self.f.sync();before=self.f.detail("000343",1,"actual")["latest"]
        def fail(code):raise OSError("offline")
        self.f.fetcher=fail;self.current+=timedelta(minutes=1)
        for i in range(3):
            self.assertTrue(self.f.due());self.f.sync("scheduled");self.assertFalse(self.f.due());self.current+=timedelta(hours=1)
        self.assertFalse(self.f.due());self.assertEqual(self.f.detail("000343",1,"actual")["latest"],before)
        self.assertEqual(self.f.public()["sources"]["000343"]["status"],"error")
    def test_manual_overlap_and_idempotent_quotes(self):
        self.settings();self.f.job_lock.acquire()
        self.assertFalse(self.f.sync());self.f.job_lock.release()
        self.f.sync();self.f.sync();self.assertEqual(self.f.public()["counts"]["000343"],1)
    def test_corrected_quote(self):
        self.settings();self.f.sync();self.f.fetcher=lambda code:([quote("2026-09-28","2")],"corrected")
        self.f.sync();self.assertEqual(self.f.public()["sources"]["000343"]["corrections"],1)
    def test_remove_preserves_quotes(self):
        self.settings();self.f.sync();self.f.settings(dict(version=self.f.public()["version"],enabled=False,time="10:30",watchlist=[]))
        self.assertFalse(self.f.due());self.assertEqual(self.f.public()["counts"]["000343"],1)
    def test_settings_conflicts_validation(self):
        with self.assertRaises(ValueError):self.settings(time="25:01")
        with self.assertRaises(ValueError):self.settings(watchlist=["000343","000343"])
        self.settings()
        with self.assertRaises(FundConflict):self.f.settings(dict(version=1,enabled=True,time="09:00",watchlist=["000343"]))
    def test_identity_parser_and_no_execution(self):
        ts=int(datetime(2026,9,28,tzinfo=CST).timestamp()*1000)
        text='var fS_name="华夏财富宝货币A";var fS_code="000343";var Data_millionCopiesIncome='+json.dumps([[ts,0.2]])+';var Data_sevenDaysYearIncome='+json.dumps([[ts,0.7]])+';'
        self.assertEqual(parse_history(text,"000343")[0]["date"],"2026-09-28")
        with self.assertRaises(ValueError):parse_history(text.replace('"000343"','"999999"'),"000343")
        with self.assertRaises(ValueError):parse_history(text.replace('0.2','null'),"000343")
        with self.assertRaises(ValueError):parse_history(text.replace('0.2','(()=>{return 0.2})()'),"000343")
    def test_calendar_compounding_and_gaps(self):
        rows=[quote((date(2026,8,28)+timedelta(days=i)).isoformat()) for i in range(32)]
        p=performance(rows,1);self.assertTrue(p["coverage"]);self.assertEqual(p["points"][0]["cumulative_pct"],"0")
        self.assertAlmostEqual(float(p["return_pct"]),((1.0001**31)-1)*100,places=8)
        self.assertIsNone(performance(rows[:4]+rows[5:],1)["return_pct"])
        self.assertEqual(performance([quote("2024-03-31")],1)["start"],"2024-02-29")
        for months in (1,3,6,12):self.assertIn("coverage",performance(rows,months))
    def test_accounts_separate_and_cashflow_not_profit(self):
        rows=[quote("2026-01-01"),quote("2026-01-02")]
        trades=[trade(),trade("sim","simulation",amount="20000",units="20000")]
        actual=estimate(rows,trades,"actual");sim=estimate(rows,trades,"simulation")
        self.assertEqual(actual["profit"],"2.00");self.assertEqual(sim["profit"],"4.00")
        self.assertEqual(actual["value"],"10002.00")
    def test_partial_sale_and_fee(self):
        rows=[quote("2026-01-01"),quote("2026-01-02")]
        trades=[trade(amount="10001"),trade("sell",kind="sell",day="2026-01-02",amount="5000",units="5000")]
        self.assertEqual(estimate(rows,trades,"actual")["profit"],"0.50")
    def test_pending_gaps_and_oversell(self):
        rows=[quote("2026-01-01"),quote("2026-01-03")]
        self.assertIsNone(estimate(rows,[trade()],"actual")["profit"])
        self.assertIsNone(estimate(rows,[trade(status="pending")],"actual")["profit"])
        self.assertIsNone(estimate(rows,[trade(kind="sell")],"actual")["profit"])
    def test_trade_edit_retry_restart_and_isolation(self):
        t=trade();t.pop("created_at");self.f.save_trade(t);self.f.save_trade(t)
        d=self.f.detail("000343",1,"actual");self.assertEqual(len(d["trades"]),1)
        self.assertEqual(self.f.detail("000343",1,"simulation")["trades"],[])
        t["amount"]="15000"
        with self.assertRaises(FundConflict):self.f.save_trade(t)
        t["revision"]=1;self.f.save_trade(t)
        again=FundTracker(self.temp.name);self.assertEqual(again.detail("000343",1,"actual")["trades"][0]["amount"],"15000")
        with self.assertRaises(FundConflict):self.f.delete_trade(dict(id=t["id"],revision=2,mode="simulation"))
        self.f.delete_trade(dict(id=t["id"],revision=2,mode="actual"));self.assertEqual(self.f.detail("000343",1,"actual")["trades"],[])
    def test_money_precision_invalid_date_no_ledger_writes(self):
        ledger=Path(self.temp.name)/"ledger.json";ledger.write_text('untouched')
        for field,value in [("amount","1.234"),("units","NaN"),("date","2030-01-01")]:
            t=trade();t.pop("created_at");t[field]=value
            with self.assertRaises(ValueError):self.f.save_trade(t)
        self.assertEqual(ledger.read_text(),'untouched')

if __name__=="__main__":unittest.main()
