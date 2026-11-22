# Independent evaluation before autonomous scoring

The published Spanish run contains 40 authored synthetic conversations and one annotator. It detected 1/4 identity-verification failures and 0/2 diagnosis failures. These results do not justify autonomous scoring. The translated English rubric needs a separate evaluation.

1. Preserve the published run and its failures.
2. Use an authorized dataset with enough failing examples for each critical criterion. Document origin, consent and transcription conditions; keep personal data out of the public repository.
3. Have two actual independent annotators label cases, record disagreements and adjudicate them. Keep AI-generated labels identified as such.
4. Separate calibration and held-out cases by source conversation before changing a rubric or threshold. Freeze revisions and splits for the final comparison.
5. Report failure recall, precision, false negatives, confidence intervals, reviewer workload, latency and actual provider usage separately for Spanish and English.
6. Agree on acceptable critical-failure detection and human-review workload with the intended operator before assessing held-out results.

Keep human review in the decision process. A high aggregate agreement or offline report-generation time does not establish safe autonomous operation. Thresholds suggested by the old examples are calibration hypotheses; tuning on those same examples does not demonstrate generalization.

The repository cannot supply independent human annotation or an authorized customer pilot by itself. Until those steps and the live evaluation occur, its published status remains experimental. No new accuracy or savings figure is claimed.
