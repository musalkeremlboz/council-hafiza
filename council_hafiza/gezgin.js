// COUNCIL Gezgin: hafıza kayıtlarını listeler, süzer, arar, düzeltir, birleştirir, arşivler.
// Kayıt verisi yalnız textContent ile yazılır (HTML olarak değil). Yazma istekleri JSON + X-CSRF ile gider.
"use strict";

const TUR = { fact: "bilgi", event: "olay", plan: "plan", preference: "tercih", decision: "karar", task: "görev", procedure: "yöntem" };
const GOR = { shared: "ortak", project: "projeye özel" };
const GUV = { user: "kullanıcı", agent: "ajan", external: "dış kaynak" };
const DUR = { guncel: "güncel", eski: "eski", arsiv: "arşiv" };
const ISLEM = { kaydet: "kaydedildi", gecersiz_kil: "geçersiz kılındı", arsivle: "arşivlendi", arsivden_cikar: "arşivden çıkarıldı",
  duzelt: "düzeltmeyle yazıldı", birlestir: "birleştirmeyle yazıldı" };
const SVGNS = "http://www.w3.org/2000/svg";

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) e.append(k instanceof Node ? k : String(k));
  return e;
}
const $ = (id) => document.getElementById(id);
function tarih(r) { return r.tarih; }
function zaman(t) { return new Date(t * 1000).toLocaleString("tr-TR", { dateStyle: "medium", timeStyle: "short" }); }

// ---------------------------------------------------------------- durum
const S = { durum: "guncel", sayfa: 0, secili: new Set(), acik: null, veri: null, oneriler: [], csrf: "", kayitOnbellek: new Map(), acan: null };
const GUVEN_SIRA = { external: 0, agent: 1, user: 2 };
function secimdenCikar(...ids) { for (const i of ids) S.secili.delete(i); secimCiz(); listeIsaretle(); }

async function api(yol, govde) {
  const ayar = { credentials: "same-origin", headers: {} };
  if (govde !== undefined) {
    ayar.method = "POST";
    ayar.headers["Content-Type"] = "application/json";
    ayar.headers["X-CSRF"] = S.csrf;
    ayar.body = JSON.stringify(govde);
  }
  const r = await fetch(yol, ayar);
  if (r.status === 401) { location.href = "/panel"; throw new Error("Oturum kapandı."); }
  let v = {};
  try { v = await r.json(); } catch (_) { v = {}; }
  if (!r.ok) throw new Error(v.hata || `İstek başarısız (${r.status}).`);
  return v;
}

let bildirimZaman = null;
function bildir(m, kotu) {
  const b = $("bildirim");
  b.classList.toggle("kotu", !!kotu); b.classList.remove("sakli");
  b.textContent = ""; requestAnimationFrame(() => { b.textContent = m; });
  clearTimeout(bildirimZaman); bildirimZaman = setTimeout(() => b.classList.add("sakli"), 4200);
}

// ---------------------------------------------------------------- liste
function parametreler() {
  const p = new URLSearchParams();
  const ekle = (k, v) => { if (v) p.set(k, v); };
  ekle("q", $("q").value.trim()); ekle("proje", $("f-proje").value); ekle("arac", $("f-arac").value); ekle("tur", $("f-tur").value);
  ekle("bas", $("f-bas").value); ekle("son", $("f-son").value); ekle("sira", $("f-sira").value);
  p.set("durum", S.durum); p.set("sayfa", String(S.sayfa));
  return p;
}

