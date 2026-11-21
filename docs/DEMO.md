# Contact-center report workflow

![Original walkthrough screenshot](images/demo.png)

## Reproduce

Python 3.12 or 3.13; standard library for this offline path. Live providers require separate configuration.

Use an isolated checkout and environment.

```bash
python -m unittest discover -s tests -v
python tools/create_demo.py --runs 5
```

Serve the generated files locally:

```bash
python -m http.server 8000 --bind 127.0.0.1 --directory docs/examples
```

Open `http://127.0.0.1:8000/walkthrough.html`.

## What the example establishes

The actual audit and report CLI processes the committed mini CSV with --fake and publishes all three campaign reports through an index. The earlier sample-report.html remains available. Scores, tokens, and displayed prices are illustrative FakeJev output; the recorded timing samples measure actual local CLI execution. They do not measure model quality, provider latency, customer impact, or actual provider charges. See the [measured case study](CASE-STUDY.md) and its raw evidence. The original single-campaign screenshot below remains a valid example of one generated report; the new index links all campaigns.

The screenshot records the visible output of this workflow. It does not establish behavior outside the stated scope. Generated evidence and source examples are preserved alongside the walkthrough; current CI runs provide commit-specific checks.
