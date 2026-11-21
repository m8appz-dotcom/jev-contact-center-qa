# Complete campaign reporting: a measured offline case

## Problem and change

The prior walkthrough ran three authored interactions across three campaigns but published only the first HTML report. A reviewer had to reproduce the CLI to inspect the other two campaigns.

The new walkthrough publishes an index and all three actual campaign reports, preserves the earlier sample-report entry point, and records repeatable CLI measurements with the input identity and validation scope. The source fixture remains unchanged.

## Responsibility and review

Kenneth Yepez defined the acceptance criteria and directed the integration, validation, and delivery. AI coding agents implemented the change. The work is tracked in [issue #3](https://github.com/m8appz-dotcom/jev-contact-center-qa/issues/3) and delivered through the repository's reviewed PR workflow. Automated review is identified as AI; no additional human reviewer or customer outcome is implied.

## Observed run

Snapshot: 21 November 2026, Windows, Python 3.13.17.

| Measure | Observed result |
|---|---|
| Authored interactions per run | 3 |
| Campaign reports linked from the public example | 3, previously 1 |
| Repeated actual CLI executions | 5 |
| Median audit-plus-report duration, including process startup | 0.406 seconds |
| Observed minimum–maximum | 0.399–0.414 seconds |
| Live provider calls and billed provider cost | 0 |

[Input identity and raw timing samples](examples/evidence.json) accompany the outputs. These are actual local workflow measurements using FakeJev; they do not measure provider inference, model accuracy, production throughput, customer adoption, or business savings. Timings vary by hardware and environment, and CI artifacts regenerate their own measurements. No speed improvement over the previous implementation is claimed.

## Reproduce and inspect

```bash
python -m unittest discover -s tests -v
python tools/create_demo.py --runs 5
python -m http.server 8000 --bind 127.0.0.1 --directory docs/examples
```

Open http://127.0.0.1:8000/walkthrough.html. Follow each campaign link and inspect the CSV/evidence links. The banner labels FakeJev scores, tokens, and displayed prices as illustrative; no provider is called or billed.

The regression checks run the actual CLI in a temporary directory, verify every generated link and all campaign reports, preserve unrelated output and source fixtures, and reject invalid run counts or fixture-root output.

## Next measurement

A separately authorized pilot with real model calls and independently labeled cases would be needed to measure failure recall, reviewer workload, provider latency, and operating cost. The [existing model evaluation](../data/eval/informe.md) retains its limitations; this workflow example does not replace it.