let istekNo = 0;
async function listele() {
  const no = ++istekNo;
  $("liste-bilgi").textContent = "Yükleniyor…";
  let v;
  try { v = await api("/panel/gezgin/kayitlar?" + parametreler().toString()); }
  catch (e) { if (no === istekNo) $("liste-bilgi").textContent = e.message; return; }
  if (no !== istekNo) return;
  S.veri = v; S.sayfa = v.sayfa;
  secenekleriDoldur(v.secenekler);
  const d = v.secenekler.durum;
  $("sayac").textContent = `${v.hepsi} kayıt · ${d.guncel} güncel · ${d.eski} eski · ${d.arsiv} arşiv`;
  const bas = v.toplam ? v.sayfa * v.boyut + 1 : 0, son = Math.min(v.toplam, (v.sayfa + 1) * v.boyut);
  $("liste-bilgi").textContent = v.toplam ? `${v.toplam} kayıttan ${bas}–${son} gösteriliyor` + ($("q").value.trim() ? " · ilgiye göre sıralı" : "")
    : "Bu süzgeçlerle eşleşen kayıt yok. Süzgeçleri gevşet ya da aramayı değiştir.";
  const ol = $("liste"); ol.replaceChildren();
  for (const r of v.kayitlar) { S.kayitOnbellek.set(r.id, r); ol.append(satir(r)); }
  sayfalar(v);
}

function satir(r) {
  const kutu = el("input", { type: "checkbox", "aria-label": `${r.id} seç`, disabled: r.durum !== "guncel" ? true : null });
  kutu.checked = S.secili.has(r.id);
  kutu.addEventListener("click", (e) => { e.stopPropagation(); kutu.checked ? S.secili.add(r.id) : S.secili.delete(r.id); secimCiz(); });
  const li = el("li", { class: `satir ${r.durum}${S.acik === r.id ? " acik" : ""}`, tabindex: "0", role: "button", "aria-label": `${r.id} kaydını aç`, "data-id": r.id },
    kutu,
    el("div", {},
      el("div", { class: "satir-ust" },
        el("span", { class: "kimlik" }, r.id),
        el("span", { class: "rozet" }, TUR[r.tur] || r.tur),
        r.durum !== "guncel" ? el("span", { class: `rozet ${r.durum}` }, DUR[r.durum]) : null,
        r.gorunurluk === "project" ? el("span", { class: "rozet ozel" }, "özel") : null,
        el("span", { class: "meta" }, `${tarih(r)} · ${r.arac}/${r.proje}`)),
      el("div", { class: "ozet" }, r.metin)));
  li.addEventListener("click", () => ac(r.id, li));
  li.addEventListener("keydown", (e) => { if (e.target === li && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); ac(r.id, li); } });
  return li;
}

function sayfalar(v) {
  const s = $("sayfalar"); s.replaceChildren();
  const toplamSayfa = Math.ceil(v.toplam / v.boyut);
  if (toplamSayfa <= 1) return;
  const git = (n) => { S.sayfa = n; listele(); $("liste-bilgi").scrollIntoView({ block: "start" }); };
  s.append(
    el("button", { type: "button", class: "dugme ikincil", disabled: v.sayfa === 0 ? true : null, onclick: () => git(v.sayfa - 1) }, "← Önceki"),
    el("span", { class: "meta" }, `Sayfa ${v.sayfa + 1} / ${toplamSayfa}`),
    el("button", { type: "button", class: "dugme ikincil", disabled: v.sayfa + 1 >= toplamSayfa ? true : null, onclick: () => git(v.sayfa + 1) }, "Sonraki →"));
}

function secenekleriDoldur(sec) {
  const doldur = (id, sozluk, adlar) => {
    const s = $(id), onceki = s.value;
    s.replaceChildren(el("option", { value: "" }, "Hepsi"));
    for (const [k, n] of Object.entries(sozluk)) s.append(el("option", { value: k }, `${adlar ? (adlar[k] || k) : k} (${n})`));
    s.value = onceki in sozluk || onceki === "" ? onceki : "";
  };
  doldur("f-proje", sec.proje); doldur("f-arac", sec.arac); doldur("f-tur", sec.tur, TUR);
}

function secimCiz() {
  const n = S.secili.size;
  $("secim").classList.toggle("gizli", n === 0);
  $("secim-say").textContent = `${n} kayıt seçili`;
  $("birlestir-ac").disabled = n < 2;
  $("birlestir-ac").textContent = n < 2 ? "Birleştirmek için en az 2 seç" : `${n} kaydı birleştir`;
}

