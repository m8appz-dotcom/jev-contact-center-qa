// The public portfolio reads recorded output; the private workspace keeps its live adapter.
export const recordedMode =
  typeof document !== "undefined" &&
  document.documentElement.dataset.assessmentMode === "recorded";

const reportFiles = Object.freeze({
  "MINI-1": "informe_Home_internet.html",
  "MINI-2": "informe_Bank_cards.html",
  "MINI-3": "informe_Health_insurance.html",
});

export function readRecordedAssessment(snapshot, id) {
  const result = snapshot?.assessments?.[id];
  if (
    !Object.hasOwn(reportFiles, id) ||
    snapshot?.version !== 1 ||
    !result ||
    result.conversation !== id ||
    !Number.isFinite(result.score) ||
    result.score < 0 ||
    result.score > 100 ||
    !["Passed", "Failed"].includes(result.outcome) ||
    typeof result.model !== "string" ||
    typeof result.needsReview !== "boolean" ||
    !Array.isArray(result.criteria) ||
    result.criteria.length !== 8 ||
    !result.criteria.every(
      (c) =>
        typeof c.label === "string" &&
        typeof c.critical === "boolean" &&
        typeof c.meets === "boolean" &&
        typeof c.needsReview === "boolean" &&
        Number.isFinite(c.confidence) &&
        c.confidence >= 0 &&
        c.confidence <= 1,
    )
  ) {
    throw Error(
      "This recorded assessment is unavailable. Open the campaign report instead.",
    );
  }
  return {
    result: {
      ...result,
      scope: `Recorded JEV assessment · ${result.model} · Authored conversation, not a customer call. No new model request is made.`,
    },
    reportUrl: "../" + reportFiles[id],
    files: [{ url: "../results.csv", name: "results.csv" }],
  };
}

export async function loadRecordedAssessment(id) {
  const response = await fetch(
    new URL("./recorded-assessments.json", import.meta.url),
  );
  if (!response.ok)
    throw Error("The recorded results could not load. Please try again.");
  return readRecordedAssessment(await response.json(), id);
}
