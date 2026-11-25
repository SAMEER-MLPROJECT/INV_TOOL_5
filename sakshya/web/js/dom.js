export function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
      else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
      else if (key === "dataset") Object.assign(node.dataset, value);
      else node.setAttribute(key, value === true ? "" : String(value));
    }
  }
  append(node, children);
  return node;
}

export function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function table(columns, rows, onRow) {
  const head = h(
    "tr",
    null,
    columns.map((c) => h("th", { class: c.num ? "num" : null, text: c.label })),
  );
  const body = rows.map((row) => {
    const tr = h(
      "tr",
      { class: onRow ? "click" : null },
      columns.map((c) => {
        const value = c.render ? c.render(row) : row[c.key];
        return h("td", { class: c.num ? "num" : null }, value === undefined || value === null ? "" : value);
      }),
    );
    if (onRow) tr.addEventListener("click", () => onRow(row));
    return tr;
  });
  return h("div", { class: "table-wrap" }, h("table", { class: "data" }, h("thead", null, head), h("tbody", null, body)));
}

export function pill(text, tone) {
  return h("span", { class: `pill ${tone || ""}`.trim(), text });
}

export function bar(value, max, tone) {
  const share = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  return h("div", { class: `bar ${tone || ""}`.trim() }, h("span", { style: { width: `${(share * 100).toFixed(1)}%` } }));
}