// ---------------------------------------------------------------- ayrıntı
const DAR = matchMedia("(max-width: 1000px)");
const dar = () => DAR.matches;
const ARKA = () => [document.querySelector(".ust"), document.querySelector(".sekmeler"), $("suzgec"), $("secim"), document.querySelector(".liste-sar")];
const gecmisteAcik = () => !!(history.state && history.state.gezginAyrinti);
// Ayrıntı açık ve ekran darsa tam ekran iletişim kutusudur: arka plan etkisizleşir, Geri tuşu onu kapatır.
// Ekran genişleyince (pencere büyür, tablet yan döner) yan panele döner ve arka plan yeniden kullanılır.
function kutuDurumu() {
  const a = $("ayrinti"), kutu = a.classList.contains("acik") && dar();
  if (kutu) { a.setAttribute("role", "dialog"); a.setAttribute("aria-modal", "true"); a.setAttribute("aria-label", "Kayıt ayrıntısı"); }
  else { a.removeAttribute("role"); a.removeAttribute("aria-modal"); a.removeAttribute("aria-label"); }
  ARKA().forEach((x) => x && (x.inert = kutu));
  if (kutu && !gecmisteAcik()) history.pushState({ gezginAyrinti: true }, "");
}
function ayrintiAc() {
  $("ayrinti").classList.add("acik");
  kutuDurumu();
}
function ayrintiOdak() { const h = $("ayrinti").querySelector(".a-baslik"); if (h) { h.setAttribute("tabindex", "-1"); h.focus({ preventScroll: !dar() }); } }
function ayrintiKapat() {
  if (gecmisteAcik()) { history.back(); return; }      // Geri ile aynı yol: popstate kapatır
  ayrintiGizle();
}
function ayrintiGizle() {
  const son = S.acik;
  $("ayrinti").classList.remove("acik");
  kutuDurumu();
  S.acik = null;
  document.querySelectorAll(".satir.acik").forEach((x) => x.classList.remove("acik"));
  // odak: açan satır hâlâ sayfadaysa ona; liste yeniden çizildiyse aynı kaydın yeni satırına; o da yoksa liste bilgisine
  let hedef = S.acan && document.contains(S.acan) ? S.acan : null;
  if (!hedef && son) hedef = [...document.querySelectorAll(".satir")].find((x) => x.dataset.id === son) || null;
  if (!hedef) { hedef = $("liste-bilgi"); hedef.setAttribute("tabindex", "-1"); }
  hedef.focus();
}

async function ac(id, acan) {
  S.acik = id; if (acan) S.acan = acan;
  document.querySelectorAll(".satir").forEach((x) => x.classList.toggle("acik", x.dataset.id === id));
  const a = $("ayrinti");
  a.replaceChildren(el("p", { class: "bilgi" }, `${id} yükleniyor…`)); ayrintiAc();
  let v;
  try { v = await api(`/panel/gezgin/kayit/${encodeURIComponent(id)}`); }
  catch (e) { if (S.acik === id) a.replaceChildren(el("p", { class: "bilgi hata" }, e.message)); return; }
  if (S.acik !== id) return;
  ayrintiCiz(v); ayrintiOdak();
}

function kapatDugmesi() {
  return el("button", { type: "button", class: "dugme ikincil kapat", onclick: ayrintiKapat }, "← Listeye dön");
}

