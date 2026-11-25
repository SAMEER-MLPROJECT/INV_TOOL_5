import { bar, clear, h, pill, table } from "../dom.js";
import { showAccount, toast } from "../drawer.js";
import { inr, pct } from "../format.js";
import { crimeHypothesis, state } from "../state.js";
import { loadReach, timeSlider } from "./money.js";

let playing = null;

export function stopReplay() {
  if (playing) {
    clearInterval(playing);
    playing = null;
  }
}

export function renderPredict(root) {
  const body = h("div", { class: "stack" });
  const draw = (reach) => {
    clear(body);
    const p = reach.prediction;
    if (!p.available) {
      body.append(h("div", { class: "empty", text: p.reason || "Nothing to predict." }));
      return;
    }
    const current = p.posterior.find((row) => row.phase === p.current);
    body.append(
      h(
        "div",
        { class: "grid halves" },
        h(
          "div",
          { class: "card" },
          h("h2", { text: "Which phase the offence is in" }),
          p.posterior.map((row) =>
            h(
              "div",
              { class: `posterior-row ${row.phase === p.current ? "current" : ""}` },
              h("span", { class: "label", text: row.label }),
              bar(row.p, 1),
              h("span", { class: "num", text: pct(row.p) }),
            ),
          ),
          h("p", {
            class: "faint",
            text: `Hidden Markov model over the template phases, from ${p.events_seen} evidenced events up to this time.`,
          }),
        ),
        h(
          "div",
          { class: "card" },
          h("h2", { text: p.next ? `When ${p.next_label.toLowerCase()} is likely` : "Trajectory" }),
          h("p", { text: p.message }),
          p.horizons
            ? h(
                "div",
                { class: "horizon" },
                p.horizons.map((item) =>
                  h(
                    "div",
                    null,
                    h("div", { class: "v", text: pct(item.p) }),
                    h("div", { class: "l", text: `within ${item.minutes} min` }),
                  ),
                ),
              )
            : null,
          p.next
            ? h("div", {
                class: p.p_before_freeze > 0.5 ? "note-box" : "info-box",
                style: { marginTop: "12px" },
                text: `A freeze typically takes ${p.freeze_latency_min} min to land. Chance ${p.next_label.toLowerCase()} happens first: ${pct(p.p_before_freeze)}.`,
              })
            : null,
        ),
      ),
      h(
        "div",
        { class: "card" },
        h("h2", { text: "Freeze now" }),
        reach.freeze.length
          ? table(
              [
                { label: "#", num: true, key: "rank" },
                { label: "Account", render: (r) => h("span", { class: "mono", text: r.label }) },
                { label: "Held", num: true, render: (r) => inr(r.held) },
                { label: "Chance it moves first", num: true, render: (r) => pct(r.p_move) },
                { label: "Expected recoverable", num: true, render: (r) => h("strong", { text: inr(r.expected_recoverable) }) },
              ],
              reach.freeze,
              (row) => showAccount(row.account),
            )
          : h("p", { class: "faint", text: "No traced money is held anywhere at this time." }),
      ),
      current ? h("p", { class: "faint", text: `Current phase: ${current.label}.` }) : null,
    );
  };
  const refresh = async (asOf) => {
    try {
      draw(await loadReach(asOf));
    } catch (error) {
      toast(error.message);
    }
  };
  const slider = timeSlider(refresh);
  const crime = crimeHypothesis();
  const payment = crime?.phases.find((p) => ["payment", "unauthorized_debit"].includes(p.name))?.t_first;
  const cash = crime?.phases.find((p) => p.name === "cash_out")?.t_first;
  const replay = h("button", { class: "btn", type: "button", text: "Replay the golden hour" });
  replay.addEventListener("click", () => {
    if (!payment) return;
    stopReplay();
    let t = payment - 600;
    const stop = (cash || payment + 4 * 3600) + 900;
    const step = Math.max(120, Math.round((stop - t) / 40));
    playing = setInterval(() => {
      t += step;
      slider.input.value = String(t);
      slider.input.dispatchEvent(new Event("input"));
      if (t >= stop) stopReplay();
    }, 450);
  });
  root.append(
    h("h1", { text: "Predict" }),
    h("p", {
      class: "lead",
      text: "Tracks which phase of the offence the evidence has reached and how soon the next one usually follows, so a freeze can land before cash-out. Use the replay to see the case unfold.",
    }),
    h(
      "div",
      { class: "card" },
      h(
        "div",
        { class: "toolbar" },
        payment
          ? [replay, h("button", { class: "btn light small", type: "button", onclick: stopReplay, text: "Stop" })]
          : pill("No payment phase to replay", "grey"),
      ),
      slider.element,
    ),
    body,
  );
  const start = payment ? payment + 15 * 60 : state.bundle.case.default_as_of;
  slider.input.value = String(start);
  slider.input.dispatchEvent(new Event("input"));
}
