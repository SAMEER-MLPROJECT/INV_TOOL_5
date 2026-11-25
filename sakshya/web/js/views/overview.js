import { h, pill } from "../dom.js";
import { showAccount, showHypothesis, showLink, showPerson } from "../drawer.js";
import { inr, ist, pct, signed, short, words } from "../format.js";
import { crimeHypothesis, state } from "../state.js";

function unitChip(unit) {
  if (unit.kind === "person") {
    return h(
      "span",
      { class: "chip", onclick: () => showPerson(unit.id) },
      h("span", { class: "k", text: unit.id }),
      unit.names && unit.names.length ? `${unit.label} (${unit.names[0]})` : unit.label,
    );
  }
  return h(
    "span",
    { class: "chip", onclick: () => showAccount(unit.id) },
    h("span", { class: "k", text: "Account" }),
    unit.label,
  );
}

function phaseStrip(hyp) {
  return h(
    "div",
    { class: "phases" },
    hyp.phases.map((p) => {
      const tone = p.filled ? (p.order_ok ? "filled" : "order") : p.optional ? "optional" : "gap";
      return h(
        "div",
        { class: `phase ${tone}` },
        h("div", { class: "n", text: p.label }),
        h("div", {
          class: "faint",
          text: p.filled ? ist(p.t_first, true) : p.optional ? "not evidenced" : `gap, observability ${pct(p.observability)}`,
        }),
      );
    }),
  );
}

function hypothesisCard(hyp, index, all) {
  if (hyp.template === "no_offence") {
    return h(
      "div",
      { class: "hyp" },
      h(
        "div",
        { class: "hyp-head" },
        h("div", { class: "hyp-title", text: `${hyp.id} No offence (reference)` }),
        h("div", { class: "hyp-score", text: "S 0.0" }),
      ),
      h("p", {
        class: "faint",
        text: "Every event explained by ordinary activity. Other explanations are scored against this reference.",
      }),
    );
  }
  const variants = Object.entries(hyp.variant || {}).map(([role, v]) => pill(`${words(role)}: ${v}`, "warn"));
  return h(
    "div",
    { class: `hyp ${index === 0 ? "top" : ""}` },
    h(
      "div",
      { class: "hyp-head" },
      h("div", null, h("span", { class: "hyp-title", text: `${hyp.id} ${hyp.label}` }), " ", variants),
      h(
        "div",
        { class: "row" },
        h("span", { class: "hyp-score", text: `S ${signed(hyp.score, 1)}` }),
        hyp.margin_next !== null && all[index + 1]
          ? h("span", { class: "faint", text: `${signed(hyp.margin_next, 1)} over ${all[index + 1].id}` })
          : null,
        h("button", { class: "btn light small", type: "button", onclick: () => showHypothesis(hyp.id), text: "Why this score" }),
      ),
    ),
    h(
      "div",
      { class: "roles" },
      hyp.roles
        .filter((r) => r.name !== "victim")
        .map((role) => [
          h("div", { class: "r", text: role.variant ? `${role.label} (${role.variant})` : role.label }),
          h(
            "div",
            null,
            role.units.length
              ? role.units.map(unitChip)
              : h("span", { class: "faint", text: role.optional ? "not identified (optional)" : "not identified" }),
          ),
        ]),
    ),
    phaseStrip(hyp),
    hyp.gaps.length
      ? h("div", { class: "faint", style: { marginTop: "6px" }, text: `Gaps: ${hyp.gaps.map(words).join(", ")}` })
      : null,
  );
}

function clearedByHolder(links) {
  const groups = new Map();
  for (const link of links) {
    if (link.type !== "impossibility" || !["inferred", "confirmed"].includes(link.status)) continue;
    const group = groups.get(link.a);
    if (group) group.count += 1;
    else groups.set(link.a, { link, count: 1 });
  }
  return [...groups.values()];
}