function ayrintiCiz(v) {
  const r = v.kayit, a = $("ayrinti");
  const alan = (et, deger) => el("div", {}, el("span", { class: "et" }, et), deger || "—");
  const zincirListe = (liste) => el("ul", { class: "zincir" }, liste.map((x) =>
    el("li", {}, el("button", { type: "button", onclick: () => ac(x.id) }, `${x.id} · ${DUR[x.durum]} · ${x.metin.slice(0, 140)}`))));
  const islemler = el("div", { class: "islemler" });
  if (r.durum === "guncel") {
    islemler.append(
      el("button", { type: "button", class: "dugme vurgu", onclick: () => duzeltFormu(r) }, "Düzelt"),
      el("button", { type: "button", class: "dugme ikincil", onclick: () => { S.secili.add(r.id); secimCiz(); listeIsaretle(); bildir(`${r.id} birleştirme seçimine eklendi.`); } }, "Birleştirmeye ekle"),
      el("button", { type: "button", class: "dugme tehlike", onclick: () => arsivFormu(r) }, "Arşivle"));
  } else if (r.durum === "arsiv") {
    islemler.append(el("button", { type: "button", class: "dugme vurgu", onclick: (e) => arsivdenCikar(r, e.currentTarget) }, "Arşivden çıkar"));
  } else {
    islemler.append(el("span", { class: "not" }, r.yerine ? `Bu kaydın yerine ${r.yerine} geçti; düzeltme güncel kayıtta yapılır.` : "Bu kayıt geçersiz kılınmış."));
    if (r.yerine) islemler.append(el("button", { type: "button", class: "dugme ikincil", onclick: () => ac(r.yerine) }, `${r.yerine} kaydını aç`));
  }
  a.replaceChildren(...[
    el("div", { class: "a-ust" },
      el("div", {}, el("div", { class: "a-baslik" }, r.id), el("div", { class: "meta" }, `${TUR[r.tur] || r.tur} · ${DUR[r.durum]}`)),
      kapatDugmesi()),
    el("div", { class: "a-metin" }, r.metin),
    el("div", { class: "a-baglam" }, r.baglam),
    el("div", { class: "anahtarlar" }, r.anahtarlar.map((k) => el("span", {}, k))),
    el("div", { class: "alanlar" },
      alan("Tarih", tarih(r)), alan("Araç", r.arac), alan("Proje", r.proje),
      alan("Görünürlük", GOR[r.gorunurluk]), alan("Güven", GUV[r.guven]), alan("Yazıldı", zaman(r.olusturma)),
      r.bitis ? alan("Geçerlilik bitişi", r.bitis) : null, r.arsiv_neden ? alan("Arşiv nedeni", r.arsiv_neden) : null),
    el("div", { id: "form-yeri" }),
    islemler,
    v.ardil.length ? el("div", { class: "blok" }, el("h3", {}, "Yerine geçenler"), zincirListe(v.ardil)) : null,
    v.oncul.length ? el("div", { class: "blok" }, el("h3", {}, "Bunun yerine geçtiği kayıtlar"), zincirListe(v.oncul)) : null,
    el("div", { class: "blok" }, el("h3", {}, "Geçmiş"),
      el("ol", { class: "gecmis" }, v.gecmis.map((g) => el("li", { class: g.arac === "gezgin" ? "vurgu" : "" },
        el("span", { class: "ne" }, ISLEM[g.islem] || g.islem), ` · ${zaman(g.zaman)} · ${g.arac || "?"}`,
        g.ayrinti.neden ? el("div", { class: "not" }, g.ayrinti.neden) : null,
        g.ayrinti.yerine ? el("div", { class: "not" }, `yerine: ${g.ayrinti.yerine}`) : null,
        g.ayrinti.kaynaklar ? el("div", { class: "not" }, `kaynaklar: ${g.ayrinti.kaynaklar.join(", ")}`) : null))))].filter(Boolean));
}

function listeIsaretle() {
  document.querySelectorAll(".satir").forEach((x) => { const k = x.querySelector("input"); if (k) k.checked = S.secili.has(x.dataset.id); });
}

