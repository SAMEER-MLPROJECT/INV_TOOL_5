import { h } from "../dom.js";
import { showEdge, showEntity, showPerson } from "../drawer.js";
import { state } from "../state.js";

let cy = null;

const COLORS = {
  phone: "#1d4e89",
  account: "#0f766e",
  upi: "#2a9d8f",
  imei: "#6d3fc0",
  imsi: "#8b5cf6",
  email: "#a15c07",
  mac: "#374151",
  host: "#4b5563",
  cloud: "#7c3aed",
  atm: "#b42318",
  domain: "#9a3412",
  ip: "#64748b",
};
const SHAPES = {
  account: "round-rectangle",
  upi: "round-rectangle",
  atm: "diamond",
  imei: "hexagon",
  imsi: "hexagon",
  mac: "rectangle",
  host: "rectangle",
  domain: "tag",
};

export function destroyGraph() {
  if (cy) {
    cy.destroy();
    cy = null;
  }
}

export function renderGraph(root) {
  const data = state.bundle.graph;
  const options = { candidates: false, rejected: true, observed: true };
  const holder = h("div", { id: "graph" });
  const check = (key, label) => {
    const input = h("input", { type: "checkbox" });
    input.checked = options[key];
    input.addEventListener("change", () => {
      options[key] = input.checked;
      applyFilter();
    });
    return h("label", null, input, label);
  };
  root.append(
    h("h1", { text: "Link graph" }),
    h("p", {
      class: "lead",
      text: "Solid edges are stated by a single record. Dashed edges are inferred across sources and carry a tested weight. Dashed boxes group identifiers into a person hypothesis.",
    }),
    h(
      "div",
      { class: "toolbar" },
      check("observed", "Observed edges"),
      check("candidates", "Weak candidates"),
      check("rejected", "Rejected links"),
      h("button", { class: "btn light small", type: "button", onclick: () => cy && cy.fit(undefined, 30), text: "Fit to view" }),
    ),
    holder,
    h(
      "div",
      { class: "legend" },
      h("span", null, h("i"), "observed record"),
      h("span", null, h("i", { class: "inferred" }), "inferred link"),
      h("span", null, h("i", { class: "confirmed" }), "confirmed by investigator"),
      h("span", null, h("i", { class: "rejected" }), "rejected"),
      h("span", null, h("i", { class: "impossible" }), "could not be there"),
      Object.entries({
        Phone: COLORS.phone,
        Account: COLORS.account,
        Handset: COLORS.imei,
        Device: COLORS.mac,
        ATM: COLORS.atm,
        Email: COLORS.email,
      }).map(([label, color]) => h("span", null, h("b", { style: { background: color } }), label)),
    ),
  );
  const elements = [];
  for (const node of data.nodes) {
    elements.push({
      group: "nodes",
      data: {
        ...node,
        color: COLORS[node.kind] || "#64748b",
        shape: SHAPES[node.kind] || "ellipse",
        display: node.is_person ? node.label : `${node.label}${node.roles && node.roles.length ? `\n${node.roles[0]}` : ""}`,
      },
    });
  }
  for (const edge of data.edges) {
    elements.push({ group: "edges", data: { ...edge, id: `e:${edge.id}` } });
  }
  destroyGraph();
  cy = cytoscape({
    container: holder,
    elements,
    style: [
      {
        selector: "node",
        style: {
          "background-color": "data(color)",
          shape: "data(shape)",
          label: "data(display)",
          "font-size": 9,
          "text-wrap": "wrap",
          "text-valign": "bottom",
          "text-margin-y": 4,
          width: 22,
          height: 22,
          color: "#1f2933",
          "text-background-color": "#ffffff",
          "text-background-opacity": 0.85,
          "text-background-padding": 2,
        },
      },
      { selector: "node[?seed]", style: { "border-width": 3, "border-color": "#0f766e" } },
      {
        selector: "node[?is_person]",
        style: {
          "background-color": "#f3f6fa",
          "background-opacity": 0.6,
          "border-style": "dashed",
          "border-width": 1.5,
          "border-color": "#8aa1bd",
          shape: "round-rectangle",
          label: "data(label)",
          "text-valign": "top",
          "font-size": 10,
          "font-weight": 600,
          color: "#1d4e89",
          padding: 10,
        },
      },
      {
        selector: "edge",
        style: {
          width: 1.3,
          "line-color": "#9aa4b1",
          "curve-style": "bezier",
          "target-arrow-shape": "triangle",
          "target-arrow-color": "#9aa4b1",
          "arrow-scale": 0.7,
          label: "data(label)",
          "font-size": 7.5,
          color: "#59616b",
          "text-rotation": "autorotate",
          "text-background-color": "#fff",
          "text-background-opacity": 0.8,
        },
      },
      {
        selector: "edge[layer = 'inferred']",
        style: {
          "line-style": "dashed",
          "line-color": "#1d4e89",
          "target-arrow-color": "#1d4e89",
          width: "mapData(w, 0, 4, 1.2, 3.6)",
        },
      },
      {
        selector: "edge[layer = 'candidate']",
        style: { "line-style": "dashed", "line-color": "#c9a96a", "target-arrow-color": "#c9a96a", width: 1 },
      },
      { selector: "edge[layer = 'confirmed']", style: { "line-color": "#1f7a4d", "target-arrow-color": "#1f7a4d", width: 3 } },
      {
        selector: "edge[layer = 'rejected']",
        style: { "line-style": "dotted", "line-color": "#b42318", "target-arrow-color": "#b42318", width: 1.5 },
      },
      {
        selector: "edge[link_type = 'impossibility']",
        style: { "line-style": "dashed", "line-color": "#b42318", "target-arrow-color": "#b42318" },
      },
      { selector: "edge[link_type = 'same_actor']", style: { "target-arrow-shape": "none" } },
      { selector: ":selected", style: { "overlay-color": "#1d4e89", "overlay-opacity": 0.15 } },
    ],
    layout: {
      name: "fcose",
      quality: "proof",
      animate: false,
      randomize: true,
      padding: 30,
      nodeRepulsion: 16000,
      idealEdgeLength: 95,
      edgeElasticity: 0.45,
      nestingFactor: 0.1,
      gravity: 0.25,
      gravityCompound: 1.0,
      gravityRangeCompound: 2.0,
      numIter: 4000,
      packComponents: true,
      nodeSeparation: 90,
    },
  });
  cy.on("tap", "node", (event) => {
    const node = event.target.data();
    if (node.is_person) showPerson(node.id);
    else showEntity(node.id);
  });
  cy.on("tap", "edge", (event) => showEdge(event.target.data()));
  const applyFilter = () => {
    cy.edges().forEach((edge) => {
      const layer = edge.data("layer");
      const hidden =
        (layer === "candidate" && !options.candidates) ||
        (layer === "rejected" && !options.rejected) ||
        (layer === "observed" && !options.observed);
      edge.style("display", hidden ? "none" : "element");
    });
  };
  applyFilter();
  cy.fit(undefined, 30);
}
