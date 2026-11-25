import { h, pill, table } from "../dom.js";
import { showLink, showPerson } from "../drawer.js";
import { LINK_TYPES, STATUS_TONE, ist, pct, signed, words } from "../format.js";
import { state } from "../state.js";

export function renderLeads(root) {
  const b = state.bundle;
  root.append(
    h("h1", { text: "Next requests" }),
    h("p", {
      class: "lead",
      text: "Evidence requests ranked by value per day: how much each would separate the leading explanations, fill a gap in the reconstruction, or reach money that can still be frozen, divided by how long it takes to obtain.",
    }),
    b.leads.length
      ? table(
          [
            { label: "#", num: true, key: "rank" },
            { label: "Request", render: (r) => h("strong", { text: r.title }) },
            {
              label: "Why",
              render: (r) =>
                h("div", null, r.why, r.reasons.length ? h("div", { class: "faint", text: r.reasons.join("; ") }) : null),
            },
            { label: "Days", num: true, key: "days" },
            { label: "Information (bits)", num: true, render: (r) => r.eig_bits.toFixed(3) },
            { label: "Value per day", num: true, render: (r) => r.value_per_day.toFixed(3) },
          ],
          b.leads,
        )
      : h("div", { class: "empty", text: "No further requests suggested." }),
    b.fragility.available
      ? h(
          "div",
          { class: "card", style: { marginTop: "16px" } },
          h("h2", { text: "What the conclusion rests on" }),
          h("p", { text: `${b.fragility.message}.` }),
          table(
            [
              { label: "Support", render: (r) => r.label },
              { label: "Weight", num: true, render: (r) => signed(r.w, 2) },
              {
                label: "",
                render: (r) =>
                  r.link_id
                    ? h("button", { class: "btn light small", type: "button", onclick: () => showLink(r.link_id), text: "Open" })
                    : null,
              },
            ],
            b.fragility.rests_on,
          ),
          h("p", {
            class: "faint",
            text: "These are the items a defence would challenge first. Strengthen them with independent records before relying on the conclusion.",
          }),
        )
      : null,
  );
}

export function renderPeople(root) {
  const b = state.bundle;
  root.append(
    h("h1", { text: "People" }),
    h("p", {
      class: "lead",
      text: "Each person is a hypothesis: identifiers grouped only where tested links tie them together. Common names alone never merge people.",
    }),
    h(
      "div",
      { class: "grid halves" },
      b.people.map((person) =>
        h(
          "div",
          { class: "card person-card" },
          h(
            "div",
            { class: "spread" },
            h(
              "div",
              null,
              h("strong", { text: `${person.id} ${person.names[0] || person.label}` }),
              person.names.length > 1
                ? h("div", { class: "faint", text: `Also registered as ${person.names.slice(1).join(", ")}` })
                : null,
            ),
            h("button", { class: "btn light small", type: "button", onclick: () => showPerson(person.id), text: "Details" }),
          ),
          h(
            "div",
            { class: "row", style: { marginTop: "6px" } },
            person.is_seed ? pill("Complainant", "teal") : null,
            person.roles.slice(0, 3).map((r) => pill(r)),
            person.cleared.length ? pill("Cleared at cash-out", "good") : null,
          ),
          h(
            "div",
            { class: "members" },
            person.members
              .slice(0, 8)
              .map((m) =>
                h(
                  "div",
                  { class: "member" },
                  h("span", { class: "faint", text: m.kind_label }),
                  h("span", { class: "mono", text: m.label }),
                  m.via ? h("span", { class: "faint", text: `W ${signed(m.score, 1)}` }) : h("span"),
                ),
              ),
          ),
          person.members.length > 8 ? h("div", { class: "faint", text: `${person.members.length - 8} more identifiers` }) : null,
          person.indicators.length
            ? h(
                "div",
                { class: "indicators" },
                person.indicators.map((i) => pill(words(i.name), i.weight >= 0 ? "warn" : "good")),
              )
            : null,
        ),
      ),
    ),
  );
}

