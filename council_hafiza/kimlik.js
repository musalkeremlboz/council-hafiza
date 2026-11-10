// COUNCIL kimliği: işaret (7A · Yörünge) her [data-isaret] öğesinin içine çizilir; uygulama şeridi her [data-serit] öğesine
// kurulur (değeri o sayfanın uygulamasıdır). Denetim, Gezgin, uygulamalar ve giriş sayfası ortak kullanır.
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

  const UYGULAMALAR = [["panel", "Dn", "Denetim", "/panel"], ["gezgin", "Gz", "Gezgin", "/panel/gezgin"], ["not", "No", "Not", "/panel/not"],
    ["gorev", "Gr", "Görev", "/panel/gorev"], ["takvim", "Tk", "Takvim", "/panel/takvim"], ["ders", "De", "Ders", "/panel/ders"],
    ["aliskanlik", "Al", "Alışkanlık", "/panel/aliskanlik"], ["oruc", "Or", "Oruç", "/panel/oruc"], ["ayarlar", "Ay", "Ayarlar", "/panel/ayarlar"]];
  for (const nav of document.querySelectorAll("[data-serit]")) {
    for (const [kod, sembol, ad, yol] of UYGULAMALAR) {
      const a = document.createElement("a");
      a.href = yol; a.className = "kutu";
      if (nav.dataset.serit === kod) { a.classList.add("secili"); a.setAttribute("aria-current", "page"); }
      const s = document.createElement("span"); s.className = "sembol"; s.setAttribute("aria-hidden", "true"); s.textContent = sembol;
      const n = document.createElement("span"); n.className = "ad"; n.textContent = ad;
      a.append(s, n); nav.append(a);
    }
    const secili = nav.querySelector(".secili");
    if (secili) nav.scrollLeft = Math.max(0, secili.offsetLeft - 12);       // dar ekranda seçili kutu görünür kalsın
  }
})();
