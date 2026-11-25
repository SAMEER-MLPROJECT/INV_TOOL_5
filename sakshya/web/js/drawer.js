import { api } from "./api.js";
import { clear, h, pill } from "./dom.js";
import { KIND_LABELS, LINK_TYPES, STATUS_TONE, duration, inr, ist, kindOf, lr, pct, short, signed, words } from "./format.js";
import { hypothesisById, personById, personOf, setState, state } from "./state.js";

const drawer = document.getElementById("drawer");
const titleEl = document.getElementById("drawer-title");
const bodyEl = document.getElementById("drawer-body");

document.getElementById("drawer-close").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeDrawer();
});

export function closeDrawer() {
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
}

function open(title, ...content) {
  titleEl.textContent = title;
  clear(bodyEl);
  bodyEl.append(...content.flat().filter(Boolean));
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  bodyEl.scrollTop = 0;
}

function loading(title) {
  open(title, h("div", { class: "loading", text: "Loading" }));
}

function errorView(title, error) {
  open(title, h("div", { class: "note-box", text: `Could not load: ${error.message}` }));
}

export function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("show"), 2600);
}

function section(title, ...children) {
  return h("section", null, h("h4", { text: title }), ...children);
}

function recordBlock(record) {
  if (!record) return null;
  const corrected = record.t_raw_display && record.t_raw_display !== record.t_display;
  return h(
    "div",
    { class: "record" },
    h(
      "div",
      { class: "spread" },
      h("strong", { text: `${record.title} ${record.obs_id}` }),
      h("button", { class: "btn light small", type: "button", onclick: () => showObservation(record.obs_id), text: "Open" }),
    ),
    h("div", { class: "meta" }, `${record.evidence_id} ${record.file}, row ${record.row}`),
    h(
      "div",
      { class: "meta" },
      record.t_display ? `Time ${record.t_display} IST` : "",
      corrected ? ` (recorded as ${record.t_raw_display})` : "",
    ),
    h("div", { class: "meta mono" }, `SHA-256 ${record.sha256.slice(0, 24)}...`),
    h("div", { class: "raw", text: record.raw }),
  );
}

function chipFor(entity) {
  const person = personOf(entity);
  return h(
    "span",
    {
      class: "chip",
      onclick: () => (person ? showPerson(person.id) : null),
    },
    h("span", { class: "k", text: KIND_LABELS[kindOf(entity)] || kindOf(entity) }),
    short(entity),
  );
}

const ACTOR_KEY = "sakshya.investigator";

function savedActor() {
  try {
    return localStorage.getItem(ACTOR_KEY) || "";
  } catch {
    return "";
  }
}

function rememberActor(name) {
  try {
    localStorage.setItem(ACTOR_KEY, name);
  } catch {
    return;
  }
}

async function submitAction(type, target, reason, actor) {
  const name = (actor || "").trim();
  if (name) rememberActor(name);
  const bundle = await api.act(state.caseId, { type, target, reason, actor: name || "investigator" });
  setState({ bundle });
  toast("Decision recorded in the custody ledger and the case was rescored");
  return bundle;
}

