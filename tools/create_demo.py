"""Generate a real application report using authored fixtures and FakeJev."""
from __future__ import annotations
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def main():
    target = ROOT / 'docs/examples'
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='jev-offline-demo-') as temp:
        work = Path(temp)
        results = work / 'results.csv'
        commands = [
            [sys.executable, '-m', 'jevqa', 'auditar', 'tests/fixtures/mini.csv', '--salida', str(results), '--fake'],
            [sys.executable, '-m', 'jevqa', 'informe', str(results), '--salida', str(work), '--fake'],
        ]
        for command in commands:
            subprocess.run(command, cwd=ROOT, env={**os.environ, 'PYTHONUTF8':'1', 'PYTHONIOENCODING':'utf-8'}, check=True, capture_output=True, text=True, encoding='utf-8')
        reports = sorted(work.glob('informe_*.html'))
        if not reports:
            raise RuntimeError('The application did not produce a campaign report')
        body = reports[0].read_text(encoding='utf-8')
        notice = '<section style="padding:20px 24px;background:#f1f5f9;color:#172033;border-radius:8px;margin:16px 0"><strong>Offline workflow example</strong><p>Authored sample conversations. Scores come from FakeJev and illustrate the reporting workflow; they are not model-quality measurements.</p></section>'
        if '<body>' not in body:
            raise RuntimeError('Unexpected report structure; inspect before modifying the demo output')
        body = body.replace('<body>', '<body>' + notice, 1)
        (target / 'sample-report.html').write_text(body, encoding='utf-8')
        shutil.copy2(results, target / 'sample-results.csv')
        with results.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        evidence = {'mode':'offline_fake_client', 'source':'tests/fixtures/mini.csv', 'interactions':len(rows), 'applicationGeneratedReport':True, 'liveProviderCalls':0, 'qualityBenchmark':False}
        (target / 'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(evidence))

if __name__ == '__main__':
    main()
