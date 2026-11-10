// COUNCIL Oruç: canlı sayaç, evre, günlük giriş (su, elektrolit, kilo, his, belirtiler), tehlike uyarısı, kırma planı, geçmiş.
// Takip aracıdır; tıbbi öneri üretmez. Günlük girişler hafızaya yazılmaz.
"use strict";
(() => {
  const { el, al, gonder, dene, bildir, alan, girdi, metinAlani, secim, isaretKutusu, pencere, onay, rozet, bos, ilerleme, sureYaz, anYaz, sayiYaz, sayiAl } = U;
  const TUR = [["su", "Su orucu"], ["aralikli", "Aralıklı oruç"], ["diger", "Diğer"]], SONUC = { tamamlandi: "tamamlandı", erken: "erken bitirildi" };
  const HAZIR = [["16 saat", 16], ["24 saat", 24], ["3 gün", 72], ["7 gün", 168], ["28 gün", 672]];
  const S = { ogeler: [], bugun: "", simdi: "", yuklenme: 0, belirtiler: {}, tehlike: [], uyari: "", yansit: true, sayac: null, plan: null };

  const anMs = (an) => Date.UTC(+an.slice(0, 4), +an.slice(5, 7) - 1, +an.slice(8, 10), +an.slice(11, 13), +an.slice(14, 16));
  const simdiMs = () => anMs(S.simdi) + (Date.now() - S.yuklenme);            // sunucunun saati + sayfa açıldığından beri geçen süre
  const gecenSaat = (v) => Math.max(0, (simdiMs() - anMs(v.baslangic)) / 3600000);
  function sayacYaz(saat) {
    const dk = Math.floor(saat * 60), gun = Math.floor(dk / 1440), s = Math.floor((dk % 1440) / 60), d = dk % 60;
    return (gun ? `${gun} gün ` : "") + `${String(s).padStart(2, "0")}:${String(d).padStart(2, "0")}`;
  }

  async function yukle() {
    const v = await al("oruc/ogeler");
    Object.assign(S, { ogeler: v.ogeler, bugun: v.bugun, simdi: v.simdi, yuklenme: Date.now(), belirtiler: v.belirtiler, tehlike: v.tehlike, uyari: v.uyari, yansit: v.yansit });
    ciz();
  }
  function degistir(o) {
    const i = S.ogeler.findIndex((x) => x.id === o.id);
    if (i < 0) S.ogeler.push(o); else S.ogeler[i] = o;
    ciz();
  }

  function hedefAlani(saat) {
    const gunMu = saat >= 48 && saat % 24 === 0;
    const sayi = girdi("number", gunMu ? saat / 24 : saat, { min: 1, max: 1440, step: 1 }), birim = secim([["1", "saat"], ["24", "gün"]], gunMu ? "24" : "1");
    const hazir = el("div", { class: "secmeli" }, HAZIR.map(([ad, s]) => el("button", { class: "dugme kucuk", type: "button", onclick: () => {
      const g = s >= 48; sayi.value = g ? s / 24 : s; birim.value = g ? "24" : "1";
    } }, ad)));
    return { deger: () => Math.round(Number(sayi.value) * Number(birim.value)), dugum: el("div", {}, el("div", { class: "iki" }, alan("Hedef süre", sayi), alan("Birim", birim)), hazir) };
  }
  function baslatFormu() {
    // varsayılan başlangıç şu an (sayfanın açıldığı an değil: sayfa saatlerdir açıksa oruç geçmişten başlamasın)
    const tur = secim(TUR, "su"), bas = girdi("datetime-local", new Date(simdiMs()).toISOString().slice(0, 16)), hedef = hedefAlani(16);
    const baslatIs = U.tekSefer(async () => {
      const r = await dene(() => gonder("oruc/ekle", { veri: { tur: tur.value, baslangic: bas.value.slice(0, 16), hedef_saat: hedef.deger() } }));
      if (r) { degistir(r.oge); bildir("Oruç başladı."); }
    });
    const baslat = (e) => { e.preventDefault(); baslatIs(); };
    return el("form", { class: "form-kutu", onsubmit: baslat }, el("h3", {}, "Oruç başlat"),
      el("div", { class: "iki" }, alan("Tür", tur), alan("Başlangıç", bas)), hedef.dugum,
      el("div", { class: "alt" }, el("button", { class: "dugme vurgu", type: "submit" }, "Başlat")));
  }
  function duzelt(o) {
    const v = o.veri, tur = secim(TUR, v.tur), bas = girdi("datetime-local", v.baslangic), hedef = hedefAlani(v.hedef_saat);
    const bitis = o.durum === "bitti" ? girdi("datetime-local", v.bitis) : null;
    const aciklama = metinAlani(v.aciklama, { maxlength: 1000, rows: 3 }), ozel = isaretKutusu(U.OZEL_ETIKET, v.ozel);
    const sil = el("button", { class: "dugme tehlike", type: "button", onclick: async () => {
      if (await dene(() => gonder("oruc/sil", { id: o.id }))) { S.ogeler = S.ogeler.filter((x) => x.id !== o.id); kapat(); ciz(); bildir("Oruç kaydı silindi."); }
    } }, "Sil");
    const kapat = pencere("Orucu düzelt", [el("div", { class: "iki" }, alan("Tür", tur), alan("Başlangıç", bas)), hedef.dugum,
      bitis ? alan("Bitiş", bitis) : null, alan("Açıklama", aciklama), ozel.satir], { ek: sil, kaydet: async () => {
      const veri = Object.assign({}, v, { tur: tur.value, baslangic: bas.value.slice(0, 16), hedef_saat: hedef.deger(), aciklama: aciklama.value, ozel: ozel.kutu.checked });
      if (bitis) { veri.bitis = bitis.value.slice(0, 16); veri.sonuc = ""; }      // sonucu sunucu yeni süreye göre yeniden belirler
      const r = await gonder("oruc/guncelle", { id: o.id, veri });
      degistir(r.oge);
    } });
  }

  function gunlukFormu(o) {
    const g = o.turev.bugun || { su_ml: null, elektrolit: false, kilo: null, his: null, belirtiler: [], not: "" };
    const su = girdi("number", g.su_ml, { min: 0, max: 15000, step: 50, inputmode: "numeric" }), kilo = girdi("text", g.kilo === null ? "" : sayiYaz(g.kilo), { inputmode: "decimal" });
    const elektrolit = isaretKutusu("Elektrolit alındı", g.elektrolit), not = metinAlani(g.not, { maxlength: 500, rows: 2 });
    let his = g.his;
    const hisKutu = el("div", { class: "his", role: "group", "aria-label": "Nasıl hissediyorsun (1 kötü, 5 iyi)" });
    const hisCiz = () => hisKutu.replaceChildren(...[1, 2, 3, 4, 5].map((n) => el("button", { type: "button", class: n === his ? "secili" : "", "aria-pressed": String(n === his),
      onclick: () => { his = his === n ? null : n; hisCiz(); } }, n)));
    hisCiz();
    const kutular = Object.entries(S.belirtiler).map(([kod, ad]) => [kod, isaretKutusu(ad, g.belirtiler.includes(kod))]);
    const grup = (tehlike) => kutular.filter(([kod]) => S.tehlike.includes(kod) === tehlike).map(([, k]) => k.satir);
    // gun gönderilmez: sunucu kendi "bugün"üne yazar (sayfa gece yarısından önce açıldıysa dünün girişi ezilmesin)
    const kaydetIs = U.tekSefer(async () => {
      const r = await dene(async () => gonder("oruc/gun", { id: o.id, veri: { su_ml: sayiAl(su), elektrolit: elektrolit.kutu.checked, kilo: sayiAl(kilo), his,
        belirtiler: kutular.filter(([, k]) => k.kutu.checked).map(([kod]) => kod), not: not.value } }));
      if (r) { degistir(r.oge); bildir(r.oge.turev.uyari.duzey === "tehlike" ? "Kaydedildi. Uyarıyı oku." : "Bugünün girişi kaydedildi.", r.oge.turev.uyari.duzey === "tehlike"); window.scrollTo({ top: 0 }); }
    });
    const kaydet = (e) => { e.preventDefault(); kaydetIs(); };
    const suEkle = (ml) => el("button", { class: "dugme kucuk", type: "button", onclick: () => { su.value = (Number(su.value) || 0) + ml; } }, `+${ml}`);
    return el("form", { class: "form-kutu", novalidate: true, onsubmit: kaydet }, el("h3", {}, `Bugünün girişi · ${S.bugun}`),
      el("div", { class: "iki" }, el("div", {}, alan("Su (ml)", su), el("div", { class: "alt" }, suEkle(250), suEkle(500))), alan("Kilo (kg)", kilo)),
      elektrolit.satir, el("div", {}, el("span", { class: "et" }, "Nasıl hissediyorsun (1 kötü · 5 iyi)"), hisKutu),
      el("div", { class: "belirti-grup" }, "Sık görülenler"), el("div", { class: "belirtiler" }, grup(false)),
      el("div", { class: "belirti-grup tehlike" }, "Tehlike belirtileri — biri varsa orucu bırak"), el("div", { class: "belirtiler" }, grup(true)),
      alan("Not", not), el("div", { class: "alt" }, el("button", { class: "dugme vurgu", type: "submit" }, "Girişi kaydet")));
  }

  function etkinGorunum(o) {
    const v = o.veri, t = o.turev;
    const buyuk = el("div", { class: "sayac-buyuk", "aria-live": "off" }), kalan = el("b"), gunNo = el("b"), cubuk = el("div");
    const guncelle = () => {
      const g = gecenSaat(v), k = Math.max(0, v.hedef_saat - g);
      buyuk.textContent = sayacYaz(g);
      gunNo.textContent = String(Math.floor(g / 24) + 1);
      kalan.textContent = k > 0 ? sureYaz(k) : "hedefe ulaşıldı";
      cubuk.replaceChildren(ilerleme(Math.min(100, 100 * g / v.hedef_saat)));
      if (new Date(simdiMs()).toISOString().slice(0, 10) !== S.bugun) dene(yukle);   // gün döndü: gün numarası, evre ve günlük form yenilensin
    };
    guncelle();
    clearInterval(S.sayac);
    S.sayac = setInterval(guncelle, 20000);
    const plan = metinAlani(S.plan === null ? v.kirma_plani : S.plan, { maxlength: 3000, rows: 4, placeholder: "Orucu nasıl bitireceğin: ilk günlerde ne yiyeceğin, ne kadar sürede normale döneceğin…" });
    plan.addEventListener("input", () => { S.plan = plan.value; });               // günlük giriş kaydedilince yazılmakta olan plan kaybolmasın
    const planKaydet = U.tekSefer(async () => {
      const r = await dene(() => gonder("oruc/guncelle", { id: o.id, veri: Object.assign({}, v, { kirma_plani: plan.value }) }));
      if (!r) return;
      S.plan = null;
      S.ogeler[S.ogeler.findIndex((x) => x.id === o.id)] = r.oge;                     // sayfa yeniden çizilmez: doldurulmakta olan günlük giriş kalsın
      v.kirma_plani = r.oge.veri.kirma_plani;
      bildir("Kırma planı kaydedildi.");
    });
    const bitir = () => onay("Orucu bitir", `Oruç şimdi bitmiş sayılacak (${sureYaz(gecenSaat(v))}). Yemeye dönüşü kademeli yap.`, "Bitir", async () => {
      const r = await gonder("oruc/guncelle", { id: o.id, durum: "bitti" });
      degistir(r.oge); bildir("Oruç bitti.");
    });
    const gunler = Object.entries(t.gunler).sort((a, b) => b[0].localeCompare(a[0]));
    return [
      t.uyari.duzey ? el("p", { class: "duyuru" + (t.uyari.duzey === "tehlike" ? " tehlike" : ""), role: t.uyari.duzey === "tehlike" ? "alert" : null }, t.uyari.mesaj) : null,
      el("section", { class: "sayac-kutu" }, el("div", { class: "et" }, `${TUR.find(([k]) => k === v.tur)[1]} · geçen süre`), buyuk, cubuk,
        el("div", { class: "sayac-alt" }, el("span", {}, "Gün ", gunNo), el("span", {}, "Hedef ", el("b", {}, sureYaz(v.hedef_saat))), el("span", {}, "Kalan ", kalan),
          el("span", {}, "Başlangıç ", el("b", {}, anYaz(v.baslangic))), el("span", {}, "Hedef bitiş ", el("b", {}, anYaz(t.hedef_bitis)))),
        el("div", { class: "evre" }, el("h3", {}, t.evre.ad), el("p", {}, t.evre.aciklama)),
        el("div", { class: "eylemler" }, el("button", { class: "dugme", type: "button", onclick: bitir }, "Orucu bitir"),
          el("button", { class: "dugme", type: "button", onclick: () => duzelt(o) }, "Düzelt"), v.ozel ? rozet("Özel", "dolu") : null)),
      gunlukFormu(o),
      el("h2", {}, "Kırma planı"), el("div", { class: "form-kutu" }, plan, el("div", { class: "alt" }, el("button", { class: "dugme", type: "button", onclick: planKaydet }, "Planı kaydet"))),
      gunler.length ? [el("h2", {}, "Günlük"), gunlukTablosu(gunler)] : null,
    ];
  }
  function gunlukTablosu(gunler) {
    return el("div", { class: "tablo-sar" }, el("table", {},
      el("tr", {}, ["Gün", "Su", "Elektrolit", "Kilo", "His", "Belirtiler", "Not"].map((b) => el("th", {}, b))),
      gunler.map(([gun, g]) => el("tr", {}, el("td", {}, gun), el("td", {}, g.su_ml === null ? "—" : `${g.su_ml} ml`), el("td", {}, g.elektrolit ? "evet" : "—"),
        el("td", {}, g.kilo === null ? "—" : sayiYaz(g.kilo)), el("td", {}, g.his === null ? "—" : g.his),
        el("td", {}, g.belirtiler.length ? g.belirtiler.map((b) => S.belirtiler[b]).join(", ") : "—"), el("td", {}, g.not || "—")))));
  }

  function ciz() {
    clearInterval(S.sayac);
    const etkin = S.ogeler.find((o) => o.durum === "acik"), biten = S.ogeler.filter((o) => o.durum === "bitti").sort((a, b) => b.veri.baslangic.localeCompare(a.veri.baslangic));
    U.ustBilgi(etkin ? `${etkin.turev.gun}. gün` : "oruç yok");
    U.koy(
      el("p", { class: "duyuru" }, S.uyari),
      S.yansit ? null : el("p", { class: "duyuru" }, "Orucun hafızaya yansıtılması kapalı (Ayarlar). Ajanlar oruçta olduğunu bu uygulamadan öğrenemez."),
      etkin ? etkinGorunum(etkin) : [baslatFormu(), biten.length ? null : bos("Süren oruç yok", "Başlattığında sayaç, evre ve günlük giriş burada görünür. Günlük girişlerin (kilo, belirtiler) hafızaya yazılmaz.")],
      biten.length ? [el("h2", {}, "Geçmiş oruçlar"), el("ul", { class: "liste" }, biten.map((o) => el("li", { class: "satir" },
        el("div", { class: "govde" }, el("div", { class: "baslik" }, `${anYaz(o.veri.baslangic)} – ${anYaz(o.veri.bitis)}`),
          el("div", { class: "meta" }, el("span", {}, sureYaz(o.turev.gecen_saat)), el("span", {}, `hedef ${sureYaz(o.veri.hedef_saat)}`),
            rozet(SONUC[o.veri.sonuc] || "bitti", o.veri.sonuc === "tamamlandi" ? "dolu" : ""), el("span", {}, `${Object.keys(o.turev.gunler).length} günlük giriş`))),
        el("div", { class: "eylemler" }, el("button", { class: "dugme", type: "button", onclick: () => duzelt(o) }, "Düzelt")))))] : null);
  }

  dene(yukle);
})();
