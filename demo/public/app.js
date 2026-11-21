import {
  $,
  $$,
  esc,
  load,
  save,
  draw,
  modal,
  notify,
  download,
  tabs,
  scope,
  access,
  wireAccess,
} from "./core.js";
import { conversations, campaigns } from "./data.js";
const criteria = [
  ["tone", "Respectful tone"],
  ["resolution", "Resolution"],
  ["close", "Closing"],
];
const valid = (value) =>
  value &&
  typeof value === "object" &&
  !Array.isArray(value) &&
  Object.entries(value).every(
    ([id, r]) =>
      conversations.some((c) => c.id === id) &&
      r &&
      criteria.every(([k]) => ["meets", "needs"].includes(r[k])) &&
      typeof r.note === "string" &&
      r.note.length <= 2000,
  );
let reviews = load("jev", {}, valid),
  drafts = load(
    "jev-drafts",
    {},
    (v) =>
      v &&
      typeof v === "object" &&
      !Array.isArray(v) &&
      Object.entries(v).every(
        ([id, r]) =>
          conversations.some((c) => c.id === id) &&
          r &&
          criteria.every(([k]) => ["", "meets", "needs"].includes(r[k])) &&
          typeof r.note === "string" &&
          r.note.length <= 2000,
      ),
  ),
  selected = "MINI-2",
  campaign = "all",
  status = "all",
  query = "",
  view = "review",
  undo = null;
