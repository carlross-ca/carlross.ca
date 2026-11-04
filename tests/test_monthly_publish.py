"""Exercise retry recovery and frozen-report behavior without network or a database."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import date, timedelta

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/publish_previous_month_pdf.sh'

class MonthlyPublishTests(unittest.TestCase):
    def test_generation_failure_then_push_failure_then_success(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            for name in ('bin', 'scripts', 'data', 'static/reports/performance', 'content/performance'):
                (site / name).mkdir(parents=True)
            git = site / 'bin/git'
            git.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$SITE/git.log"
case "$1" in
  diff) test -f "$SITE/committed" ;;
  commit) touch "$SITE/committed" ;;
  push) test ! -f "$SITE/fail-push" ;;
esac
''')
            git.chmod(0o755)
            exporter = site / 'scripts/export_performance_pdf.py'
            exporter.write_text('''from pathlib import Path
import json
from datetime import date, timedelta
p=Path('.')
with (p/'exports').open('a') as f: f.write('attempt\\n')
if (p/'fail-export').exists(): raise SystemExit(1)
previous=date.today().replace(day=1)-timedelta(days=1)
(p/'static/reports/performance/test.pdf').write_bytes(b'frozen PDF')
(p/'data/performance_records.json').write_text(json.dumps([{'as_of_date':str(previous),'pdf_url':'/reports/performance/test.pdf'}]))
''')
            env = dict(os.environ, SITE=str(site), DB='unused', PATH=str(site/'bin')+os.pathsep+os.environ['PATH'])
            def run():
                return subprocess.run(['bash', str(SCRIPT)], env=env, capture_output=True).returncode
            (site/'fail-export').touch()
            self.assertNotEqual(run(), 0)
            self.assertNotIn('push origin main', (site/'git.log').read_text())
            (site/'fail-export').unlink()
            (site/'fail-push').touch()
            self.assertNotEqual(run(), 0)
            pdf = site/'static/reports/performance/test.pdf'
            modified = pdf.stat().st_mtime_ns
            (site/'fail-push').unlink()
            self.assertEqual(run(), 0)
            self.assertEqual(pdf.stat().st_mtime_ns, modified)
            self.assertEqual((site/'exports').read_text().count('attempt'), 2)
            self.assertEqual((site/'git.log').read_text().count('push origin main'), 2)
            pdf.unlink()
            self.assertEqual(run(), 0)
            self.assertTrue(pdf.exists())

if __name__ == '__main__':
    unittest.main()
