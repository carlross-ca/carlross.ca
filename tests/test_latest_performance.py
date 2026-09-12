import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from update_latest_performance import write_latest


class DailyExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site = Path(self.tmp.name)
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.execute('CREATE TABLE fact_performance_paths_daily (period_key TEXT,date TEXT,equity_index REAL,spx_tr_index_cad REAL,drawdown REAL,spx_tr_drawdown_cad REAL)')
        self.conn.execute("INSERT INTO fact_performance_paths_daily VALUES ('since_inception','2026-05-01',99,101,-0.01,0)")
        self.path = self.site / 'data/latest_performance.json'

    def test_new_day_updates_chart_and_summary_together(self):
        first = write_latest(self.conn,self.site,'2026-05-01')
        self.assertEqual(first['portfolio_since_inception'],'-1.00%')
        self.assertEqual(len(first['chart']['portfolio'].split()),2) # baseline plus first return
        self.conn.execute("INSERT INTO fact_performance_paths_daily VALUES ('since_inception','2026-05-04',110,103,0,0)")
        second = write_latest(self.conn,self.site,'2026-05-04')
        self.assertEqual(second['portfolio_since_inception'],'10.00%')
        self.assertEqual(second['chart']['end'],second['as_of_date'])
        self.assertEqual(second['chart']['observations'],2)
        self.assertEqual(len(second['chart']['portfolio'].split()),3)
        self.assertNotEqual(first['chart']['portfolio'],second['chart']['portfolio'])

    def test_stale_data_preserves_previous_file(self):
        write_latest(self.conn,self.site)
        previous=self.path.read_bytes()
        with self.assertRaises(SystemExit): write_latest(self.conn,self.site,'2026-05-04')
        self.assertEqual(previous,self.path.read_bytes())

    def test_invalid_chart_preserves_previous_file(self):
        write_latest(self.conn,self.site)
        previous=self.path.read_bytes()
        self.conn.execute('UPDATE fact_performance_paths_daily SET equity_index=NULL')
        with self.assertRaises(SystemExit): write_latest(self.conn,self.site)
        self.assertEqual(previous,self.path.read_bytes())

    def test_repeated_export_does_not_create_daily_noise(self):
        write_latest(self.conn,self.site)
        previous=self.path.read_bytes()
        write_latest(self.conn,self.site)
        self.assertEqual(previous,self.path.read_bytes())


if __name__=='__main__': unittest.main()
