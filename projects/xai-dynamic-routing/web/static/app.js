const POS = {
  R1: [80, 200],
  R2: [200, 80],
  R3: [200, 320],
  R4: [340, 140],
  R5: [340, 280],
  R6: [480, 140],
  R7: [480, 280],
  R8: [580, 200],
};

function line(svg, x1, y1, x2, y2, edge) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", "line");
  el.setAttribute("x1", x1);
  el.setAttribute("y1", y1);
  el.setAttribute("x2", x2);
  el.setAttribute("y2", y2);
  el.setAttribute("stroke", "#38bdf8");
  el.setAttribute("stroke-width", "3");
  el.setAttribute("stroke-linecap", "round");
  el.style.cursor = "pointer";
  el.addEventListener("click", () => {
    document.getElementById("detail").textContent = JSON.stringify(edge, null, 2);
  });
  svg.appendChild(el);
}

function circle(svg, id, x, y) {
  const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
  const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  c.setAttribute("cx", x);
  c.setAttribute("cy", y);
  c.setAttribute("r", "18");
  c.setAttribute("fill", "#1e293b");
  c.setAttribute("stroke", "#e2e8f0");
  c.setAttribute("stroke-width", "2");
  const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
  t.setAttribute("x", x);
  t.setAttribute("y", y + 4);
  t.setAttribute("text-anchor", "middle");
  t.setAttribute("fill", "#e2e8f0");
  t.setAttribute("font-size", "11");
  t.textContent = id;
  g.appendChild(c);
  g.appendChild(t);
  svg.appendChild(g);
}

async function main() {
  const status = document.getElementById("status");
  const svg = document.getElementById("graph");
  try {
    const res = await fetch("/api/topology");
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    status.textContent = `Loaded ${data.file}: ${data.node_count} nodes, ${data.edge_count} edges.`;
    for (const e of data.edges) {
      const a = POS[e.source];
      const b = POS[e.target];
      if (!a || !b) continue;
      line(svg, a[0], a[1], b[0], b[1], e);
    }
    for (const n of data.nodes) {
      const p = POS[n.id];
      if (p) circle(svg, n.id, p[0], p[1]);
    }
  } catch (err) {
    status.textContent = "Failed to load topology: " + err;
  }
}

main();
