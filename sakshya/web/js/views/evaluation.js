import { api } from "../api.js";
import { bar, h, pill, table } from "../dom.js";
import { pct, words } from "../format.js";

function verdict(ok) {
  return ok === null || ok === undefined ? pill("reported", "grey") : ok ? pill("met", "good") : pill("below target", "warn");
}

function num(value, digits = 3) {
  return value === null || value === undefined ? "n/a" : Number(value).toFixed(digits);
}

export async function renderEvaluation(root) {
  root.append(
    h("h1", { text: "Evaluation" }),
    h("p", {
      class: "lead",
      text: "Measured on held-out generated cases with answer keys that the engine never reads. Held-out seeds and case structures were not used while building the engine. All figures describe synthetic data.",
    }),
  );
  let data;
  try {
    data = await api.evaluation();
  } catch (error) {
    root.append(h("div", { class: "empty", text: `Evaluation results are not available: ${error.message}` }));
    return;
  }
  const r = data.heldout;
  const coverage = Object.values(r.extraction).map((s) => s.mean_coverage);
  const minCoverage = Math.min(...coverage);
  const rows = [
    {
      line: "Evidence processing and extraction (15)",
      metric: `Records parsed, worst of ${coverage.length} source types`,
      value: pct(minCoverage, 1),
      target: "98% or more",
      ok: minCoverage >= 0.98,
    },
    {
      line: "Cross-source correlation (20)",
      metric: "Same-event links, precision / recall",
      value: `${num(r.same_event.precision)} / ${num(r.same_event.recall)}`,
      target: "0.95 or more",
      ok: r.same_event.precision >= 0.95 && r.same_event.recall >= 0.95,
    },
    {
      line: "",
      metric: "Presence links, precision",
      value: num(r.presence.link_precision),
      target: "0.95 or more",
      ok: r.presence.link_precision >= 0.95,
    },
    {
      line: "",
      metric: "Identity resolution, precision / recall / F1",
      value: `${num(r.resolution.precision)} / ${num(r.resolution.recall)} / ${num(r.resolution.f1)}`,
      target: "precision 0.95 or more",
      ok: r.resolution.precision >= 0.95,
    },
    {
      line: "",
      metric: "Decoys wrongly merged",
      value: `${r.resolution.decoy_merges} of ${r.resolution.decoy_pairs}`,
      target: "none",
      ok: r.resolution.decoy_merges === 0,
    },
    {
      line: "Timeline and reconstruction (20)",
      metric: "Clock offset error, median / worst",
      value: `${num(r.clock.median_error_s, 1)} s / ${num(r.clock.max_error_s, 1)} s`,
      target: "under 60 s",
      ok: r.clock.max_error_s < 60,
    },
    {
      line: "",
      metric: "Wrong time zones detected",
      value: `${r.clock.timezone_detected} of ${r.clock.timezone_cases}`,
      target: "all",
      ok: r.clock.timezone_detected === r.clock.timezone_cases,
    },
    {
      line: "",
      metric: "Event ordering (Kendall tau), before / after correction",
      value: `${num(r.timeline.kendall_tau_before)} / ${num(r.timeline.kendall_tau_after)}`,
      target: "0.95 or more after",
      ok: r.timeline.kendall_tau_after >= 0.95,
    },
    {
      line: "Accuracy, traceability, explainability (25)",
      metric: "Findings with a resolvable evidence pointer",
      value: `${pct(r.traceability.share, 1)} of ${r.traceability.pointers}`,
      target: "100%",
      ok: r.traceability.share === 1,
    },
    {
      line: "",
      metric: "Same input gives identical output",
      value: data.determinism.identical ? "yes" : "no",
      target: "yes",
      ok: data.determinism.identical,
    },
    {
      line: "",
      metric: "Tampered CCTV frames caught",
      value: `${r.tamper.caught} of ${r.tamper.expected}, ${r.tamper.false_alarms} false alarms`,
      target: "all, no false alarms",
      ok: r.tamper.caught === r.tamper.expected && r.tamper.false_alarms === 0,
    },
    {
      line: "Multimedia and fraud analysis (10)",
      metric: "Accounts reached by the money, precision / recall",
      value: `${num(r.money.precision)} / ${num(r.money.recall)}`,
      target: "0.95 or more",
      ok: r.money.precision >= 0.95 && r.money.recall >= 0.95,
    },
    {
      line: "",
      metric: "Cash withdrawn, relative error",
      value: pct(r.money.cash_error_share, 1),
      target: "under 5%",
      ok: r.money.cash_error_share < 0.05,
    },
    {
      line: "",
      metric: "First-layer mule identified",
      value: pct(r.roles.mule_l1_accuracy, 0),
      target: "95% or more",
      ok: r.roles.mule_l1_accuracy >= 0.95,
    },
    {
      line: "Performance and usability (10)",
      metric: "Analysis time per case, median / worst",
      value: `${num(r.analysis_time_s.median, 2)} s / ${num(r.analysis_time_s.max, 2)} s`,
      target: "reported",
      ok: null,
    },
    {
      line: "Beyond the rubric",
      metric: "Offence type, including unknown and no offence",
      value: pct(r.classification.accuracy, 0),
      target: "reported",
      ok: null,
    },
    { line: "", metric: "Cash-out person identified", value: pct(r.roles.cashout_accuracy, 0), target: "reported", ok: null },
    {
      line: "",
      metric: "Phase tracked during layering, and error in predicted cash-out time",
      value: `${pct(r.prediction.phase_accuracy, 0)}, median ${num(r.prediction.median_error_min, 1)} min`,
      target: "reported",
      ok: null,
    },
  ];
  const classes = Object.keys(r.classification.confusion);
  root.append(
    h(
      "div",
      { class: "row" },
      pill(`${r.cases} held-out cases`),
      pill(`engine ${data.engine}`, "grey"),
      pill(`generated ${data.generated}`, "grey"),
    ),
    h(
      "div",
      { class: "card", style: { marginTop: "12px" } },
      h("h2", { text: "Against the SUTRAM rubric" }),
      table(
        [
          { label: "Rubric line (weight)", render: (x) => h("strong", { text: x.line }) },
          { label: "Metric", key: "metric" },
          { label: "Result", num: true, render: (x) => h("strong", { text: x.value }) },
          { label: "Target", key: "target" },
          { label: "", render: (x) => verdict(x.ok) },
        ],
        rows,
      ),
    ),
    h(
      "div",
      { class: "grid halves", style: { marginTop: "16px" } },
      h(
        "div",
        { class: "card" },
        h("h2", { text: "Calibration of link weights" }),
        h("p", { class: "faint", text: "Share of links that are true, by weight band. The acceptance threshold is W of 2." }),
        r.calibration.map((band) =>
          h(
            "div",
            { class: "posterior-row" },
            h("span", { class: "label", text: `${band.band} (${band.links})` }),
            bar(band.true_share, 1, band.true_share > 0.5 ? "teal" : "red"),
            h("span", { class: "num", text: pct(band.true_share, 1) }),
          ),
        ),
        h("p", {
          class: "faint",
          text: `Presence likelihood ratios were fitted on ${data.calibration_fit.links} labelled candidates from training cases: scale ${data.calibration_fit.scale}, log loss ${data.calibration_fit.log_loss} against ${data.calibration_fit.log_loss_unscaled} unscaled. The scale is applied to reported likelihood ratios and posteriors.`,
        }),
      ),
      h(
        "div",
        { class: "card" },
        h("h2", { text: "Offence type, confusion matrix" }),
        table(
          [
            { label: "Truth \\ found", render: (x) => words(x.truth) },
            ...classes.map((c) => ({ label: words(c), num: true, render: (x) => x[c] || 0 })),
          ],
          classes.map((truth) => ({ truth, ...r.classification.confusion[truth] })),
        ),
        h("h2", { style: { marginTop: "16px" }, text: "Scaling" }),
        table(
          [
            { label: "Case size", render: (x) => `${x.scale}x` },
            { label: "Records", num: true, render: (x) => x.observations.toLocaleString("en-IN") },
            { label: "Identifiers", num: true, render: (x) => x.entities.toLocaleString("en-IN") },
            { label: "Seconds", num: true, render: (x) => x.seconds.toFixed(2) },
          ],
          data.scaling,
        ),
      ),
    ),
    h("div", { class: "note-box", style: { marginTop: "16px" }, text: data.note }),
  );
}