// ---------------------------------------------------------------- formlar
function secim(id, sozluk, deger) {
  const s = el("select", { id });
  for (const [k, ad] of Object.entries(sozluk)) s.append(el("option", { value: k }, ad));
  s.value = deger; return s;
}
function kayitAlanlari(r, onEk) {
  const metin = el("textarea", { id: onEk + "-metin", required: true, maxlength: "4000" }); metin.value = r.metin;
  const baglam = el("input", { id: onEk + "-baglam", maxlength: "1000" }); baglam.value = r.baglam || "";
  const anah = el("input", { id: onEk + "-anahtar" }); anah.value = (r.anahtarlar || []).join(", ");
  const tarihK = el("input", { id: onEk + "-tarih", type: "date" }); tarihK.value = r.tarih || "";
  // projeye özel bir kaydı ortak yapmak (bütün projelere açmak) açık onay ister; sunucu da onaysız isteği reddeder
  const gorSec = secim(onEk + "-gor", GOR, r.gorunurluk);
  const acKutu = el("input", { type: "checkbox", id: onEk + "-gor-onay" });
  const acSatir = el("label", { class: "onay-satir gizli" }, acKutu,
    el("span", {}, "Bu kaydı bütün projelere açıyorum (şu an yalnız kendi projesinde görünüyor)."));
  gorSec.addEventListener("change", () => {
    const gerek = r.gorunurluk === "project" && gorSec.value === "shared";
    acSatir.classList.toggle("gizli", !gerek);
    if (!gerek) acKutu.checked = false;
  });
  const alanlar = el("div", { class: "form-alanlar" },
    el("label", {}, el("span", { class: "et" }, "Metin"), metin),
    el("label", {}, el("span", { class: "et" }, "Bağlam"), baglam),
    el("label", {}, el("span", { class: "et" }, "Arama anahtarları (virgülle)"), anah),
    el("div", { class: "dort" },
      el("label", {}, el("span", { class: "et" }, "Tür"), secim(onEk + "-tur", TUR, r.tur)),
      el("label", {}, el("span", { class: "et" }, "Görünürlük"), gorSec),
      el("label", {}, el("span", { class: "et" }, "Güven"), secim(onEk + "-guv", GUV, r.guven || "user")),
      el("label", {}, el("span", { class: "et" }, "Tarih"), tarihK)),
    acSatir,
    el("p", { class: "not" }, "Güveni yükseltirsen (ör. dış kaynak → kullanıcı) bilgiyi doğruladığını onaylamış olursun."));
  const oku = () => ({ metin: metin.value, baglam: baglam.value, anahtarlar: anah.value.split(",").map((x) => x.trim()).filter(Boolean),
    tur: $(onEk + "-tur").value, gorunurluk: $(onEk + "-gor").value, guven: $(onEk + "-guv").value, tarih: tarihK.value,
    guven_onay: GUVEN_SIRA[$(onEk + "-guv").value] > GUVEN_SIRA[r.guven || "user"], gorunurluk_onay: acKutu.checked });
  return { alanlar, oku, odak: () => metin.focus() };
}

function formKur(baslik, aciklama, govdeler, gonderAd, gonder) {
  const hata = el("p", { class: "hata", role: "alert" });
  const neden = el("input", { id: "f-neden", maxlength: "300", placeholder: "Kısaca neden (geçmişte görünür)" });
  const btn = el("button", { type: "submit", class: "dugme vurgu" }, gonderAd);
  const f = el("form", { class: "form" }, el("h3", {}, baslik), aciklama ? el("p", { class: "not" }, aciklama) : null, govdeler,
    el("label", {}, el("span", { class: "et" }, "Neden"), neden), hata,
    el("div", { class: "alt" }, btn, el("button", { type: "button", class: "dugme ikincil", onclick: () => f.remove() }, "Vazgeç")));
  f.addEventListener("submit", async (e) => {
    e.preventDefault(); hata.textContent = ""; btn.disabled = true;
    try { await gonder(neden.value); } catch (err) { hata.textContent = err.message; }
    btn.disabled = false;
  });
  return f;
}

function formYerlestir(f) {
  const yer = $("form-yeri");
  if (!yer) return;
  yer.replaceChildren(f);
  f.scrollIntoView({ block: "nearest" });
}

function duzeltFormu(r) {
  const k = kayitAlanlari(r, "d");
  formYerlestir(formKur("Düzelt", `Düzeltilmiş metin yeni bir kayıt olur; ${r.id} geçersiz kılınır ve geçmişte kalır.`, k.alanlar, "Düzeltmeyi kaydet",
    async (neden) => {
      const v = await api("/panel/gezgin/duzelt", { id: r.id, neden, ...k.oku() });
      secimdenCikar(r.id); bildir(v.mesaj); await yenile(); ac(v.yeni);
    }));
  k.odak();
}