export function renderOverview(root) {
  const b = state.bundle;
  const decision = b.decision;
  const crime = crimeHypothesis();
  const cleared = clearedByHolder(b.links);
  const traced = b.reach.trace.victim_out;
  const held = b.reach.freeze.reduce((sum, row) => sum + row.held, 0);
  const presence = b.links
    .filter((l) => l.type === "co_presence" && ["inferred", "confirmed"].includes(l.status))
    .sort((a, c) => c.w - a.w)[0];
  root.append(
    h(
      "div",
      { class: "spread" },
      h(
        "div",
        null,
        h("h1", { text: b.case.title }),
        h(
          "p",
          { class: "lead" },
          `Case ${b.case.id}`,
          b.case.complaint_time ? `, complaint filed ${ist(b.case.complaint_time)} IST` : "",
        ),
      ),
      h("div", { class: "faint", text: `Engine ${b.case.engine_version}, digest ${b.digest.slice(0, 12)}` }),
    ),
    h(
      "div",
      { class: "card" },
      h(
        "div",
        { class: "verdict" },
        h(
          "div",
          { class: `verdict-badge ${decision.label}` },
          h("div", { class: "label", text: "Leading explanation" }),
          h("div", { class: "title", text: decision.title }),
          h("div", {
            class: "score",
            text:
              crime && decision.label === crime.template && decision.label !== "no_offence"
                ? `S ${signed(decision.score, 1)}, ${signed(decision.margin, 1)} over the next explanation`
                : `Best offence pattern S ${signed(decision.score, 1)}`,
          }),
        ),
        h(
          "div",
          { style: { flex: 1 } },
          h("p", { style: { marginTop: 0 }, text: `${decision.reason}.` }),
          decision.suspicious && decision.suspicious.length && decision.label !== crime?.template
            ? h(
                "div",
                { class: "note-box" },
                "Suspicious activity found: ",
                decision.suspicious
                  .map((s) => s.detail)
                  .slice(0, 3)
                  .join("; "),
              )
            : null,
          h(
            "div",
            { class: "kpis" },
            h(
              "div",
              { class: "kpi" },
              h("div", { class: "v", text: String(b.counts.evidence) }),
              h("div", { class: "l", text: "Evidence files" }),
            ),
            h(
              "div",
              { class: "kpi" },
              h("div", { class: "v", text: b.counts.observations.toLocaleString("en-IN") }),
              h("div", { class: "l", text: "Records parsed" }),
            ),
            h(
              "div",
              { class: "kpi" },
              h("div", { class: "v", text: inr(traced) }),
              h("div", { class: "l", text: "Traced from complainant" }),
            ),
            h(
              "div",
              { class: "kpi" },
              h("div", { class: "v", text: inr(held) }),
              h("div", { class: "l", text: "Still held, can be frozen" }),
            ),
          ),
        ),
      ),
    ),
    h(
      "div",
      { class: "grid two", style: { marginTop: "16px" } },
      h("div", { class: "stack" }, h("h2", { text: "Ranked explanations" }), b.hypotheses.slice(0, 5).map(hypothesisCard)),
      h(
        "div",
        { class: "stack" },
        presence
          ? h(
              "div",
              { class: "card" },
              h("h2", { text: "Strongest cross-source link" }),
              h("p", { class: "small", text: presence.claim }),
              h(
                "div",
                { class: "row" },
                pill(`W ${signed(presence.w, 2)}`),
                pill(presence.verbal, "grey"),
                presence.posterior ? pill(`posterior ${pct(presence.posterior, 0)}`, "teal") : null,
              ),
              h("p", {
                class: "faint",
                text: `${presence.extra.population} phones were on those cells at the time; the rarity test keeps bystanders out.`,
              }),
              h("button", {
                class: "btn light small",
                type: "button",
                onclick: () => showLink(presence.link_id),
                text: "Open the arithmetic",
              }),
            )
          : null,
        cleared.length
          ? h(
              "div",
              { class: "card" },
              h("h2", { text: "People cleared" }),
              cleared.slice(0, 3).map(({ link, count }) =>
                h(
                  "p",
                  { class: "small" },
                  link.claim,
                  count > 1
                    ? h("span", {
                        class: "faint",
                        text: `. The same holds for ${count - 1} more withdrawal${count > 2 ? "s" : ""}.`,
                      })
                    : null,
                  " ",
                  h("button", { class: "btn light small", type: "button", onclick: () => showLink(link.link_id), text: "Why" }),
                ),
              ),
            )
          : null,
        b.fragility.available
          ? h(
              "div",
              { class: "card" },
              h("h2", { text: "What the conclusion rests on" }),
              h("p", { class: "small", text: `${b.fragility.message}.` }),
              h(
                "ul",
                { class: "small" },
                b.fragility.rests_on.map((item) => h("li", null, `${item.label} (${signed(item.w, 1)})`)),
              ),
            )
          : null,
        b.leads.length
          ? h(
              "div",
              { class: "card" },
              h("h2", { text: "Next requests" }),
              h(
                "ol",
                { class: "small" },
                b.leads
                  .slice(0, 4)
                  .map((lead) => h("li", null, h("strong", { text: lead.title }), h("div", { class: "faint", text: lead.why }))),
              ),
            )
          : null,
        b.linked_cases && b.linked_cases.length
          ? h(
              "div",
              { class: "card" },
              h("h2", { text: "Linked cases" }),
              b.linked_cases.map((c) =>
                h(
                  "p",
                  { class: "small" },
                  h("a", { href: `#/${encodeURIComponent(c.case_id)}/overview`, text: c.case_id }),
                  `: shares ${c.shared.map(short).join(", ")}`,
                ),
              ),
            )
          : null,
      ),
    ),
  );
}