export function renderLinks(root) {
  const b = state.bundle;
  const filters = { type: "all", status: "active" };
  const holder = h("div");
  const typeSelect = h(
    "select",
    null,
    h("option", { value: "all", text: "All types" }),
    Object.entries(LINK_TYPES).map(([k, v]) => h("option", { value: k, text: v })),
  );
  const statusSelect = h(
    "select",
    null,
    h("option", { value: "active", text: "Inferred and confirmed" }),
    h("option", { value: "all", text: "All statuses" }),
    h("option", { value: "candidate", text: "Candidates" }),
    h("option", { value: "rejected", text: "Rejected" }),
  );
  const draw = () => {
    holder.replaceChildren();
    const rows = b.links.filter(
      (l) =>
        (filters.type === "all" || l.type === filters.type) &&
        (filters.status === "all" ||
          (filters.status === "active" ? ["inferred", "confirmed"].includes(l.status) : l.status === filters.status)),
    );
    holder.append(
      h("p", { class: "faint", text: `${rows.length} links` }),
      table(
        [
          { label: "Type", render: (r) => LINK_TYPES[r.type] || r.type },
          { label: "Claim", render: (r) => r.claim },
          { label: "W", num: true, render: (r) => signed(r.w, 2) },
          { label: "Strength", render: (r) => r.verbal },
          {
            label: "Posterior",
            num: true,
            render: (r) => (r.posterior !== null && r.posterior !== undefined ? pct(r.posterior, 0) : ""),
          },
          { label: "Status", render: (r) => pill(r.status, STATUS_TONE[r.status]) },
          { label: "Sources", num: true, render: (r) => new Set(r.sources).size },
        ],
        rows.slice(0, 400),
        (row) => showLink(row.link_id),
      ),
    );
  };
  typeSelect.addEventListener("change", () => {
    filters.type = typeSelect.value;
    draw();
  });
  statusSelect.addEventListener("change", () => {
    filters.status = statusSelect.value;
    draw();
  });
  root.append(
    h("h1", { text: "Tested links" }),
    h("p", {
      class: "lead",
      text: "Every cross-source link is a likelihood ratio against coincidence, built from time, place, attribute and rarity terms. A link is accepted at W of 2 or more with at least two independent sources; the investigator confirms or rejects.",
    }),
    h("div", { class: "toolbar" }, h("label", null, "Type", typeSelect), h("label", null, "Status", statusSelect)),
    holder,
  );
  draw();
}

export function renderEvidence(root) {
  const ev = state.bundle.evidence;
  const ledger = ev.ledger;
  root.append(
    h("h1", { text: "Evidence and custody" }),
    h("p", {
      class: "lead",
      text: "Every file is hashed on intake and every analysis, investigator decision and report export is written to a hash-chained ledger. Clock corrections are listed per file.",
    }),
    h(
      "div",
      { class: "card" },
      h(
        "div",
        { class: "spread" },
        h(
          "div",
          null,
          h("h2", { text: "Custody ledger" }),
          h("div", { class: "small", text: ledger.message }),
          h("div", { class: "faint mono", text: `Head ${ledger.head}` }),
        ),
        pill(
          ledger.ok ? `Chain verified, ${ledger.entries} entries` : `Broken at entry ${ledger.broken_at}`,
          ledger.ok ? "good" : "bad",
        ),
      ),
    ),
    ev.media.length
      ? h(
          "div",
          { class: "card", style: { marginTop: "14px" } },
          h("h2", { text: "Media integrity" }),
          table(
            [
              { label: "File", render: (r) => r.file },
              { label: "Result", render: (r) => pill(r.status, r.status === "verified" ? "good" : "bad") },
              { label: "Detail", render: (r) => r.message },
            ],
            ev.media,
          ),
        )
      : null,
    h("h2", { style: { marginTop: "18px" }, text: "Evidence files" }),
    table(
      [
        { label: "ID", key: "evidence_id" },
        { label: "File", render: (r) => h("div", null, r.file, h("div", { class: "faint", text: r.label })) },
        { label: "Records", num: true, key: "records" },
        { label: "SHA-256", render: (r) => h("span", { class: "mono", title: r.sha256, text: `${r.sha256.slice(0, 16)}...` }) },
        {
          label: "Clock",
          render: (r) =>
            r.clock
              ? h(
                  "div",
                  null,
                  pill(words(r.clock.method), r.clock.method === "anchor_vote" ? "warn" : "grey"),
                  h("div", { class: "faint", text: r.clock.note }),
                )
              : "",
        },
        {
          label: "Integrity",
          render: (r) =>
            h(
              "div",
              { class: "row" },
              r.integrity.length ? r.integrity.map((i) => pill(i.message, "bad")) : pill("no issue", "good"),
              r.warnings.length
                ? h("span", {
                    class: "pill warn",
                    title: r.warnings.slice(0, 8).join("\n"),
                    text: `${r.warnings.length} row${r.warnings.length === 1 ? "" : "s"} not read`,
                  })
                : null,
            ),
        },
      ],
      ev.items,
    ),
    h("h2", { style: { marginTop: "18px" }, text: "Recent ledger entries" }),
    table(
      [
        { label: "#", num: true, key: "seq" },
        { label: "Time (IST)", render: (r) => ist(r.time) },
        { label: "Type", render: (r) => words(r.type) },
        { label: "Detail", render: (r) => h("span", { class: "mono small", text: JSON.stringify(r.payload).slice(0, 140) }) },
        { label: "Hash", render: (r) => h("span", { class: "mono", text: r.hash.slice(0, 12) }) },
      ],
      [...ev.ledger_entries].reverse(),
    ),
  );
}
