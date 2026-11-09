// COUNCIL işareti (7A · Yörünge): sayfadaki her [data-isaret] öğesinin içine çizilir. Panel, Gezgin ve giriş sayfası ortak kullanır.
"use strict";
(() => {
  const NS = "http://www.w3.org/2000/svg";
  function arc(cx, cy, r, a0, a1) {
    const p = (a) => [+(cx + r * Math.cos(a * Math.PI / 180)).toFixed(2), +(cy - r * Math.sin(a * Math.PI / 180)).toFixed(2)];
    if (a1 - a0 >= 360) return arc(cx, cy, r, a0, a0 + 180) + " " + arc(cx, cy, r, a0 + 180, a0 + 360);
    const [x0, y0] = p(a0), [x1, y1] = p(a1);
    return `M${x0} ${y0} A${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 0 ${x1} ${y1}`;
  }
  function isaret() {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "-130 -130 260 260");
    const parca = [[arc(0, 0, 100, 40, 320), "#FF4F00"], [arc(0, 0, 100, -28, 28)], [arc(0, 0, 120, 180, 270)], [arc(0, 0, 78, 40, 320)],
      [arc(0, 0, 56, 0, 360)], [arc(-28, 0, 28, 180, 360), "#FF4F00"], [arc(28, 0, 28, 0, 180), "#FF4F00"]];
    for (const [d, renk] of parca) {
      const p = document.createElementNS(NS, "path");
      p.setAttribute("d", d); p.setAttribute("fill", "none"); p.setAttribute("stroke-width", "13");
      p.setAttribute("stroke", renk || "currentColor");
      svg.append(p);
    }
    return svg;
  }
  for (const e of document.querySelectorAll("[data-isaret]")) e.append(isaret());
})();
