"""Publish every authored-fixture campaign and measure the real offline CLI flow."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import hashlib
import html
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tests/fixtures/mini.csv'
NOTICE = '<section style="padding:20px 24px;background:#f1f5f9;color:#172033;border-radius:8px;margin:16px 0"><strong>Offline workflow example</strong><p>Authored sample conversations. FakeJev scores, tokens, and displayed prices illustrate the reporting workflow. No live provider was called or billed; this is not a model-quality measurement.</p></section>'

def generate_demo(target: Path, runs: int = 3) -> dict:
    if not 1 <= runs <= 20:
        raise ValueError('Use between 1 and 20 offline measurement runs')
    target = Path(target)
    if SOURCE.resolve().is_relative_to(target.resolve()):
        raise ValueError('Choose a separate output directory, away from source fixtures')
    target.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    timings, rows, report_names = [], [], []
    for index in range(runs):
        with tempfile.TemporaryDirectory(prefix='jev-offline-demo-') as temp:
            work = Path(temp)
            results = work / 'results.csv'
            commands = [
                [sys.executable, '-m', 'jevqa', 'auditar', 'tests/fixtures/mini.csv', '--salida', str(results), '--fake'],
                [sys.executable, '-m', 'jevqa', 'informe', str(results), '--salida', str(work), '--fake'],
            ]
            elapsed = []
            for command in commands:
                start = time.perf_counter()
                subprocess.run(command, cwd=ROOT, env={**os.environ, 'PYTHONUTF8':'1', 'PYTHONIOENCODING':'utf-8'}, check=True, capture_output=True, text=True, encoding='utf-8')
                elapsed.append(time.perf_counter() - start)
            timings.append({'auditSeconds':elapsed[0], 'reportSeconds':elapsed[1], 'totalSeconds':sum(elapsed)})
            reports = sorted(work.glob('informe_*.html'))
            with results.open(encoding='utf-8-sig', newline='') as stream:
                current_rows = list(csv.DictReader(stream))
            campaigns = Counter(row['campaña'] for row in current_rows)
            if not reports or len(reports) != len(campaigns):
                raise RuntimeError('The CLI did not produce one report for every campaign')
            if index == 0:
                rows = current_rows
                report_names = [p.name for p in reports]
                for report in reports:
                    body = report.read_text(encoding='utf-8')
                    if '<body>' not in body:
                        raise RuntimeError('Unexpected application report structure')
                    (target / report.name).write_text(body.replace('<body>', '<body>' + NOTICE, 1), encoding='utf-8')
                shutil.copy2(target / report_names[0], target / 'sample-report.html')
                shutil.copy2(results, target / 'sample-results.csv')
            elif len(current_rows) != len(rows) or [p.name for p in reports] != report_names:
                raise RuntimeError('Fixture output counts changed between measurement runs')
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError('The source fixture changed during the walkthrough')
    campaigns = Counter(row['campaña'] for row in rows)
    totals = [r['totalSeconds'] for r in timings]
    evidence = {
        'mode':'offline_fake_client', 'source':'tests/fixtures/mini.csv', 'sourceSha256':source_hash,
        'interactions':len(rows), 'campaigns':dict(sorted(campaigns.items())), 'reportFiles':report_names,
        'applicationGeneratedReport':True, 'liveProviderCalls':0, 'billedProviderCostUsd':0,
        'qualityBenchmark':False, 'customerImpactClaimed':False,
        'measurement':{'runs':runs, 'python':platform.python_version(), 'system':platform.system(),
            'samples':timings, 'medianSeconds':statistics.median(totals), 'minSeconds':min(totals), 'maxSeconds':max(totals),
            'scope':'Actual local CLI startup, fake audit, CSV writing, and HTML reports; excludes live inference and customer operations.'},
    }
    (target / 'evidence.json').write_text(json.dumps(evidence, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    links = ''.join(f'<li><a href="{html.escape(name, quote=True)}">{html.escape(name.removeprefix("informe_").removesuffix(".html"))}</a></li>' for name in report_names)
    report = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>JEV campaign workflow measurement</title><style>body{margin:0;background:#f5f7fa;color:#172033;font:17px/1.6 system-ui,sans-serif}main{max-width:1000px;margin:42px auto;padding:30px}h1{font-size:38px;line-height:1.2}.panel{background:white;border:1px solid #dce2e9;border-radius:12px;padding:24px;margin:24px 0}.stats{display:flex;gap:40px;flex-wrap:wrap}b{display:block;font-size:28px}a{color:#1753aa}.muted{color:#526174}</style><main><p class="muted">JEV Contact Center QA · Actual offline CLI measurement</p><h1>Every campaign, with reproducible execution evidence</h1><p>Three authored interactions exercise the actual audit and HTML report commands with FakeJev. Scores and displayed prices are illustrative; no live model is called or billed.</p>'''
    report += f'<section class="panel stats"><div><b>{len(rows)}</b>fixture interactions</div><div><b>{len(campaigns)}</b>campaign reports</div><div><b>{runs}</b>measured CLI runs</div><div><b>{statistics.median(totals):.3f} s</b>median local duration</div></section>'
    report += '<section class="panel"><h2>Open the actual campaign reports</h2><ul>'+links+'</ul><p><a href="sample-results.csv">Inspect the generated CSV</a> · <a href="evidence.json">Inspect inputs, timings, and scope</a></p></section>'
    report += f'<p class="muted">Observed range: {min(totals):.3f}–{max(totals):.3f} seconds on {html.escape(platform.system())}, Python {html.escape(platform.python_version())}. These measurements describe local orchestration, including CLI startup and file output. They do not measure inference quality, provider latency, customer savings, or production throughput.</p></main></html>'
    (target / 'walkthrough.html').write_text(report, encoding='utf-8')
    return evidence

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'docs/examples')
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(generate_demo(args.output, args.runs), ensure_ascii=False))

if __name__ == '__main__':
    main()
