import { h } from "../dom.js";
import { showLink, showObservation } from "../drawer.js";
import { state } from "../state.js";

let map = null;

const STYLE = {
  cash: { color: "#b42318", fill: "#b42318", radius: 9, label: "Cash withdrawal" },
  presence: { color: "#1d4e89", fill: "#1d4e89", radius: 6, label: "Phone on a cell" },
  cloud: { color: "#6d3fc0", fill: "#6d3fc0", radius: 6, label: "Cloud location fix" },
  cleared: { color: "#5b6574", fill: "#ffffff", radius: 7, label: "Cleared by travel time" },
  seizure: { color: "#0f766e", fill: "#0f766e", radius: 8, label: "Search premises" },
};

export function destroyMap() {
  if (map) {
    map.remove();
    map = null;
  }
}

function caseArea(data) {
  if (!data.bounds) return null;
  const area = L.latLngBounds(data.bounds);
  for (const circle of data.circles) {
    const dLat = circle.radius_m / 111320;
    const dLon = circle.radius_m / (111320 * Math.cos((circle.lat * Math.PI) / 180));
    area.extend([circle.lat - dLat, circle.lon - dLon]).extend([circle.lat + dLat, circle.lon + dLon]);
  }
  return area;
}

export function renderMap(root) {
  const data = state.bundle.map;
  const area = caseArea(data);
  const holder = h("div", { id: "map" });
  root.append(
    h("h1", { text: "Map" }),
    h("p", {
      class: "lead",
      text: "Withdrawals, the cells and location fixes tested against them, and evidence that clears people. Circles show cell coverage radius.",
    }),
    h(
      "div",
      { class: "toolbar" },
      h("button", {
        class: "btn light small",
        type: "button",
        onclick: () => map && area && map.fitBounds(area, { padding: [30, 30], maxZoom: 16 }),
        text: "Case area",
      }),
      data.full_bounds && JSON.stringify(data.full_bounds) !== JSON.stringify(data.bounds)
        ? h("button", {
            class: "btn light small",
            type: "button",
            onclick: () => map && map.fitBounds(data.full_bounds, { padding: [40, 40] }),
            text: "Include cleared locations",
          })
        : null,
    ),
    data.points.length ? holder : h("div", { class: "empty", text: "No located events in this case." }),
    h(
      "div",
      { class: "legend" },
      Object.values(STYLE).map((s) =>
        h("span", null, h("b", { style: { background: s.fill, border: `2px solid ${s.color}` } }), s.label),
      ),
      h("span", null, h("i", { class: "inferred" }), "presence link"),
      h("span", null, h("i", { class: "impossible" }), "impossible travel"),
    ),
  );
  if (!data.points.length) return;
  destroyMap();
  map = L.map(holder, { preferCanvas: true });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);
  for (const circle of data.circles) {
    L.circle([circle.lat, circle.lon], {
      radius: circle.radius_m,
      color: "#1d4e89",
      weight: 1,
      fillOpacity: 0.05,
      dashArray: "4 4",
    })
      .bindTooltip(`Cell ${circle.label}`)
      .addTo(map);
  }
  for (const line of data.lines) {
    const impossible = line.kind === "impossibility";
    L.polyline([line.from, line.to], {
      color: impossible ? "#b42318" : "#1d4e89",
      weight: impossible ? 1.5 : 2.5,
      dashArray: "6 6",
      opacity: 0.8,
    })
      .on("click", () => showLink(line.link_id))
      .bindTooltip(impossible ? "Could not have been there" : `Presence link, W ${line.w}`)
      .addTo(map);
  }
  for (const point of data.points) {
    const style = STYLE[point.category] || STYLE.presence;
    const marker = L.circleMarker([point.lat, point.lon], {
      radius: style.radius,
      color: style.color,
      weight: 2,
      fillColor: style.fill,
      fillOpacity: point.category === "cleared" ? 0.4 : 0.85,
    }).addTo(map);
    const popup = h(
      "div",
      null,
      h("strong", { text: point.label }),
      h("div", { text: point.time ? `${point.time} IST` : "" }),
      h("button", {
        class: "btn light small",
        type: "button",
        style: { marginTop: "6px" },
        onclick: () => showObservation(point.obs_id),
        text: "Open record",
      }),
    );
    marker.bindPopup(popup);
  }
  if (area) map.fitBounds(area, { padding: [30, 30], maxZoom: 16 });
  setTimeout(() => map && map.invalidateSize(), 50);
}