const persist = () => save("jev", reviews);
function csvCell(value) {
  const text = String(value ?? "");
  return (
    '"' +
    (/^[=+@\-\t\r]/.test(text) ? "'" + text : text).replaceAll('"', '""') +
    '"'
  );
}
function exportReviews() {
  const rows = [
    [
      "Conversation",
      "Agent",
      "Campaign",
      "Tone",
      "Resolution",
      "Closing",
      "Evidence note",
    ],
    ...conversations
      .filter((c) => reviews[c.id])
      .map((c) => {
        const r = reviews[c.id];
        return [
          c.id,
          c.agent,
          campaigns[c.campaign],
          r.tone,
          r.resolution,
          r.close,
          r.note,
        ];
      }),
  ];
  download(
    "jev-reviews.csv",
    rows.map((row) => row.map(csvCell).join(",")).join("\r\n"),
    "text/csv",
  );
}
function render() {
  const visible = conversations.filter(
    (c) =>
      (campaign === "all" || campaign === c.campaign) &&
      (status === "all" ||
        (status === "reviewed") === Boolean(reviews[c.id])) &&
      `${c.id} ${c.agent} ${campaigns[c.campaign]} ${c.turns.flat().join(" ")}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const reviewed = Object.keys(reviews).length;
  draw(
    `<div class="jev-shell"><header class="jev-header"><a href="./" class="jev-brand">JEV<span> / </span>Review index</a><span class="jev-collection">Conversations [03]</span>${access()}</header>${tabs(
      [
        ["review", "Review conversations"],
        ["report", "Review report"],
      ],
      view,
    )}<nav class="jev-filters" aria-label="Campaign filter">${[["all", "All campaigns"], ...Object.entries(campaigns)].map(([id, title]) => `<button data-campaign="${id}" aria-pressed="${campaign === id}"><span aria-hidden="true">[${campaign === id ? "×" : " "}]</span> ${title}</button>`).join("")}</nav><div class="jev-tools"><label>Search conversations<input id="conversation-search" type="search" value="${esc(query)}" placeholder="Agent, phrase or campaign"></label><label>Review status<select id="review-status"><option value="all" ${status === "all" ? "selected" : ""}>All conversations</option><option value="pending" ${status === "pending" ? "selected" : ""}>To review</option><option value="reviewed" ${status === "reviewed" ? "selected" : ""}>Reviewed</option></select></label><button class="text-button" data-export ${!reviewed ? "disabled" : ""}>Export reviews ↓</button></div><div class="jev-scope"><span>Authored conversations · English adaptations</span><span>${reviewed} of 3 reviewed in this browser</span></div><main id="main" class="jev-index">${view === "report" ? report(visible) : visible.length ? visible.map((c) => row(c)).join("") : '<div class="empty"><h2>No conversations match.</h2><p>Change the search or reset the filters.</p><button class="text-button" data-reset>Reset filters</button></div>'}</main><footer class="review-footer"><span>JEV Contact Center QA</span><span>${scope}</span></footer></div>`,
    () => {
      $$("[data-tab]").forEach(
        (b) =>
          (b.onclick = () => {
            view = b.dataset.tab;
            render();
          }),
      );
      $$("[data-campaign]").forEach(
        (b) =>
          (b.onclick = () => {
            campaign = b.dataset.campaign;
            selected = conversations.find(
              (c) => campaign === "all" || c.campaign === campaign,
            )?.id;
            render();
          }),
      );
      $("#review-status").onchange = (e) => {
        status = e.target.value;
        render();
      };
      $("#conversation-search").oninput = (e) => {
        const cursor = e.target.selectionStart;
        query = e.target.value;
        render();
        $("#conversation-search").setSelectionRange(cursor, cursor);
      };
      $("[data-reset]")?.addEventListener("click", () => {
        campaign = "all";
        status = "all";
        query = "";
        render();
      });
      $$("[data-case]").forEach(
        (b) =>
          (b.onclick = () => {
            selected = selected === b.dataset.case ? null : b.dataset.case;
            render();
          }),
      );
      $$("[data-open-review]").forEach(
        (b) =>
          (b.onclick = () => {
            selected = b.dataset.openReview;
            view = "review";
            render();
          }),
      );
      $("[data-export]").onclick = exportReviews;
      $("#review-form")?.addEventListener("input", (e) => {
        drafts[selected] = Object.fromEntries(new FormData(e.currentTarget));
        save("jev-drafts", drafts);
      });
      $("#review-form")?.addEventListener("change", (e) => {
        drafts[selected] = Object.fromEntries(new FormData(e.currentTarget));
        save("jev-drafts", drafts);
      });
      $("#review-form")?.addEventListener("submit", (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.currentTarget));
        if (!criteria.every(([id]) => data[id])) {
          notify("Rate all three criteria before saving.", true);
          return;
        }
        if (
          Object.values(data).includes("needs") &&
          data.note.trim().length < 10
        ) {
          $("#review-note").setAttribute("aria-invalid", "true");
          $("#review-note").focus();
          notify("Add a short evidence note explaining what needs work.", true);
          return;
        }
        const next = {
          ...reviews,
          [selected]: { ...data, note: data.note.trim() },
        };
        if (save("jev", next)) {
          reviews = next;
          delete drafts[selected];
          save("jev-drafts", drafts);
          render();
          notify("Review saved in this browser.");
        }
      });
      $("[data-clear-review]")?.addEventListener("click", () => {
        undo = { id: selected, value: reviews[selected] };
        delete drafts[selected];
        save("jev-drafts", drafts);
        delete reviews[selected];
        if (persist()) {
          render();
          notify("Review cleared. You can undo this change.");
        }
      });
      $("[data-undo-review]")?.addEventListener("click", () => {
        if (undo) {
          reviews[undo.id] = undo.value;
          undo = null;
          persist();
          render();
          notify("Review restored.");
        }
      });
      wireAccess(
        "jev",
        () => reviews,
        (data) => {
          if (!valid(data))
            throw new Error(
              "That workspace is not a compatible review collection.",
            );
          reviews = data;
          persist();
          render();
        },
      );
    },
  );
}
function row(c) {
  const active = selected === c.id,
    r = drafts[c.id] || reviews[c.id];
  return `<article class="jev-case ${active ? "selected" : ""}"><button class="jev-case-heading" data-case="${c.id}" aria-expanded="${active}"><span class="jev-meta"><span>${c.id}</span><span>${c.date}</span><span>${campaigns[c.campaign]}</span></span><span class="jev-agent">${esc(c.agent)}</span><span class="jev-case-state">${r ? "Reviewed locally" : "To review"}<span class="case-toggle" aria-hidden="true">${active ? "−" : "+"}</span></span></button>${active ? `<div class="jev-case-body"><section class="jev-conversation" aria-label="Selected conversation"><div class="jev-quote">“${esc(c.turns[c.highlight][1])}”</div><div class="jev-transcript">${c.turns.map(([speaker, text], i) => `<p><span class="mono">${String(i + 1).padStart(2, "0")} / ${speaker.toUpperCase()}</span><span>${esc(text)}</span></p>`).join("")}</div><button class="text-button transcript-link" data-full-transcript="${c.id}">Read full conversation ↗</button></section><form class="jev-scorecard" id="review-form"><h2>Your review</h2><p class="scorecard-note">Use the conversation as evidence.</p>${criteria.map(([id, label]) => `<label class="jev-rating"><span>${label}</span><select name="${id}" aria-label="${label}"><option value="">Unreviewed</option><option value="meets" ${r?.[id] === "meets" ? "selected" : ""}>Meets criterion</option><option value="needs" ${r?.[id] === "needs" ? "selected" : ""}>Needs work</option></select></label>`).join("")}<label class="jev-note-label" for="review-note">Evidence or comment</label><textarea id="review-note" name="note" maxlength="2000" placeholder="Quote the words that support your decision.">${esc(r?.note || "")}</textarea><button class="jev-save" type="submit">Save review ↗</button>${r ? '<button type="button" class="text-button" data-clear-review>Clear this review</button>' : ""}${undo ? '<button type="button" class="text-button" data-undo-review>Undo cleared review</button>' : ""}</form></div>` : ""}</article>`;
}
function report(visible) {
  return `<section class="review-report"><h1>Decisions, with evidence.</h1><p>These are your reviews of authored examples. No automated model scores are included.</p>${visible.length ? `<div class="table-scroll"><table><caption>Conversation review report</caption><thead><tr><th>Conversation</th><th>Agent</th>${criteria.map(([, title]) => `<th>${title}</th>`).join("")}<th>Evidence note</th></tr></thead><tbody>${visible.map((c) => `<tr><th><button data-open-review="${c.id}">${c.id} ↗</button></th><td>${esc(c.agent)}</td>${criteria.map(([id]) => `<td>${reviews[c.id]?.[id] === "meets" ? "Meets criterion" : reviews[c.id]?.[id] === "needs" ? "Needs work" : "Unreviewed"}</td>`).join("")}<td>${esc(reviews[c.id]?.note || "—")}</td></tr>`).join("")}</tbody></table></div>` : "<p>No conversations match the current filters.</p>"}</section>`;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-full-transcript]");
  if (!b) return;
  const c = conversations.find((c) => c.id === b.dataset.fullTranscript);
  modal(
    `${c.id} · ${c.agent}`,
    c.turns
      .map(([s, t]) => `<p><strong>${esc(s)}</strong></p><p>${esc(t)}</p><br>`)
      .join(""),
  );
});
render();
