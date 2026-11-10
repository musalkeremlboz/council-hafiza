// COUNCIL Not: yaz, etiketle, sabitle, ara; nottan görev ya da takvim etkinliği üret.
"use strict";
(() => {
  const { el, al, gonder, dene, bildir, tarihYaz, alan, girdi, metinAlani, isaretKutusu, pencere, rozet, bos } = U;
  const S = { ogeler: [], bugun: "", ara: "", etiket: "", yansit: true, taslak: { metin: "", etiketler: "", ozel: false } };
  const kucuk = (s) => s.toLocaleLowerCase("tr");
  const etiketleriAl = (s) => s.split(",").map((x) => x.trim()).filter(Boolean).slice(0, 8);
  const ilkSatir = (m, n) => { const s = m.split("\n")[0].trim(); return s.length > n ? s.slice(0, n - 1) + "…" : s; };

  async function yukle() {
    const v = await al("not/ogeler");
    Object.assign(S, { ogeler: v.ogeler, bugun: v.bugun, yansit: v.yansit });
    ciz();
  }
  function degistir(o) {
    const i = S.ogeler.findIndex((x) => x.id === o.id);
    if (i < 0) S.ogeler.push(o); else S.ogeler[i] = o;
    ciz();
  }
  const guncelle = async (o, ek, mesaj) => {
    const r = await dene(() => gonder("not/guncelle", { id: o.id, veri: Object.assign({}, o.veri, ek) }));
    if (r) { degistir(r.oge); if (mesaj) bildir(mesaj); }
  };

  function duzelt(o) {
    const metin = metinAlani(o.veri.metin, { maxlength: 4000, rows: 8 }), etiketler = girdi("text", o.veri.etiketler.join(", "));
    const ozel = isaretKutusu(U.OZEL_ETIKET, o.veri.ozel);
    const sil = el("button", { class: "dugme tehlike", type: "button", onclick: async () => {
      if (await dene(() => gonder("not/sil", { id: o.id }))) { S.ogeler = S.ogeler.filter((x) => x.id !== o.id); kapat(); ciz(); bildir("Not silindi."); }
    } }, "Sil");
    const kapat = pencere("Notu düzelt", [alan("Not", metin), alan("Etiketler", etiketler, "Virgülle ayır; en fazla 8."), ozel.satir], { ek: sil, kaydet: async () => {
      const r = await gonder("not/guncelle", { id: o.id, veri: { metin: metin.value, etiketler: etiketleriAl(etiketler.value), sabit: o.veri.sabit, ozel: ozel.kutu.checked } });
      degistir(r.oge);
    } });
  }
  const goreveCevir = U.tekSefer(async (o) => {
    const m = o.veri.metin;
    const r = await dene(() => gonder("gorev/ekle", { veri: { baslik: ilkSatir(m, 300), aciklama: m.length > 300 || m.includes("\n") ? m.slice(0, 2000) : "",
      son_tarih: o.turev.tarih_onerisi || "", ozel: o.veri.ozel } }));
    if (r) bildir("Görev eklendi" + (r.oge.veri.son_tarih ? ` (son tarih ${r.oge.veri.son_tarih}).` : "."));
  });
  const takvimeEkle = U.tekSefer(async (o) => {
    const r = await dene(() => gonder("takvim/ekle", { veri: { baslik: ilkSatir(o.veri.metin, 200), tarih: o.turev.tarih_onerisi, aciklama: o.veri.metin.slice(0, 2000), ozel: o.veri.ozel } }));
    if (r) bildir(`Takvime eklendi: ${r.oge.veri.tarih}.`);
  });

  function kart(o) {
    const v = o.veri, dugme = (ad, fn, sinif) => el("button", { class: "dugme kucuk" + (sinif ? " " + sinif : ""), type: "button", onclick: fn }, ad);
    return el("article", { class: "kart" },
      el("div", { class: "not-metin" }, v.metin),
      el("div", { class: "meta" }, v.sabit ? rozet("Sabit", "vurgu") : null, v.ozel ? rozet("Özel", "dolu") : null,
        v.etiketler.map((e) => el("button", { class: "rozet", type: "button", onclick: () => { S.etiket = S.etiket === e ? "" : e; ciz(); } }, e)),
        el("span", {}, tarihYaz(U.yerelGun(o.guncelleme), S.bugun)), o.kayit_id ? el("span", { title: "Hafızadaki kaydı" }, o.kayit_id) : null),
      el("div", { class: "eylemler" }, dugme("Düzelt", () => duzelt(o)), dugme(v.sabit ? "Sabiti kaldır" : "Sabitle", () => guncelle(o, { sabit: !v.sabit })),
        dugme("Göreve çevir", () => goreveCevir(o)),
        o.turev.tarih_onerisi ? dugme(`Takvime ekle (${tarihYaz(o.turev.tarih_onerisi, S.bugun)})`, () => takvimeEkle(o), "vurgu") : null));
  }

  function ciz() {
    U.ustBilgi(`${S.ogeler.length} not`);
    const metin = metinAlani(S.taslak.metin, { placeholder: "Yeni not…", maxlength: 4000, "aria-label": "Yeni not" });
    const etiketler = girdi("text", S.taslak.etiketler, { placeholder: "etiketler (virgülle)", "aria-label": "Etiketler", class: "ara-kutu" });
    const ozel = isaretKutusu("Özel", S.taslak.ozel);
    // taslak: karttaki bir düğme sayfayı yeniden çizince yazılmakta olan not kaybolmasın
    const taslakTut = () => { S.taslak = { metin: metin.value, etiketler: etiketler.value, ozel: ozel.kutu.checked }; };
    for (const g of [metin, etiketler, ozel.kutu]) g.addEventListener("input", taslakTut);
    const kaydetNot = U.tekSefer(async () => {
      const r = await dene(() => gonder("not/ekle", { veri: { metin: metin.value, etiketler: etiketleriAl(etiketler.value), ozel: ozel.kutu.checked } }));
      if (r) { S.taslak = { metin: "", etiketler: "", ozel: false }; S.ara = ""; S.etiket = ""; degistir(r.oge); bildir(r.oge.kayit_id ? `Not kaydedildi (${r.oge.kayit_id}).` : "Not kaydedildi (hafızaya yazılmadı)."); }
    });
    const ekle = (e) => {
      e.preventDefault();
      if (!metin.value.trim()) { metin.focus(); return; }
      kaydetNot();
    };
    metin.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ekle(e); });
    const araKutu = girdi("search", S.ara, { placeholder: "Notlarda ara", class: "ara-kutu", "aria-label": "Notlarda ara" });
    araKutu.addEventListener("input", () => { S.ara = araKutu.value; cizListe(); });
    const liste = el("div", { class: "izgara", id: "not-liste" });
    function cizListe() {
      const a = kucuk(S.ara.trim());
      const l = S.ogeler.filter((o) => (!S.etiket || o.veri.etiketler.includes(S.etiket))
        && (!a || kucuk(o.veri.metin).includes(a) || o.veri.etiketler.some((e) => kucuk(e).includes(a))))
        .sort((x, y) => (y.veri.sabit - x.veri.sabit) || (y.guncelleme - x.guncelleme));
      liste.replaceChildren(...(l.length ? l.map(kart) : [S.ogeler.length ? bos("Eşleşen not yok", "Aramayı ya da etiket süzgecini değiştir.")
        : bos("Henüz not yok", "Yukarıya yaz ve Kaydet'e bas. Notlar ortak hafızaya da düşer; Hermes ve Claude onları bulabilir.")]));
    }
    U.koy(
      S.yansit ? null : el("p", { class: "duyuru" }, "Notların hafızaya yansıtılması kapalı (Ayarlar). Ajanlar buradaki notları görmez."),
      el("form", { class: "hizli", onsubmit: ekle }, metin, el("button", { class: "dugme vurgu", type: "submit" }, "Kaydet")),
      el("div", { class: "cubuk" }, etiketler, ozel.satir),
      el("div", { class: "cubuk" }, araKutu, S.etiket ? el("button", { class: "dugme kucuk", type: "button", onclick: () => { S.etiket = ""; ciz(); } }, `Etiket: ${S.etiket} ×`) : null),
      liste);
    cizListe();                       // arama yazılırken yalnız liste yeniden çizilir (odak arama kutusunda kalır)
  }

  dene(yukle);
})();