function actionBox(link) {
  if (link.status === "observed") return null;
  const actor = h("input", {
    type: "text",
    class: "actor",
    placeholder: "Your name and rank",
    "aria-label": "Investigator",
    maxlength: 80,
  });
  actor.value = savedActor();
  const reason = h("textarea", { placeholder: "Reason (recorded in the custody ledger)", "aria-label": "Reason" });
  const status = h("div", { class: "faint" });
  const run = async (type) => {
    if (reason.value.trim().length < 3) {
      status.textContent = "Please give a short reason.";
      return;
    }
    status.textContent = "Saving and rescoring";
    try {
      await submitAction(type, link.link_id, reason.value.trim(), actor.value);
      await showLink(link.link_id);
    } catch (error) {
      status.textContent = error.message;
    }
  };
  const revoke = state.bundle.actions.find((a) => a.target === link.link_id);
  return section(
    "Investigator decision",
    h(
      "div",
      { class: "action-box" },
      actor,
      reason,
      h(
        "div",
        { class: "row", style: { marginTop: "8px" } },
        h("button", { class: "btn good small", type: "button", onclick: () => run("confirm_link"), text: "Confirm link" }),
        h("button", { class: "btn danger small", type: "button", onclick: () => run("reject_link"), text: "Reject link" }),
        revoke
          ? h("button", {
              class: "btn light small",
              type: "button",
              text: "Undo earlier decision",
              onclick: async () => {
                try {
                  await submitAction("revoke", revoke.id, reason.value.trim() || "Undo previous decision", actor.value);
                  await showLink(link.link_id);
                } catch (error) {
                  status.textContent = error.message;
                }
              },
            })
          : null,
      ),
      status,
      h("div", {
        class: "faint",
        text: "The tool never confirms a link by itself. Rejecting a same-person link also stops those identifiers being merged.",
      }),
    ),
  );
}

export async function showLink(linkId) {
  loading("Tested link");
  try {
    const link = await api.link(state.caseId, linkId);
    const posterior = link.posterior !== null && link.posterior !== undefined;
    open(
      LINK_TYPES[link.type] || words(link.type),
      h(
        "div",
        { class: "row" },
        pill(link.status, STATUS_TONE[link.status]),
        pill(link.verbal, "grey"),
        h("span", { class: "faint", text: link.link_id }),
      ),
      h("p", { class: "claim", text: link.claim }),
      link.note ? h("div", { class: "note-box", text: link.note }) : null,
      h(
        "div",
        { class: "weights" },
        h("div", null, h("div", { class: "v", text: signed(link.w) }), h("div", { class: "l", text: "Weight W (log10 LR)" })),
        h("div", null, h("div", { class: "v", text: lr(link.w_calibrated) }), h("div", { class: "l", text: "Likelihood ratio" })),
        h(
          "div",
          null,
          h("div", { class: "v", text: posterior ? pct(link.posterior, 1) : "n/a" }),
          h("div", { class: "l", text: "Posterior" }),
        ),
        h(
          "div",
          null,
          h("div", { class: "v", text: link.prior_odds ? `1 : ${Math.round(1 / link.prior_odds)}` : "n/a" }),
          h("div", { class: "l", text: "Prior odds" }),
        ),
      ),
      link.calibration_scale !== 1
        ? h("p", {
            class: "faint",
            text: `Likelihood ratio and posterior use the calibration scale ${link.calibration_scale} fitted for this link type on training cases.`,
          })
        : null,
      section(
        "How the weight was built",
        link.terms.map((term) =>
          h(
            "div",
            { class: "term-row" },
            h("div", null, h("strong", { text: words(term.name) }), h("div", { class: "faint", text: term.source_label })),
            h("div", { class: `w ${term.w >= 0 ? "pos" : "neg"}`, text: signed(term.w) }),
            h("div", { text: term.detail }),
          ),
        ),
        h("p", { class: "faint", text: `Terms from one source are capped at 4 before adding. Raw total ${signed(link.raw_w)}.` }),
      ),
      section("Basis records", link.basis_detail.map(recordBlock)),
      link.alternatives.length
        ? section(
            "Other explanations",
            h(
              "ul",
              null,
              link.alternatives.map((t) => h("li", { text: t })),
            ),
          )
        : null,
      link.defeaters.length
        ? section(
            "What would break it",
            h(
              "ul",
              null,
              link.defeaters.map((t) => h("li", { text: t })),
            ),
          )
        : null,
      actionBox(link),
    );
  } catch (error) {
    errorView("Tested link", error);
  }
}

