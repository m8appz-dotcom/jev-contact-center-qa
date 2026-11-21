"""Exercise the actual fixture CLI and all published campaign links."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('portfolio_demo', ROOT/'tools/create_demo.py')
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)

class DemoTests(unittest.TestCase):
    def test_all_campaign_reports_and_measured_evidence_are_published(self):
        source_before = demo.SOURCE.read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'output'
            target.mkdir()
            (target/'unrelated.txt').write_text('preserve this work', encoding='utf-8')
            evidence = demo.generate_demo(target, runs=2)
            self.assertEqual(evidence['interactions'], 3)
            self.assertEqual(set(evidence['campaigns']), {'telco_hogar','banca_tarjetas','seguros_salud'})
            self.assertEqual(len(evidence['reportFiles']), 3)
            page = (target/'walkthrough.html').read_text(encoding='utf-8')
            for href in re.findall(r'href="([^"]+)"', page):
                self.assertTrue((target/href).is_file(), href)
            for name in evidence['reportFiles']:
                report = (target/name).read_text(encoding='utf-8')
                self.assertIn('FakeJev', report)
                self.assertIn('No live provider was called or billed', report)
            self.assertEqual((target/'sample-report.html').read_bytes(), (target/evidence['reportFiles'][0]).read_bytes())
            self.assertEqual((target/'unrelated.txt').read_text(encoding='utf-8'), 'preserve this work')
            self.assertEqual(json.loads((target/'evidence.json').read_text(encoding='utf-8'))['measurement']['runs'], 2)
            self.assertEqual(evidence['sourceSha256'], hashlib.sha256(source_before).hexdigest())
            self.assertEqual(evidence['liveProviderCalls'], 0)
            self.assertFalse(evidence['qualityBenchmark'])
            self.assertFalse(evidence['customerImpactClaimed'])
            self.assertTrue(all(s['totalSeconds'] > 0 for s in evidence['measurement']['samples']))
            self.assertLessEqual(evidence['measurement']['minSeconds'], evidence['measurement']['medianSeconds'])
            self.assertLessEqual(evidence['measurement']['medianSeconds'], evidence['measurement']['maxSeconds'])
        self.assertEqual(demo.SOURCE.read_bytes(), source_before)

    def test_invalid_run_counts_and_fixture_destination_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            for runs in [0,21]:
                with self.assertRaises(ValueError):
                    demo.generate_demo(Path(temp), runs=runs)
        with self.assertRaises(ValueError):
            demo.generate_demo(demo.SOURCE.parent, runs=1)

if __name__ == '__main__':
    unittest.main()
