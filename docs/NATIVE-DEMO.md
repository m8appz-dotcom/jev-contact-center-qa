# Run the original JEV application

The Python CLI remains the application: redact a transcript batch, request one structured JEV assessment per conversation, apply the weighted rubric and produce campaign reports. The English report uses the original layout and scoring functions. The earlier local review interface remains available separately.

## Recorded connected example

[Explore the reports](https://kennethyepez.com/projects/jev-contact-center-qa) · [Input conversations](../demo/fixtures/conversations-en.csv) · [Actual results CSV](examples/live-english/results.csv) · [Execution evidence](examples/live-english/evidence.json)

On November 22, 2026, the original CLI assessed the three English conversations already used by `demo/public/data.js`. The response model was `jev-1.14.0`, using the existing `jev-latest` selection. All three requests succeeded and produced three campaign reports. Their reported input usage totals 3,404 tokens; the application's token-price calculation estimates US$0.00014297. This is an application estimate, not a billing statement.

Re-running the same audit skipped all three existing IDs, made no new provider requests and left the results CSV unchanged. Report generation reads that saved CSV and makes no provider calls.

These are authored examples, not customer calls. They have no new independent human annotations and cannot establish accuracy, failure recall or production performance. Historical Spanish evaluation limitations remain in the README and evaluation plan.

## Reproduce with the real provider

Use Python 3.12 or newer. Configure `TYPESAFE_API_KEY` privately in the process environment; never put it in a command, source file or browser. Without that credential, use the README's explicitly offline workflow instead. Do not label fake-client output as a live assessment.

```bash
python -m jevqa auditar demo/fixtures/conversations-en.csv --rubrica rubrics/support_en.json --salida .demo-state/english/results.csv --concurrencia 1 --por-minuto 20
python -m jevqa informe .demo-state/english/results.csv --rubrica rubrics/support_en.json --salida .demo-state/english/reports --note "Authored sample conversations assessed by JEV. This is a recorded workflow example, not a customer audit or an accuracy benchmark."
```

Run the first command again to exercise resumption. Existing IDs are skipped; choose a fresh output path when intentionally reevaluating them. Private run state stays under ignored `.demo-state/`. The committed public snapshot contains only the selected authored examples and their results.

## Interpret the report

- A critical failure can fail an interaction even when its numeric score exceeds 70. **Failed interactions** includes both causes.
- A passing interaction can still require human review when one or more criterion judgments have low confidence or ambiguous probabilities.
- An agent with fewer than five audited interactions stays outside the ranking.
- The report distinguishes unscored errors from scored failures; no successful assessment substitutes for a failed request.
- English report labels follow the English rubric. Existing Spanish reports and commands retain their behavior and layout.

The browser review covered all three native reports and the 390px mobile layout. Wide tables scroll within their own containers. Regression checks cover critical failure at a high numeric score, uncertainty, unscored errors and safe escaping of data and context notes. This phase does not claim a new passkey enrollment, a hosted private workspace or an independently labeled quality benchmark.
