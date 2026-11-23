import test from "node:test";
import assert from "node:assert/strict";
import { readRecordedAssessment } from "../public/recorded-assessment.js";

const snapshot = () => ({
  version: 1,
  assessments: {
    "MINI-1": {
      conversation: "MINI-1",
      model: "jev-1.14.0",
      score: 80,
      outcome: "Failed",
      needsReview: true,
      criteria: Array.from({ length: 8 }, () => ({
        label: "Identity verification",
        critical: true,
        meets: false,
        needsReview: true,
        confidence: 0.02,
      })),
    },
  },
});

test("recorded results preserve critical failure and use trusted relative files", () => {
  const data = snapshot();
  data.assessments["MINI-1"].reportUrl = "javascript:alert(1)";
  const job = readRecordedAssessment(data, "MINI-1");
  assert.equal(job.result.outcome, "Failed");
  assert.equal(job.result.score, 80);
  assert.equal(job.reportUrl, "../informe_Home_internet.html");
  assert.match(job.result.scope, /Recorded JEV assessment/);
  assert.match(job.result.scope, /No new model request/);
});

test("missing, foreign or malformed assessments fail closed", () => {
  for (const id of ["MINI-4", "__proto__", "../../private"]) {
    assert.throws(() => readRecordedAssessment(snapshot(), id));
  }
  for (const change of [
    { score: NaN },
    { outcome: "Approved" },
    { conversation: "MINI-2" },
    { criteria: [] },
    { needsReview: "false" },
  ]) {
    const data = snapshot();
    Object.assign(data.assessments["MINI-1"], change);
    assert.throws(() => readRecordedAssessment(data, "MINI-1"));
  }
});
