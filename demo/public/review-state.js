import { conversations } from "./data.js";

export const criteria = [
  ["tone", "Respectful tone"],
  ["resolution", "Resolution"],
  ["close", "Closing"],
];

export function validReviews(value, incomplete = false) {
  const choices = incomplete ? ["", "meets", "needs"] : ["meets", "needs"];
  return Boolean(
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.entries(value).every(
      ([id, review]) =>
        conversations.some((c) => c.id === id) &&
        review &&
        criteria.every(([key]) => choices.includes(review[key])) &&
        typeof review.note === "string" &&
        review.note.length <= 2000,
    ),
  );
}

export function readReviewWorkspace(value) {
  // Versionless exports from the original demo contained completed reviews only.
  if (validReviews(value))
    return { reviews: structuredClone(value), drafts: {} };
  if (
    value?.version === 1 &&
    validReviews(value.reviews) &&
    validReviews(value.drafts, true)
  )
    return {
      reviews: structuredClone(value.reviews),
      drafts: structuredClone(value.drafts),
    };
  throw new Error("That workspace is not a compatible review collection.");
}