function arsivFormu(r) {
  formYerlestir(formKur("Arşivle", `${r.id} aramalarda görünmez ama silinmez; istediğin zaman arşivden çıkarabilirsin.`, [], "Arşivle",
    async (neden) => {
      if (neden.trim().length < 3) throw new Error("Arşivleme nedeni yaz.");
      const v = await api("/panel/gezgin/arsivle", { id: r.id, neden });
      secimdenCikar(r.id); bildir(v.mesaj); await yenile(); ac(r.id);
    }));
  $("f-neden").focus();
}

async function arsivdenCikar(r, dugme) {
  if (dugme) dugme.disabled = true;                      // çift dokunuşta ikinci istek gitmesin
  try { const v = await api("/panel/gezgin/arsivden-cikar", { id: r.id, neden: "Gezgin'den geri alındı" }); bildir(v.mesaj); await yenile(); ac(r.id); }
  catch (e) { bildir(e.message, true); if (dugme) dugme.disabled = false; }
}

async function birlestirFormu(ids) {
  const kayitlar = [];
  for (const id of ids) {
    let r = S.kayitOnbellek.get(id);
    if (!r) { try { r = (await api(`/panel/gezgin/kayit/${encodeURIComponent(id)}`)).kayit; } catch (_) { r = null; } }
    if (r) kayitlar.push(r);
  }
  const eskimis = kayitlar.filter((x) => x.durum !== "guncel");
  if (eskimis.length) {
    secimdenCikar(...eskimis.map((x) => x.id));
    bildir(`${eskimis.map((x) => x.id).join(", ")} artık güncel değil; seçimden çıkarıldı.`, true);
    kayitlar.splice(0, kayitlar.length, ...kayitlar.filter((x) => x.durum === "guncel"));
  }
  if (kayitlar.length < 2) { bildir("Birleştirmek için en az 2 güncel kayıt gerekli.", true); return; }
  // sunucunun her durumda reddedeceği seçimler (gezgin.py kural_denetle): formu hiç açma
  const ozel = kayitlar.filter((x) => x.gorunurluk === "project");
  if (ozel.length && ozel.length < kayitlar.length) { bildir("Projeye özel ve ortak kayıtlar birleştirilemez (özel bilgi öbür projelere taşınır).", true); return; }
  if (new Set(ozel.map((x) => x.proje)).size > 1) { bildir("Farklı projelerin projeye özel kayıtları birleştirilemez.", true); return; }
  kayitlar.sort((x, y) => tarih(y).localeCompare(tarih(x)) || y.olusturma - x.olusturma);
  const enYeni = kayitlar[0];
  const temel = { ...enYeni, metin: kayitlar.map((x) => x.metin).join("\n"),
    anahtarlar: [...new Set(kayitlar.flatMap((x) => x.anahtarlar))].slice(0, 12),
    gorunurluk: kayitlar.some((x) => x.gorunurluk === "shared") ? "shared" : enYeni.gorunurluk,
    guven: kayitlar.reduce((m, x) => (GUVEN_SIRA[x.guven] < GUVEN_SIRA[m] ? x.guven : m), "user") };
  const k = kayitAlanlari(temel, "b");
  S.acik = null;
  const a = $("ayrinti");
  a.replaceChildren(...[
    el("div", { class: "a-ust" }, el("div", {}, el("div", { class: "a-baslik" }, "Birleştir"), el("div", { class: "meta" }, `${kayitlar.length} kayıt`)), kapatDugmesi()),
    el("div", { class: "blok" }, el("h3", {}, "Kaynaklar"),
      el("ul", { class: "kaynaklar" }, kayitlar.map((x) => el("li", {}, el("b", {}, x.id), ` · ${tarih(x)} · ${x.arac}/${x.proje} · `, x.metin)))),
    el("div", { id: "form-yeri" })].filter(Boolean));
  ayrintiAc(); ayrintiOdak();
  formYerlestir(formKur("Birleşik kayıt", "Metni tek ve kendi başına anlaşılır bir bilgiye indir. Kaynakların hepsi geçersiz kılınır, silinmez.",
    k.alanlar, "Birleştir", async (neden) => {
      const v = await api("/panel/gezgin/birlestir", { ids: kayitlar.map((x) => x.id), neden, ...k.oku() });
      S.secili.clear(); secimCiz(); bildir(v.mesaj); await yenile(); ac(v.yeni);
    }));
}

