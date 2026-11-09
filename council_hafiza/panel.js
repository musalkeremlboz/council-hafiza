// COUNCIL sistem paneli: /panel/veri'deki denetim raporunu çizer. Rapor verisi yalnız textContent ile yazılır (HTML olarak değil).
"use strict";
const CID = ["kritik", "yuksek", "orta", "dusuk", "bilgi"];
const CID_AD = { kritik: "Kritik", yuksek: "Yüksek", orta: "Orta", dusuk: "Düşük", bilgi: "Bilgi" };
const TUR_AD = { acik: "açık", celiski: "çelişki", saglik: "sağlık", bilgi: "bilgi" };
const ALAN_AD = { sunucu: "Sunucu", hafiza: "Hafıza", hermes: "Hermes", mac: "Mac", yedek: "Yedek", araclar: "Araçlar" };
const SVGNS = "http://www.w3.org/2000/svg";

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v; else if (v !== undefined && v !== null) e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined) e.append(k instanceof Node ? k : String(k));
  return e;
}
function sv(tag, attrs, text) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
}
function zaman(t) {
  if (!t) return "—";
  const d = typeof t === "number" ? new Date(t * 1000) : new Date(t);
  return d.toLocaleString("tr-TR", { dateStyle: "medium", timeStyle: "short" });
}
function once(t) {
  if (!t) return "hiç";
  const s = (Date.now() / 1000 - (typeof t === "number" ? t : Date.parse(t) / 1000));
  if (s < 3600) return Math.max(1, Math.round(s / 60)) + " dk önce";
  if (s < 86400) return Math.round(s / 3600) + " sa önce";
  return Math.round(s / 86400) + " gün önce";
}
function sonrakiDenetim() {
  const saatler = [8, 14, 20], n = new Date();
  for (const h of saatler) { const d = new Date(n); d.setHours(h, 0, 0, 0); if (d > n) return d; }
  const d = new Date(n); d.setDate(d.getDate() + 1); d.setHours(8, 0, 0, 0); return d;
}

let RAPOR = null, SEC = new Set(["kritik", "yuksek", "orta", "dusuk"]);

async function yukle() {
  const r = await fetch("/panel/veri", { credentials: "same-origin" });
  if (r.status === 401) { location.reload(); return; }
  const v = await r.json();
  if (!v.hazir) { document.getElementById("zaman").textContent = "Henüz denetim raporu yok. İlk denetim çalışınca burada görünecek."; return; }
  RAPOR = v.rapor;
  document.getElementById("zaman").textContent =
    `Son denetim: ${zaman(RAPOR.zaman)} (${once(RAPOR.zaman)}) · sonraki: ${zaman(sonrakiDenetim())} · envanter: ${RAPOR.envanter.guncelleme}`;
  const oz = document.getElementById("ozet"); oz.replaceChildren();
  for (const c of CID) if (RAPOR.ozet[c]) oz.append(el("span", { class: "rozet r-" + c }, `${CID_AD[c]} ${RAPOR.ozet[c]}`));
  bulgular(); akis(); cihazlar(); araclar(); durum(); gecmis(v.gecmis || []);
}

function bulgular() {
  const f = document.getElementById("filtre"); f.replaceChildren();
  for (const c of CID) {
    const b = el("button", { class: SEC.has(c) ? "secili" : "" }, `${CID_AD[c]} (${RAPOR.ozet[c] || 0})`);
    b.onclick = () => { SEC.has(c) ? SEC.delete(c) : SEC.add(c); bulgular(); };
    f.append(b);
  }
  const l = document.getElementById("bulgu-liste"); l.replaceChildren();
  const liste = RAPOR.bulgular.filter(b => SEC.has(b.ciddiyet));
  if (!liste.length) l.append(el("p", { class: "soluk" }, "Seçili ciddiyette bulgu yok."));
  for (const b of liste) {
    l.append(el("div", { class: "bulgu c-" + b.ciddiyet },
      el("div", { class: "bulgu-ust" },
        el("span", { class: "rozet r-" + b.ciddiyet }, CID_AD[b.ciddiyet]),
        el("span", { class: "bulgu-baslik" }, b.baslik),
        el("span", { class: "etiket" }, ALAN_AD[b.alan] || b.alan),
        el("span", { class: "etiket" }, TUR_AD[b.tur] || b.tur)),
      b.ayrinti ? el("div", { class: "soluk" }, b.ayrinti) : null,
      b.oneri ? el("div", { class: "oneri" }, el("b", {}, "Öneri: "), b.oneri) : null));
  }
}

