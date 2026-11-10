// COUNCIL uygulamalarının ortak yardımcıları (U): istek + CSRF, öğe kurma, bildirim, tarih yazımı, pencere (form).
// Veri sayfaya yalnız textContent ile yazılır (HTML olarak değil). Satır içi stil yok; ölçüler CSSOM ile verilir.
"use strict";
const U = (() => {
  const $ = (id) => document.getElementById(id);
  const UYG = document.body.dataset.uyg;

  /** el("div", {class: "x", onclick: fn, disabled: true}, çocuklar...) — null/false çocuklar atlanır. */
  function el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") e.className = v;
      else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
      else if (k === "value") e.value = v;
      else if (k === "checked") e.checked = !!v;
      else e.setAttribute(k, v === true ? "" : v);
    }
    for (const k of kids.flat(Infinity)) if (k !== null && k !== undefined && k !== false) e.append(k instanceof Node ? k : String(k));
    return e;
  }

  // ---------------------------------------------------------------- istek
  let csrf = null;
  async function istek(yol, govde) {
    const secenek = { credentials: "same-origin" };
    if (govde !== undefined) {
      if (!csrf) {
        const o = await fetch("/panel/gezgin/oturum", { credentials: "same-origin" });
        if (o.status === 401) { location.href = "/panel"; throw new Error("Oturum kapandı."); }
        csrf = (await o.json()).csrf;
      }
      Object.assign(secenek, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF": csrf }, body: JSON.stringify(govde) });
    }
    const r = await fetch("/panel/uyg/" + yol, secenek);
    if (r.status === 401) { location.href = "/panel"; throw new Error("Oturum kapandı."); }
    let v = null;
    try { v = await r.json(); } catch (e) { v = null; }
    if (!r.ok) throw new Error((v && v.hata) || `İstek başarısız oldu (${r.status}).`);
    return v;
  }
  const al = (yol) => istek(yol);
  const gonder = (yol, govde) => istek(yol, govde || {});

  // ---------------------------------------------------------------- bildirim
  let zamanlayici = null;
  function bildir(mesaj, kotu) {
    const b = $("bildirim");
    b.textContent = mesaj;
    b.classList.toggle("kotu", !!kotu);
    b.classList.remove("sakli");
    clearTimeout(zamanlayici);
    zamanlayici = setTimeout(() => b.classList.add("sakli"), kotu ? 6000 : 3000);
  }
  /** İşi dener; hata olursa bildirir ve null döner. */
  async function dene(fn) {
    try { return await fn(); } catch (e) { bildir(e.message || String(e), true); return null; }
  }

  // ---------------------------------------------------------------- tarih
  const AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"];
  const GUNLER = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];
  const tarih = (iso) => { const [y, a, g] = iso.slice(0, 10).split("-").map(Number); return new Date(Date.UTC(y, a - 1, g)); };
  const isoYaz = (d) => d.toISOString().slice(0, 10);
  const gunEkle = (iso, n) => { const d = tarih(iso); d.setUTCDate(d.getUTCDate() + n); return isoYaz(d); };
  const haftaGunu = (iso) => (tarih(iso).getUTCDay() + 6) % 7;                 // 0 = Pazartesi
  const gunFarki = (a, b) => Math.round((tarih(b) - tarih(a)) / 86400000);
  /** "Bugün", "Yarın", "Dün" ya da "21 Kas Cmt" (yıl farklıysa yılıyla). */
  function tarihYaz(iso, bugun) {
    if (!iso) return "";
    const f = bugun ? gunFarki(bugun, iso) : 99;
    if (f === 0) return "Bugün";
    if (f === 1) return "Yarın";
    if (f === -1) return "Dün";
    const d = tarih(iso);
    const yil = bugun && bugun.slice(0, 4) !== iso.slice(0, 4) ? " " + iso.slice(0, 4) : "";
    return `${d.getUTCDate()} ${AYLAR[d.getUTCMonth()].slice(0, 3)}${yil} ${GUNLER[haftaGunu(iso)]}`;
  }
  const anYaz = (an) => an ? `${an.slice(0, 10)} ${an.slice(11, 16)}` : "";
  function sureYaz(saat) {
    const s = Math.floor(saat);
    if (s < 1) return "1 saatten az";
    const gun = Math.floor(s / 24), kalan = s % 24;
    return [gun ? `${gun} gün` : "", kalan ? `${kalan} saat` : ""].filter(Boolean).join(" ");
  }
  const sayiYaz = (x) => String(Math.round(x * 10) / 10).replace(".", ",");
  /** Zaman damgasının bu cihazın saatine göre günü (toISOString UTC gününü verir; gece 00–03 arası "dün" çıkardı). */
  const yerelGun = (ts) => { const d = new Date(ts * 1000); return isoYaz(new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))); };
  const zamanYaz = (ts) => new Date(ts * 1000).toLocaleString("tr-TR", { dateStyle: "medium", timeStyle: "short" });

  // ---------------------------------------------------------------- form parçaları
  const alan = (etiket, girdi, ipucu) => el("label", { class: "alan" }, el("span", { class: "et" }, etiket), girdi, ipucu ? el("span", { class: "not" }, ipucu) : null);
  const girdi = (tur, deger, ek) => el("input", Object.assign({ type: tur, value: deger === null || deger === undefined ? "" : deger }, ek || {}));
  const metinAlani = (deger, ek) => { const t = el("textarea", ek || {}); t.value = deger || ""; return t; };
  /** secim([["deger", "Ad"], ...], seçili) */
  function secim(secenekler, deger, ek) {
    const s = el("select", ek || {}, secenekler.map(([d, ad]) => el("option", { value: d }, ad)));
    s.value = deger === null || deger === undefined ? "" : String(deger);
    return s;
  }
  function isaretKutusu(etiket, isaretli, ek) {
    const kutu = el("input", Object.assign({ type: "checkbox", checked: !!isaretli }, ek || {}));
    return { kutu, satir: el("label", { class: "isaret-satir" }, kutu, el("span", {}, etiket)) };
  }
  const OZEL_ETIKET = "Özel: hafızaya yazılmasın, ajanlar görmesin";
  /** Boş → null; sayı değilse hata atar (yoksa "8o" gibi bir yazım sessizce boş kaydedilir ve eski değeri silerdi). */
  function sayiAl(girdiOgesi) {
    const s = girdiOgesi.value.trim().replace(",", ".");
    if (s === "") return null;
    const n = Number(s);
    if (Number.isNaN(n)) throw new Error(`“${girdiOgesi.value.trim()}” bir sayı değil.`);
    return n;
  }
  /** Aynı iş sürerken gelen ikinci çağrıyı yok sayar (çift tık, basılı tutulan Enter iki kayıt oluşturmasın). */
  function tekSefer(fn) {
    let surer = false;
    return async (...a) => {
      if (surer) return undefined;
      surer = true;
      try { return await fn(...a); } finally { surer = false; }
    };
  }

  // ---------------------------------------------------------------- pencere (form)
  /** pencere("Başlık", [alanlar], {kaydet: async () => bool|void, kaydetAd, ek: [düğmeler]}) — kaydet hata atarsa pencere açık kalır. */
  function pencere(baslik, alanlar, secenek) {
    const p = $("pencere"), hata = el("p", { class: "hata", role: "alert" });
    const kapat = () => { p.close(); p.replaceChildren(); };
    const kaydet = el("button", { class: "dugme vurgu", type: "submit" }, secenek.kaydetAd || "Kaydet");
    const form = el("form", { method: "dialog", novalidate: true }, el("h3", {}, baslik), alanlar, hata,
      el("div", { class: "alt" }, kaydet, el("button", { class: "dugme", type: "button", onclick: kapat }, "Vazgeç"),
        el("span", { class: "bosluk" }), secenek.ek || null));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      kaydet.disabled = true; hata.textContent = "";
      try {
        if (await secenek.kaydet() !== false) kapat();
      } catch (err) { hata.textContent = err.message || String(err); }
      kaydet.disabled = false;
    });
    p.replaceChildren(form);
    p.showModal();
    const ilk = form.querySelector("input:not([type=checkbox]), textarea, select");
    if (ilk) ilk.focus();
    return kapat;
  }
  /** Geri alınması zahmetli işler için onay penceresi. */
  function onay(baslik, aciklama, eylemAd, fn) {
    return pencere(baslik, [el("p", {}, aciklama)], { kaydetAd: eylemAd, kaydet: fn });
  }

  const ustBilgi = (metin) => { $("ust-bilgi").textContent = metin; };
  const bos = (baslik, metin) => el("p", { class: "bos-not" }, el("b", {}, baslik), metin);
  const rozet = (metin, sinif) => el("span", { class: "rozet" + (sinif ? " " + sinif : "") }, metin);
  /** Seçici düğme sırası: cipler([["kod", "Ad", sayı?], ...], seçili, fn) */
  function cipler(secenekler, secili, fn) {
    return el("div", { class: "cipler", role: "group" }, secenekler.map(([kod, ad, sayi]) =>
      el("button", { type: "button", class: kod === secili ? "secili" : "", "aria-pressed": String(kod === secili), onclick: () => fn(kod) },
        ad, sayi === undefined ? null : el("span", { class: "say" }, sayi))));
  }
  function ilerleme(yuzde) {
    const ic = el("span");
    ic.style.width = Math.max(0, Math.min(100, yuzde)) + "%";
    return el("div", { class: "ilerleme", role: "progressbar", "aria-valuenow": String(Math.round(yuzde)), "aria-valuemin": "0", "aria-valuemax": "100" }, ic);
  }
  const ana = () => $("uyg");
  /** Sayfanın gövdesini kurar: iç içe diziler açılır, null/false atlanır (replaceChildren bunları "null" diye yazardı). */
  const koy = (...kids) => ana().replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));

  return { $, UYG, el, al, gonder, bildir, dene, AYLAR, GUNLER, tarih, isoYaz, gunEkle, haftaGunu, gunFarki, tarihYaz, anYaz, sureYaz, sayiYaz,
    zamanYaz, yerelGun, alan, girdi, metinAlani, secim, isaretKutusu, OZEL_ETIKET, sayiAl, tekSefer, pencere, onay, ustBilgi, bos, rozet, cipler, ilerleme, ana, koy };
})();
