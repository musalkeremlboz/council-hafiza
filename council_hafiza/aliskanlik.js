// COUNCIL Alışkanlık: tek dokunuşla işaretleme, seri, son 7 gün. İşaretler hafızaya yazılmaz; yalnız alışkanlığın tanımı yazılır.
"use strict";
(() => {
  const { el, al, gonder, dene, bildir, alan, girdi, metinAlani, isaretKutusu, pencere, onay, rozet, bos, haftaGunu } = U;
  const GUN_TAM = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"];
  const S = { ogeler: [], bugun: "", yansit: true };

  async function yukle() {
    const v = await al("aliskanlik/ogeler");
    Object.assign(S, { ogeler: v.ogeler, bugun: v.bugun, yansit: v.yansit });
    ciz();
  }
  function degistir(o) {
    const i = S.ogeler.findIndex((x) => x.id === o.id);
    if (i < 0) S.ogeler.push(o); else S.ogeler[i] = o;
    ciz();
  }
  // gun verilmezse sunucu kendi "bugün"ünü kullanır: sayfa gece yarısından önce açıldıysa büyük düğme düne yazmasın
  const isaretle = U.tekSefer(async (o, gun, tamam) => {
    const r = await dene(() => gonder("aliskanlik/gun", Object.assign({ id: o.id, veri: { tamam } }, gun ? { gun } : {})));
    if (r) { if (!gun) await yukle(); else degistir(r.oge); }
  });
  async function durum(o, yeni) {
    const r = await dene(() => gonder("aliskanlik/guncelle", { id: o.id, durum: yeni }));
    if (r) degistir(r.oge);
  }

  function form(o) {
    const v = o ? o.veri : { ad: "", gunler: [], aciklama: "", ozel: false };
    const ad = girdi("text", v.ad, { maxlength: 120, placeholder: "10 dakika okuma" }), aciklama = metinAlani(v.aciklama, { maxlength: 500, rows: 3 });
    const gunler = GUN_TAM.map((g, i) => isaretKutusu(g, v.gunler.includes(i)));
    const ozel = isaretKutusu(U.OZEL_ETIKET, v.ozel);
    const sil = o ? el("button", { class: "dugme tehlike", type: "button", onclick: async () => {
      if (await dene(() => gonder("aliskanlik/sil", { id: o.id }))) { S.ogeler = S.ogeler.filter((x) => x.id !== o.id); kapat(); ciz(); bildir("Alışkanlık silindi."); }
    } }, "Sil") : null;
    const kapat = pencere(o ? "Alışkanlığı düzelt" : "Yeni alışkanlık", [
      alan("Ad", ad), el("div", {}, el("span", { class: "et" }, "Günler (hiçbiri seçilmezse her gün)"), el("div", { class: "secmeli" }, gunler.map((g) => g.satir))),
      alan("Açıklama", aciklama), ozel.satir,
    ], { ek: sil, kaydet: async () => {
      const veri = { ad: ad.value, gunler: gunler.map((g, i) => g.kutu.checked ? i : -1).filter((i) => i >= 0), aciklama: aciklama.value, ozel: ozel.kutu.checked };
      const r = await gonder(o ? "aliskanlik/guncelle" : "aliskanlik/ekle", o ? { id: o.id, veri } : { veri });
      degistir(r.oge);
    } });
  }

  function kart(o) {
    const v = o.veri, t = o.turev;
    const dugme = (ad, fn) => el("button", { class: "dugme kucuk", type: "button", onclick: fn }, ad);
    const gunlerYazi = !v.gunler.length || v.gunler.length === 7 ? "Her gün" : v.gunler.map((g) => U.GUNLER[g]).join(", ");
    return el("article", { class: "kart" }, el("div", { class: "aliskanlik" },
      el("button", { class: "isaret-dugme" + (t.bugun_tamam ? " tamam" : "") + (t.bugun_planli ? "" : " plansiz"), type: "button", "aria-pressed": String(t.bugun_tamam),
        "aria-label": `${v.ad}: bugün ${t.bugun_tamam ? "tamam, geri al" : "işaretle"}`, onclick: () => isaretle(o, null, !t.bugun_tamam) }, t.bugun_tamam ? "Tamam" : "İşaretle"),
      el("div", {}, el("h3", {}, v.ad),
        el("div", { class: "meta" }, el("span", {}, `Seri ${t.seri} gün`), el("span", {}, `En uzun ${t.en_uzun}`), el("span", {}, gunlerYazi),
          t.bugun_planli ? null : el("span", {}, "bugün planlı değil"), t.risk ? rozet("Seri kırılmak üzere", "kotu") : null, v.ozel ? rozet("Özel", "dolu") : null),
        el("div", { class: "hafta" }, t.son7.map((g) => el("button", { type: "button",
          class: (g.tamam ? "tamam" : "") + (g.planli ? "" : " plansiz") + (g.gun === S.bugun ? " bugun" : ""), "aria-pressed": String(g.tamam),
          "aria-label": `${g.gun} ${g.tamam ? "tamam" : "boş"}`, title: g.gun, onclick: () => isaretle(o, g.gun, !g.tamam) }, U.GUNLER[haftaGunu(g.gun)]))))),
      v.aciklama ? el("div", { class: "soluk" }, v.aciklama) : null,
      el("div", { class: "eylemler" }, dugme("Düzelt", () => form(o)),
        dugme("Bırak", () => onay("Alışkanlığı bırak", `“${v.ad}” bırakılanlara taşınsın mı? İşaretlerin silinmez; istersen yeniden başlarsın.`, "Bırak", () => durum(o, "bitti")))));
  }

  function ciz() {
    const acik = S.ogeler.filter((o) => o.durum === "acik"), birakilan = S.ogeler.filter((o) => o.durum === "bitti");
    const bugunku = acik.filter((o) => o.turev.bugun_planli);
    U.ustBilgi(`${bugunku.filter((o) => o.turev.bugun_tamam).length}/${bugunku.length} bugün`);
    U.koy(
      S.yansit ? null : el("p", { class: "duyuru" }, "Alışkanlıkların hafızaya yansıtılması kapalı (Ayarlar)."),
      el("div", { class: "cubuk" }, el("span", { class: "bosluk" }), el("button", { class: "dugme vurgu", type: "button", onclick: () => form(null) }, "Alışkanlık ekle")),
      acik.length ? el("div", { class: "izgara" }, acik.map(kart)) : bos("Henüz alışkanlık yok", "Küçük başla: günde tek bir şey. İşaretledikçe seri uzar; planlı bir günü boş geçersen seri sıfırlanır."),
      birakilan.length ? [el("h2", {}, "Bırakılanlar"), el("ul", { class: "liste" }, birakilan.map((o) => el("li", { class: "satir bitti" },
        el("div", { class: "govde" }, el("div", { class: "baslik" }, o.veri.ad), el("div", { class: "meta" }, `En uzun seri ${o.turev.en_uzun} gün`)),
        el("div", { class: "eylemler" }, el("button", { class: "dugme", type: "button", onclick: () => durum(o, "acik") }, "Yeniden başla"),
          el("button", { class: "dugme", type: "button", onclick: () => form(o) }, "Düzelt")))))] : null);
  }

  document.addEventListener("visibilitychange", () => { if (!document.hidden) dene(yukle); });   // sekmeye dönünce gün değişmiş olabilir
  dene(yukle);
})();
