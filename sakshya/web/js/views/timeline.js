import { h, pill, table } from "../dom.js";
import { showObservation } from "../drawer.js";
import { duration, ist } from "../format.js";
import { state } from "../state.js";

let instance = null;

export function destroyTimeline() {
  if (instance) {
    instance.destroy();
    instance = null;
  }
}

export function renderTimeline(root) {
  const data = state.bundle.timeline;
  const corrected = data.items.filter((i) => i.corrected);
  const mode = { raw: false };
  const holder = h("div", { id: "timeline" });
  const toggle = h(
    "div",
    { class: "segmented" },
    h("button", { class: "on", type: "button", text: "Corrected times" }),
    h("button", { type: "button", text: "As recorded" }),
  );
  root.append(
    h("h1", { text: "Reconstruction" }),
    h("p", {
      class: "lead",
      text: "One merged clock for every source. Device clocks and time zones were corrected from events that also appear in reference records; shaded bands show the remaining uncertainty.",
    }),
    h(
      "div",
      { class: "toolbar" },
      toggle,
      corrected.length
        ? pill(`${corrected.length} events had their clock corrected`, "warn")
        : pill("No clock corrections needed", "good"),
      h("span", { class: "faint", text: "Click an event to open the source record." }),
    ),
    holder,
    h("h2", { style: { marginTop: "18px" }, text: "Events in order" }),
    table(
      [
        { label: "Time (IST)", render: (r) => ist(r.t) },
        { label: "Phase", render: (r) => pill(r.phase_label, r.phase === "context" ? "grey" : "") },
        { label: "Event", render: (r) => r.summary },
        { label: "Source", render: (r) => `${r.evidence_id} ${r.source_label}` },
        { label: "Correction", render: (r) => (r.corrected ? duration(r.offset_s) : "") },
      ],
      data.items,
      (row) => showObservation(row.obs_id),
    ),
  );
  const groups = new vis.DataSet(data.groups.map((g, i) => ({ id: g.id, content: g.label, order: i })));
  const build = () => {
    const items = [];
    for (const item of data.items) {
      const t = mode.raw && item.t_raw ? item.t_raw : item.t;
      items.push({
        id: item.obs_id,
        group: item.phase,
        start: new Date(t * 1000),
        type: "point",
        content: item.title,
        title: `${ist(t)} IST\n${item.summary}`,
        className: `phase-${item.phase}${item.corrected ? " corrected" : ""}`,
      });
      if (!mode.raw && item.sigma > 60) {
        items.push({
          id: `${item.obs_id}#u`,
          group: item.phase,
          type: "background",
          className: "uncertainty",
          start: new Date((item.t - item.sigma) * 1000),
          end: new Date((item.t + item.sigma) * 1000),
        });
      }
    }
    return new vis.DataSet(items);
  };
  destroyTimeline();
  const options = {
    stack: true,
    zoomMin: 60 * 1000,
    height: "480px",
    verticalScroll: true,
    orientation: "top",
    tooltip: { followMouse: true },
    margin: { item: { horizontal: 2, vertical: 4 } },
  };
  if (data.window) {
    options.start = new Date(data.window[0] * 1000);
    options.end = new Date(data.window[1] * 1000);
  }
  if (typeof vis.moment === "function") options.moment = (date) => vis.moment(date).utcOffset("+05:30");
  instance = new vis.Timeline(holder, build(), groups, options);
  instance.on("select", (event) => {
    const id = event.items[0];
    if (id && !String(id).endsWith("#u")) showObservation(id);
  });
  const [correctedBtn, rawBtn] = toggle.querySelectorAll("button");
  correctedBtn.addEventListener("click", () => {
    mode.raw = false;
    correctedBtn.classList.add("on");
    rawBtn.classList.remove("on");
    instance.setItems(build());
  });
  rawBtn.addEventListener("click", () => {
    mode.raw = true;
    rawBtn.classList.add("on");
    correctedBtn.classList.remove("on");
    instance.setItems(build());
  });
}