// ---------------------------------------------------------------- akış diyagramı
const KONUM = {
  "claude-code": [175, 70, "Claude Code"], "katip": [175, 135, "Kâtip ajanı"], "bakim": [175, 200, "Bakım ajanı"],
  "antigravity": [175, 265, "Antigravity (agy)"], "hermes-masaustu": [175, 330, "Hermes masaüstü"], "mac": [175, 395, "Mac yedek kopyası"],
  "claude-chat": [175, 520, "claude.ai"], "telegram": [175, 585, "Telegram"],
  "hafiza-sunucusu": [800, 110, "Hafıza sunucusu"], "yedek": [800, 220, "Şifreli yedek"], "hermes": [800, 360, "Hermes Agent"],
  "denetci": [800, 470, "Denetim ajanı"], "panel": [800, 560, "Panel (/panel)"],
};
function dugumDurum(id) {
  const B = RAPOR.bulgular, kotu = c => ["kritik", "yuksek"].includes(c);
  const svc = (RAPOR.sunucu || {}).servisler || {};
  const arac = (RAPOR.araclar || []).find(a => a.id === id);
  if (id === "hafiza-sunucusu") return svc["council-hafiza"] === "active" ? "iyi" : "kotu";
  if (id === "hermes") { const h = Object.entries(svc).find(([k]) => k.startsWith("hermes-gateway")); return h && h[1] === "active" ? (B.some(b => b.alan === "hermes" && kotu(b.ciddiyet)) ? "kotu" : "iyi") : "kotu"; }
  if (id === "yedek") return B.some(b => b.alan === "yedek" && kotu(b.ciddiyet)) ? "kotu" : "iyi";
  if (id === "mac") return B.some(b => ["mac-yedek-eski", "mac-yedek-yok"].includes(b.id)) ? "uyari" : "iyi";
  if (id === "denetci" || id === "panel") return "iyi";
  if (arac) return arac.son_etkinlik && (Date.now() / 1000 - arac.son_etkinlik) < 7 * 86400 ? "iyi" : "uyari";
  return "uyari";
}
function akis() {
  const s = document.getElementById("akis-svg"); s.replaceChildren();
  const defs = sv("defs");
  const m = sv("marker", { id: "uc", viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" });
  m.append(sv("path", { d: "M0,0 L10,5 L0,10 z", fill: "currentColor", class: "ok-ucu" }));
  defs.append(m); s.append(defs);
  const kutular = [[20, 20, 310, 410, "Mac (MacBook)"], [20, 470, 310, 170, "Tarayıcı / telefon"], [640, 20, 340, 620, "Sunucu (VPS)"]];
  for (const [x, y, w, h, t] of kutular) {
    s.append(sv("rect", { x, y, width: w, height: h, class: "kutu" }));
    s.append(sv("text", { x: x + 14, y: y + 22, class: "kutu-baslik" }, t));
  }
  const renk = { iyi: "var(--iyi)", uyari: "var(--uyari)", kotu: "var(--kotu)" };
  for (const a of RAPOR.envanter.akislar) {
    const k = KONUM[a.kaynak], h = KONUM[a.hedef];
    if (!k || !h) continue;
    let d;
    if (h[0] === k[0]) {   // aynı sütun: düğümlerin sağından yay (aradaki düğümlerin üstünden geçmesin)
      const x = k[0] + 118, bulge = x + 40 + Math.min(60, Math.abs(h[1] - k[1]) / 6);
      d = `M${x},${k[1]} C${bulge},${k[1]} ${bulge},${h[1]} ${x + 2},${h[1]}`;
    } else {
      const x1 = k[0] + (h[0] > k[0] ? 120 : -120), x2 = h[0] + (h[0] > k[0] ? -120 : 120), mx = (x1 + x2) / 2;
      d = `M${x1},${k[1]} C${mx},${k[1]} ${mx},${h[1]} ${x2},${h[1]}`;
    }
    const p = sv("path", { d, class: "ok", "marker-end": "url(#uc)" });
    p.style.color = "var(--soluk)";
    p.append(sv("title", {}, `${a.kaynak} → ${a.hedef}: ${a.ne} (${a.yol})`));
    s.append(p);
  }
  for (const [id, [x, y, ad]] of Object.entries(KONUM)) {
    const d = dugumDurum(id);
    const g = sv("g");
    const kutu = sv("rect", { x: x - 118, y: y - 18, width: 236, height: 36, class: "dugum" });
    kutu.style.stroke = renk[d];
    const isik = sv("circle", { cx: x - 102, cy: y, r: 5 });
    isik.style.fill = renk[d];
    g.append(kutu, isik);
    g.append(sv("text", { x: x - 90, y: y + 5 }, ad));
    s.append(g);
  }
  const l = document.getElementById("akis-liste"); l.replaceChildren();
  const t = el("table", {}, el("tr", {}, el("th", {}, "Nereden"), el("th", {}, "Nereye"), el("th", {}, "Yol"), el("th", {}, "Ne taşınıyor")));
  for (const a of RAPOR.envanter.akislar)
    t.append(el("tr", {}, el("td", {}, (KONUM[a.kaynak] || [0, 0, a.kaynak])[2]), el("td", {}, (KONUM[a.hedef] || [0, 0, a.hedef])[2]), el("td", {}, a.yol), el("td", {}, a.ne)));
  l.append(el("h2", { style: null }, " "), el("div", { class: "tablo-sar" }, t));
}

function dl(ciftler) {
  const d = el("dl");
  for (const [k, v] of ciftler) if (v !== undefined && v !== null && v !== "") d.append(el("dt", {}, k), el("dd", {}, String(v)));
  return d;
}
function cihazlar() {
  const l = document.getElementById("cihaz-liste"); l.replaceChildren();
  const AD = { macos: "macOS", python: "Python", katip_surumu: "Kâtip sürümü", istemci_surumu: "İstemci sürümü", hooklar: "COUNCIL hook'ları",
    yedek_isi: "Günlük yedek işi", son_yedek_cekim: "Son yedek çekimi", filevault: "FileVault", gizli_dosya_izinleri: "Gizli dosya izinleri",
    anahtar_dosyasi: "Veritabanı anahtarı kopyası", claude_code: "Claude Code", antigravity: "Antigravity", hermes_masaustu: "Hermes masaüstü" };
  for (const c of RAPOR.cihazlar || RAPOR.envanter.cihazlar) {
    const kart = el("div", { class: "kart" }, el("h2", {}, c.ad), el("p", { class: "soluk" }, c.tur), el("p", {}, c.rol));
    const ek = [["Araçlar", (c.araclar || []).join(", ")]];
    if (c.id === "vps" && RAPOR.sunucu) {
      const v = RAPOR.sunucu;
      ek.push(["İşletim sistemi", v.isletim], ["RAM", `${v.ram_bos_mb} / ${v.ram_mb} MB boş`], ["Disk", `%${v.disk_doluluk} dolu`],
        ["Açık kalma", `${v.acik_kalma_gun} gün`]);
    }
    if (c.rapor) {
      ek.push(["Rapor zamanı", `${zaman(c.rapor_zamani)} (${once(c.rapor_zamani)})`]);
      for (const [k, v] of Object.entries(c.rapor)) ek.push([AD[k] || k, v === true ? "açık / var" : v === false ? "KAPALI" : v]);
    } else if (c.id === "mac") ek.push(["Rapor", "henüz gelmedi"]);
    kart.append(dl(ek));
    l.append(kart);
  }
}
function araclar() {
  const t = document.getElementById("arac-tablo"); t.replaceChildren();
  t.append(el("tr", {}, ["Araç", "Cihaz", "Görevi", "Hafızadaki kimliği", "Bağlantı", "Token kapsamı", "Son etkinlik"].map(h => el("th", {}, h))));
  for (const a of RAPOR.araclar || []) {
    const d = dugumDurum(a.id);
    t.append(el("tr", {},
      el("td", {}, el("span", { class: "nokta n-" + d }), a.ad, a.ic ? el("div", { class: "soluk" }, "iç ajan") : null),
      el("td", {}, a.cihaz), el("td", {}, a.gorev), el("td", {}, a.kimlik || "—"), el("td", {}, a.baglanti),
      el("td", {}, a.token ? (a.token.projeler === "*" ? "bütün projeler" : a.token.projeler) : "—"),
      el("td", {}, a.son_etkinlik ? `${once(a.son_etkinlik)}` : "hiç")));
  }
}
function durum() {
  const l = document.getElementById("durum-liste"); l.replaceChildren();
  const s = RAPOR.sunucu || {}, h = RAPOR.hafiza || {}, he = RAPOR.hermes || {}, m = RAPOR.model || {};
  l.append(el("div", { class: "kart" }, el("h2", {}, "Sunucu"), dl([
    ["Servisler", Object.entries(s.servisler || {}).map(([k, v]) => `${k}: ${v}`).join(" · ")],
    ["Güncelleme", `${s.guncelleme ?? "?"} paket (${s.guvenlik_guncellemesi ?? "?"} güvenlik)`],
    ["Otomatik güvenlik güncellemesi", s.otomatik_guvenlik], ["Yeniden başlatma", s.yeniden_baslatma ? "bekliyor" : "gerekmiyor"],
    ["HTTPS sertifikası", s.sertifika_gun !== undefined ? `${s.sertifika_gun} gün kaldı` : "?"],
    ["SSH", s.ssh ? Object.entries(s.ssh).map(([k, v]) => `${k}=${v}`).join(", ") : "?"],
    ["Başarısız SSH (24 sa)", s.ssh_basarisiz_24s], ["Güvenlik duvarı", s.guvenlik_duvari], ["Dışa açık portlar", (s.dis_portlar || []).join(", ")]])));
  l.append(el("div", { class: "kart" }, el("h2", {}, "Hafıza"), dl([
    ["Güncel kayıt", `${h.kayit_guncel} (toplam ${h.kayit_toplam}, projeye özel ${h.projeye_ozel})`],
    ["Projeler", Object.entries(h.projeler || {}).map(([k, v]) => `${k} ${v}`).join(" · ")],
    ["Değişiklik günlüğü", `${h.olay} olay · zincir ${h.zincir ? "sağlam" : "BOZUK"}`], ["Disk şifreleme", h.sifreli ? "açık (SQLCipher)" : "KAPALI"],
    ["Sunucu yedeği", h.yedek ? `${h.yedek.son} · ${h.yedek.yas_saat} sa önce · ${h.yedek.sifreli ? "şifreli" : "ŞİFRESİZ"}` : "yok"],
    ["Mac yedeği", h.mac_yedek_yas_saat !== undefined ? `${h.mac_yedek_yas_saat} sa önce` : "hiç"],
    ["Yönlendirme gözlemi", h.yonlendirme_gozlem], ["Kimlik tanımı", h.kimlik_sayisi]])));
  const gorev = el("div", { class: "kart" }, el("h2", {}, "Açık görevler (hafızadan)"));
  if (!(h.acik_gorevler || []).length) gorev.append(el("p", { class: "soluk" }, "Açık görev yok."));
  for (const g of h.acik_gorevler || []) gorev.append(el("p", {}, el("b", {}, g.id + " "), g.metin, el("span", { class: "soluk" }, ` (${g.tarih}, ${g.proje})`)));
  l.append(gorev);
  l.append(el("div", { class: "kart" }, el("h2", {}, "Hermes ve model denetimi"), dl([
    ["hermes kullanıcısı", he.kullanici ? (he.sudo ? "VAR · sudo yetkili!" : "var · sudo yok") : "yok"],
    ["Hafıza dosyasını okuyabilir", he.db_okuyabilir ? "EVET" : "hayır"],
    ["Hermes token kapsamı", Array.isArray(he.token_projeleri) ? he.token_projeleri.join(", ") : he.token_projeleri],
    ["Model katmanı (çelişki taraması)", `${m.durum || "?"}${m.neden ? " — " + m.neden : ""}${m.oneri !== undefined ? ` · ${m.oneri} öneri` : ""}`],
    ["Denetim süresi", `${RAPOR.sure_sn} sn`]])));
}
function gecmis(g) {
  const k = document.getElementById("gecmis-grafik"); k.replaceChildren();
  if (!g.length) { k.append(el("p", { class: "soluk" }, "Geçmiş yok.")); return; }
  const enCok = Math.max(1, ...g.map(x => CID.reduce((a, c) => a + (x.ozet[c] || 0), 0)));
  for (const x of g) {
    const sut = el("div", { class: "sutun" });
    sut.style.height = "180px";
    for (const c of CID) {
      const n = x.ozet[c] || 0;
      if (!n) continue;
      const p = el("span", { class: "r-" + c, title: `${CID_AD[c]}: ${n}` });
      p.style.height = (160 * n / enCok) + "px";
      sut.append(p);
    }
    const d = new Date(x.zaman);
    k.append(el("div", { class: "sutun-sar" }, sut, el("div", { class: "sutun-etiket" }, `${d.getDate()}.${d.getMonth() + 1} ${String(d.getHours()).padStart(2, "0")}`)));
  }
}

document.getElementById("sekmeler").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  for (const x of document.querySelectorAll(".sekmeler button")) x.classList.toggle("secili", x === b);
  for (const s of document.querySelectorAll(".sekme")) s.classList.toggle("gizli", s.id !== "s-" + b.dataset.s);
});
yukle().catch(e => { document.getElementById("zaman").textContent = "Rapor yüklenemedi: " + e; });