export async function showObservation(obsId) {
  loading("Evidence record");
  try {
    const record = await api.observation(state.caseId, obsId);
    const clock = record.clock;
    open(
      `${record.title} ${record.obs_id}`,
      h(
        "div",
        { class: "row" },
        pill(record.source_label, "grey"),
        h("span", { class: "faint", text: `${record.evidence_id} ${record.file}, row ${record.row}` }),
      ),
      section("Verbatim record", h("div", { class: "raw", text: record.raw })),
      section(
        "Time",
        h("div", null, record.t_display ? `${record.t_display} IST (uncertainty ${Math.round(record.sigma_t)} s)` : "No time"),
        record.t_raw_display && record.t_raw_display !== record.t_display
          ? h("div", { class: "faint", text: `Recorded as ${record.t_raw_display}; corrected by ${duration(clock.offset_s)}` })
          : null,
        clock ? h("div", { class: "faint", text: clock.note }) : null,
      ),
      record.place
        ? section(
            "Place",
            h("div", null, `${record.place}${record.radius_m ? ` (radius ${Math.round(record.radius_m)} m)` : ""}`),
          )
        : null,
      record.amount ? section("Amount", h("div", { text: inr(record.amount) })) : null,
      section(
        "Identifiers",
        h(
          "div",
          null,
          record.identifiers.map((item) =>
            h("span", null, h("span", { class: "faint", text: `${item.role} ` }), chipFor(item.entity)),
          ),
        ),
      ),
      section("Integrity", h("div", { class: "mono", text: `SHA-256 of source file ${record.sha256}` })),
    );
  } catch (error) {
    errorView("Evidence record", error);
  }
}

export function showPerson(personId) {
  const person = personById(personId);
  if (!person) return;
  const links = state.bundle.links.reduce((acc, l) => acc.set(l.link_id, l), new Map());
  open(
    `${person.id} ${person.names[0] || person.label}`,
    h(
      "div",
      { class: "row" },
      person.is_seed ? pill("Complainant", "teal") : null,
      person.roles.map((r) => pill(r)),
      person.cleared.length ? pill("Cleared at cash-out", "good") : null,
    ),
    h("p", {
      class: "faint",
      text: "A person here is a hypothesis: identifiers grouped because tested links tie them together. Registered names are what KYC records say, not verified identity.",
    }),
    section(
      "Identifiers and how they were joined",
      person.members.map((m) =>
        h(
          "div",
          { class: "member" },
          h("div", null, h("div", { class: "faint", text: m.kind_label }), h("span", { class: "mono", text: m.label })),
          h(
            "div",
            { class: "small" },
            m.via_claim || "Starting identifier",
            m.names.length ? h("div", { class: "faint", text: `Registered as ${m.names.join(", ")}` }) : null,
          ),
          m.via && links.has(m.via)
            ? h("button", {
                class: "btn light small",
                type: "button",
                onclick: () => showLink(m.via),
                text: `W ${signed(m.score, 1)}`,
              })
            : h("span", { class: "faint", text: "" }),
        ),
      ),
    ),
    person.indicators.length
      ? section(
          "Indicators",
          person.indicators.map((i) =>
            h(
              "div",
              { class: "member" },
              h("div", null, h("strong", { class: "small", text: words(i.name) })),
              h("div", { class: "small", text: i.detail }),
              h("span", { class: `pill ${i.weight >= 0 ? "teal" : "bad"}`, text: signed(i.weight, 1) }),
            ),
          ),
        )
      : null,
  );
}

export function showAccount(entity) {
  const trace = state.bundle.reach.trace.accounts.find((a) => a.account === entity);
  const person = personOf(entity);
  open(
    `Account ${short(entity)}`,
    trace
      ? section(
          "Traced money",
          h(
            "div",
            { class: "weights" },
            h("div", null, h("div", { class: "v", text: inr(trace.tainted_in) }), h("div", { class: "l", text: "Received" })),
            h("div", null, h("div", { class: "v", text: inr(trace.tainted_out) }), h("div", { class: "l", text: "Sent on" })),
            h(
              "div",
              null,
              h("div", { class: "v", text: inr(trace.tainted_cash) }),
              h("div", { class: "l", text: "Cash withdrawn" }),
            ),
            h("div", null, h("div", { class: "v", text: inr(trace.tainted_held) }), h("div", { class: "l", text: "Still held" })),
          ),
          h("p", {
            class: "faint",
            text: `Hop ${trace.hop} from the complainant. ${trace.statement ? "Statement in the case." : "No statement in the case; amounts come from the sender's records."}`,
          }),
        )
      : null,
    person
      ? section(
          "Person",
          h("button", {
            class: "btn light small",
            type: "button",
            onclick: () => showPerson(person.id),
            text: `Open ${person.id}`,
          }),
        )
      : null,
  );
}

