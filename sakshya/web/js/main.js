import { api } from "./api.js";
import { clear, h } from "./dom.js";
import { closeDrawer, toast } from "./drawer.js";
import { setState, state, subscribe } from "./state.js";
import { openUpload } from "./upload.js";
import { renderEvaluation } from "./views/evaluation.js";
import { destroyGraph, renderGraph } from "./views/graph.js";
import { renderEvidence, renderLeads, renderLinks, renderPeople } from "./views/lists.js";
import { destroyMap, renderMap } from "./views/map.js";
import { renderMoney } from "./views/money.js";
import { renderOverview } from "./views/overview.js";
import { renderPredict, stopReplay } from "./views/predict.js";
import { destroyTimeline, renderTimeline } from "./views/timeline.js";

const VIEWS = {
  overview: renderOverview,
  timeline: renderTimeline,
  graph: renderGraph,
  map: renderMap,
  money: renderMoney,
  predict: renderPredict,
  leads: renderLeads,
  people: renderPeople,
  links: renderLinks,
  evidence: renderEvidence,
  evaluation: renderEvaluation,
};

const viewEl = document.getElementById("view");
const select = document.getElementById("case-select");
const reportBtn = document.getElementById("report-btn");

function parseHash() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  return { caseId: parts[0] || null, view: VIEWS[parts[1]] ? parts[1] : "overview" };
}

function go(caseId, view) {
  const target = `#/${encodeURIComponent(caseId)}/${view}`;
  if (location.hash !== target) location.hash = target;
  else route();
}

function teardown() {
  destroyGraph();
  destroyMap();
  destroyTimeline();
  stopReplay();
}

function render() {
  teardown();
  clear(viewEl);
  for (const link of document.querySelectorAll(".sidenav a")) {
    link.classList.toggle("active", link.dataset.view === state.view);
    link.setAttribute("href", `#/${encodeURIComponent(state.caseId || "")}/${link.dataset.view}`);
  }
  if (!state.bundle && state.view !== "evaluation") {
    viewEl.append(h("div", { class: "loading", text: "Loading case" }));
    return;
  }
  try {
    const result = VIEWS[state.view](viewEl);
    if (result && typeof result.catch === "function")
      result.catch((error) => viewEl.append(h("div", { class: "note-box", text: error.message })));
  } catch (error) {
    viewEl.append(h("div", { class: "note-box", text: `This view could not be drawn: ${error.message}` }));
  }
  viewEl.focus({ preventScroll: true });
}

async function loadCase(caseId) {
  setState({ caseId, bundle: null, asOf: null });
  render();
  try {
    const bundle = await api.bundle(caseId);
    if (state.caseId !== caseId) return;
    state.bundle = bundle;
    reportBtn.href = `/api/cases/${encodeURIComponent(caseId)}/report`;
    select.value = caseId;
    render();
  } catch (error) {
    clear(viewEl);
    viewEl.append(h("div", { class: "note-box", text: `Could not load case ${caseId}: ${error.message}` }));
  }
}

async function route() {
  const { caseId, view } = parseHash();
  closeDrawer();
  if (!caseId) {
    const first = select.options[0]?.value;
    if (first) go(first, view);
    return;
  }
  const changedCase = caseId !== state.caseId;
  state.view = view;
  if (changedCase) await loadCase(caseId);
  else render();
}

async function refreshCases(selectId) {
  const cases = await api.cases();
  clear(select);
  for (const item of cases) {
    const label = item.error ? `${item.id} (could not load)` : `${item.id}  |  ${item.title}  |  ${item.decision_title}`;
    select.append(h("option", { value: item.id, text: label }));
  }
  if (selectId) select.value = selectId;
  return cases;
}

subscribe((current, patch) => {
  if ("bundle" in patch && patch.bundle) render();
});

select.addEventListener("change", () => go(select.value, state.view));
document.getElementById("upload-btn").addEventListener("click", () =>
  openUpload(async (caseId) => {
    await refreshCases(caseId);
    toast(`Case ${caseId} added and analysed`);
    go(caseId, "overview");
  }),
);
window.addEventListener("hashchange", route);

(async () => {
  try {
    await refreshCases();
    route();
  } catch (error) {
    viewEl.append(h("div", { class: "note-box", text: `The server could not be reached: ${error.message}` }));
  }
})();
