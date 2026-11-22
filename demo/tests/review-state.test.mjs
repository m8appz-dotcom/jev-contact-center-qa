import test from "node:test";
import assert from "node:assert/strict";
import { readReviewWorkspace } from "../public/review-state.js";

test("workspace round-trip retains unfinished ratings and evidence alongside completed reviews", () => {
  const reviews = {
    "MINI-1": {
      tone: "meets",
      resolution: "needs",
      close: "meets",
      note: "The question remains unanswered.",
    },
  };
  const drafts = {
    "MINI-2": {
      tone: "needs",
      resolution: "",
      close: "",
      note: "Evidence still being reviewed.",
    },
  };
  const restored = readReviewWorkspace(
    JSON.parse(JSON.stringify({ version: 1, reviews, drafts })),
  );
  assert.deepEqual(restored, { reviews, drafts });
  restored.drafts["MINI-2"].note = "Edited after restore";
  assert.equal(drafts["MINI-2"].note, "Evidence still being reviewed.");
});

test("legacy review-only backups remain readable and malformed drafts are rejected", () => {
  const legacy = {
    "MINI-3": { tone: "meets", resolution: "meets", close: "meets", note: "" },
  };
  assert.deepEqual(readReviewWorkspace(legacy), {
    reviews: legacy,
    drafts: {},
  });
  for (const value of [
    null,
    { version: 2, reviews: {}, drafts: {} },
    { version: 1, reviews: {}, drafts: { "MINI-4": {} } },
    {
      version: 1,
      reviews: {},
      drafts: {
        "MINI-1": {
          tone: "",
          resolution: "",
          close: "",
          note: "x".repeat(2001),
        },
      },
    },
  ])
    assert.throws(
      () => readReviewWorkspace(value),
      /compatible review collection/,
    );
});