export function showHypothesis(id) {
  const hyp = hypothesisById(id);
  if (!hyp) return;
  const groups = {
    prior: "Prior",
    indicator: "Indicators",
    link: "Tested links",
    missing: "Missing evidence",
    order: "Order and timing",
    baseline: "Reference",
  };
  const rows = hyp.breakdown.map((item) =>
    h(
      "div",
      { class: "term-row" },
      h(
        "div",
        null,
        h("strong", { class: "small", text: groups[item.kind] || item.kind }),
        item.role ? h("div", { class: "faint", text: words(item.role) }) : null,
      ),
      h("div", { class: `w ${item.w >= 0 ? "pos" : "neg"}`, text: signed(item.w) }),
      h(
        "div",
        { class: "small" },
        item.detail || item.label || words(item.name),
        item.link_id
          ? h(
              "div",
              null,
              h("button", { class: "btn light small", type: "button", onclick: () => showLink(item.link_id), text: "Open link" }),
            )
          : null,
        item.evidence && item.evidence.length
          ? h(
              "div",
              null,
              item.evidence
                .slice(0, 4)
                .map((obs) => h("span", { class: "chip", onclick: () => showObservation(obs), text: obs })),
            )
          : null,
      ),
    ),
  );
  open(
    `${hyp.id} ${hyp.label}`,
    h(
      "div",
      { class: "row" },
      pill(`S ${signed(hyp.score, 1)}`),
      hyp.margin_next !== null ? pill(`${signed(hyp.margin_next, 1)} over next`, "grey") : null,
      Object.values(hyp.variant || {}).map((v) => pill(v, "warn")),
    ),
    h("p", {
      class: "faint",
      text: "S adds base-10 log likelihood ratios against ordinary activity. Missing evidence counts only where a source in the case could have shown it.",
    }),
    section("Score breakdown", rows),
    hyp.phases.length
      ? section(
          "Phases",
          hyp.phases.map((p) =>
            h(
              "div",
              { class: "member" },
              h("div", null, h("strong", { class: "small", text: p.label })),
              h(
                "div",
                { class: "small" },
                p.filled
                  ? `${p.event_count} records, first ${ist(p.t_first, true)}`
                  : `Not found (observability ${pct(p.observability)})`,
                p.events.length
                  ? h(
                      "div",
                      null,
                      p.events
                        .slice(0, 5)
                        .map((obs) => h("span", { class: "chip", onclick: () => showObservation(obs), text: obs })),
                    )
                  : null,
              ),
              pill(
                p.filled ? (p.order_ok ? "evidenced" : "timing issue") : p.optional ? "optional" : "gap",
                p.filled ? (p.order_ok ? "good" : "warn") : p.optional ? "grey" : "bad",
              ),
            ),
          ),
        )
      : null,
  );
}

export function showEdge(edge) {
  if (edge.link_id) {
    showLink(edge.link_id);
    return;
  }
  open(
    `${words(edge.kind)}: ${short(edge.source)} to ${short(edge.target)}`,
    h("p", { class: "faint", text: "Observed relationship stated directly by records." }),
    section(
      "Records",
      (edge.obs || []).map((obs) => h("span", { class: "chip", onclick: () => showObservation(obs), text: obs })),
    ),
  );
}

export function showEntity(entity) {
  if (kindOf(entity) === "account") {
    showAccount(entity);
    return;
  }
  const person = personOf(entity);
  if (person) showPerson(person.id);
}