// ---------------------------------------------------------------- öneriler
async function onerileriYukle() {
  let hata = "";
  try { S.oneriler = (await api("/panel/gezgin/oneriler")).oneriler; } catch (e) { S.oneriler = []; hata = e.message; }
  const acik = S.oneriler.filter((o) => o.acik).length;
  $("oneri-say").textContent = acik ? String(acik) : "";
  onerileriCiz(hata);
}

function onerileriCiz(hata) {
  const k = $("oneri-liste"); k.replaceChildren();
  if (hata) { k.append(el("p", { class: "aciklama hata", role: "alert" }, `Öneriler yüklenemedi: ${hata}`)); return; }
  if (!S.oneriler.length) {
    k.append(el("p", { class: "aciklama" }, "Şu an öneri yok. Denetim ajanı günde üç kez (08:00, 14:00, 20:00) hafızayı tarar; bulduğu çelişkiler burada görünür."));
    return;
  }
  const sirali = [...S.oneriler].sort((a, b) => (b.acik - a.acik));
  for (const o of sirali) k.append(oneriKart(o));
}

function oneriKart(o) {
  const islem = el("div", { class: "o-islem" });
  const kart = el("article", { class: "oneri" + (o.acik ? "" : " kapali") },
    el("div", { class: "o-ust" }, el("span", { class: "rozet" }, { celiski: "çelişki", tekrar: "tekrar", tamamlandi: "tamamlanmış", gorev: "açık görev" }[o.tur] || o.tur),
      el("span", { class: "o-baslik" }, o.baslik)),
    o.ayrinti ? el("p", { class: "o-ayrinti" }, o.ayrinti) : null,
    el("div", { class: "o-kayitlar" }, o.kayitlar.map((r) => el("div", { class: "o-kayit" },
      el("div", { class: "satir-ust" }, el("span", { class: "kimlik" }, r.id), el("span", { class: `rozet ${r.durum}` }, DUR[r.durum])),
      el("div", { class: "meta" }, `${tarih(r)} · ${r.arac}/${r.proje} · ${TUR[r.tur] || r.tur}`),
      el("div", {}, r.metin),
      el("button", { type: "button", class: "dugme ikincil", onclick: () => { gorunum("kayitlar"); ac(r.id); } }, "Aç")))),
    islem);
  if (!o.acik) { islem.append(el("span", { class: "not" }, "Bu öneri çözülmüş: kayıtlardan en az biri artık güncel değil.")); return kart; }
  const guncel = o.kayitlar.filter((r) => r.durum === "guncel");
  if (guncel.length >= 2) {
    const sirali = [...guncel].sort((x, y) => tarih(x).localeCompare(tarih(y)) || x.olusturma - y.olusturma);
    const eski = sirali[0], yeni = sirali[sirali.length - 1];
    islem.append(
      el("button", { type: "button", class: "dugme vurgu", onclick: () => { gorunum("kayitlar"); birlestirFormu(guncel.map((r) => r.id)); } }, "Birleştir"),
      el("button", { type: "button", class: "dugme ikincil", onclick: () => onayla(islem, `${eski.id} geçersiz kılınsın, yerine ${yeni.id} geçsin mi?`,
        async () => { const v = await api("/panel/gezgin/gecersiz-kil", { eski: eski.id, yeni: yeni.id, neden: o.baslik.slice(0, 200) }); secimdenCikar(eski.id); bildir(v.mesaj); await yenile(); }) },
        `Eskisini geçersiz kıl (${eski.id} → ${yeni.id})`));
  }
  for (const r of guncel) {
    islem.append(el("button", { type: "button", class: "dugme tehlike", onclick: () => onayla(islem, `${r.id} arşivlensin mi? Silinmez, istediğinde geri alınır.`,
      async () => { const v = await api("/panel/gezgin/arsivle", { id: r.id, neden: o.baslik.slice(0, 200) }); secimdenCikar(r.id); bildir(v.mesaj); await yenile(); }) }, `${r.id} arşivle`));
  }
  return kart;
}

function onayla(yer, soru, is) {
  yer.querySelector(".onay")?.remove();
  const evet = el("button", { type: "button", class: "dugme" }, "Evet");
  const kutu = el("div", { class: "onay", role: "alertdialog" }, el("span", {}, soru), evet,
    el("button", { type: "button", class: "dugme ikincil", onclick: () => kutu.remove() }, "Vazgeç"));
  evet.addEventListener("click", async () => {
    evet.disabled = true;
    try { await is(); kutu.remove(); } catch (e) { bildir(e.message, true); evet.disabled = false; }
  });
  yer.prepend(kutu);
  evet.focus();
}

// ---------------------------------------------------------------- genel
function gorunum(ad) {
  document.querySelectorAll(".sekmeler button").forEach((b) => { b.classList.toggle("secili", b.dataset.g === ad); b.setAttribute("aria-selected", String(b.dataset.g === ad)); });
  $("g-kayitlar").classList.toggle("gizli", ad !== "kayitlar");
  $("g-oneriler").classList.toggle("gizli", ad !== "oneriler");
}

async function yenile() { S.kayitOnbellek.clear(); await Promise.all([listele(), onerileriYukle()]); }

function bagla() {
  document.querySelectorAll(".sekmeler button").forEach((b) => b.addEventListener("click", () => gorunum(b.dataset.g)));
  let bekle = null;
  $("q").addEventListener("input", () => { clearTimeout(bekle); bekle = setTimeout(() => { S.sayfa = 0; listele(); }, 300); });
  for (const id of ["f-proje", "f-arac", "f-tur", "f-bas", "f-son", "f-sira"]) $(id).addEventListener("change", () => { S.sayfa = 0; listele(); });
  document.querySelectorAll("#durumlar button").forEach((b) => b.addEventListener("click", () => {
    S.durum = b.dataset.d; S.sayfa = 0;
    document.querySelectorAll("#durumlar button").forEach((x) => { x.classList.toggle("secili", x === b); x.setAttribute("aria-pressed", String(x === b)); });
    listele();
  }));
  $("suzgec").addEventListener("submit", (e) => { e.preventDefault(); S.sayfa = 0; listele(); });
  $("temizle").addEventListener("click", () => {
    for (const id of ["q", "f-proje", "f-arac", "f-tur", "f-bas", "f-son"]) $(id).value = "";
    $("f-sira").value = "yeni"; S.durum = "guncel"; S.sayfa = 0;
    document.querySelectorAll("#durumlar button").forEach((x) => { x.classList.toggle("secili", x.dataset.d === "guncel"); x.setAttribute("aria-pressed", String(x.dataset.d === "guncel")); });
    listele();
  });
  $("secim-temizle").addEventListener("click", () => { S.secili.clear(); secimCiz(); listeIsaretle(); });
  $("birlestir-ac").addEventListener("click", () => birlestirFormu([...S.secili]));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("ayrinti").classList.contains("acik")) ayrintiKapat(); });
  // sayfa yenilenince tarayıcı eski geçmiş durumunu korur; ayrıntı kapalı açıldığı için işareti temizle
  if (gecmisteAcik()) history.replaceState(null, "");
  DAR.addEventListener("change", kutuDurumu);
  window.addEventListener("popstate", () => { if ($("ayrinti").classList.contains("acik")) ayrintiGizle(); });
}

(async function basla() {
  bagla();
  try { S.csrf = (await api("/panel/gezgin/oturum")).csrf; } catch (e) { bildir(e.message, true); }
  await yenile();
})();
