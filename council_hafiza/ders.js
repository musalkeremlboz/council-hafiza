// COUNCIL Ders: dersler, üniteler ve ilerleme; ara sınav/final ortalaması ve hedef için gereken final; Takvim'deki sınavlar.
"use strict";
(() => {
  const { el, al, gonder, dene, bildir, tarihYaz, alan, girdi, metinAlani, isaretKutusu, pencere, onay, rozet, bos, ilerleme, sayiYaz, sayiAl } = U;
  const DURUM = { yok: "Başlanmadı", calisiliyor: "Çalışılıyor", bitti: "Bitti" }, SONRAKI = { yok: "calisiliyor", calisiliyor: "bitti", bitti: "yok" };
  const S = { ogeler: [], bugun: "", yansit: true };

  async function yukle() {
    const v = await al("ders/ogeler");
    Object.assign(S, { ogeler: v.ogeler, bugun: v.bugun, yansit: v.yansit });
    ciz();
  }
  function degistir(o) {
    const i = S.ogeler.findIndex((x) => x.id === o.id);
    if (i < 0) S.ogeler.push(o); else S.ogeler[i] = o;
    ciz();
  }
  // Dersin verisini kısmen değiştirir. Bütün ünite listesi gönderildiği için istekler üst üste binmemeli: ilk cevap gelmeden
  // yapılan ikinci tık eski listeden hesaplanır ve ilk değişikliği silerdi; bu yüzden istek sürerken gelen tıklar yok sayılır.
  const kaydet = U.tekSefer(async (o, ek) => {
    const r = await dene(() => gonder("ders/guncelle", { id: o.id, veri: Object.assign({}, o.veri, ek) }));
    if (r) degistir(r.oge);
    return r;
  });

  function form(o) {
    const v = o ? o.veri : { ad: "", kurum: "", donem: "", ara: null, final: null, ara_agirlik: 30, hedef: null, aciklama: "", ozel: false, uniteler: [] };
    const ad = girdi("text", v.ad, { maxlength: 120 }), kurum = girdi("text", v.kurum, { maxlength: 80 }), donem = girdi("text", v.donem, { maxlength: 40, placeholder: "2026 güz" });
    const sayi = (d) => girdi("text", d === null ? "" : sayiYaz(d), { inputmode: "decimal" });
    const ara = sayi(v.ara), fin = sayi(v.final), agirlik = sayi(v.ara_agirlik), hedef = sayi(v.hedef);
    const aciklama = metinAlani(v.aciklama, { maxlength: 2000 }), ozel = isaretKutusu(U.OZEL_ETIKET, v.ozel);
    const uniteler = o ? null : metinAlani("", { placeholder: "Her satıra bir ünite adı (sonradan da eklenir)", rows: 4 });
    const sil = o ? el("button", { class: "dugme tehlike", type: "button", onclick: async () => {
      if (await dene(() => gonder("ders/sil", { id: o.id }))) { S.ogeler = S.ogeler.filter((x) => x.id !== o.id); kapat(); ciz(); bildir("Ders silindi."); }
    } }, "Sil") : null;
    const kapat = pencere(o ? "Dersi düzelt" : "Yeni ders", [
      alan("Ders adı", ad), el("div", { class: "iki" }, alan("Kurum", kurum), alan("Dönem", donem)),
      el("div", { class: "iki" }, alan("Ara sınav notu", ara), alan("Final notu", fin)),
      el("div", { class: "iki" }, alan("Ara sınav ağırlığı (%)", agirlik, "Final ağırlığı kalanıdır."), alan("Hedef ortalama", hedef, "Yazarsan gereken final notu hesaplanır.")),
      uniteler ? alan("Üniteler", uniteler) : null, alan("Açıklama", aciklama), ozel.satir,
    ], { ek: sil, kaydet: async () => {
      const veri = { ad: ad.value, kurum: kurum.value, donem: donem.value, ara: sayiAl(ara), final: sayiAl(fin), ara_agirlik: sayiAl(agirlik) === null ? 30 : sayiAl(agirlik),
        hedef: sayiAl(hedef), aciklama: aciklama.value, ozel: ozel.kutu.checked,
        uniteler: o ? o.veri.uniteler : uniteler.value.split("\n").map((s) => s.trim()).filter(Boolean).map((s) => ({ ad: s, durum: "yok" })) };
      const r = await gonder(o ? "ders/guncelle" : "ders/ekle", o ? { id: o.id, veri } : { veri });
      degistir(r.oge);
    } });
  }
  function sinavEkle(o) {
    const baslik = girdi("text", `${o.veri.ad} sınavı`, { maxlength: 200 }), gun = girdi("date", ""), saat = girdi("time", "");
    pencere("Sınav ekle", [alan("Başlık", baslik), el("div", { class: "iki" }, alan("Tarih", gun), alan("Saat", saat)),
      el("p", { class: "not" }, "Sınav Takvim'e eklenir ve bu derse bağlanır.")], { kaydetAd: "Takvime ekle", kaydet: async () => {
      await gonder("takvim/ekle", { veri: { baslik: baslik.value, tarih: gun.value, saat: saat.value, tur: "sinav", ders_id: o.id, ozel: o.veri.ozel } });
      bildir("Sınav takvime eklendi."); dene(yukle);
    } });
  }

  function notKutusu(o) {
    const v = o.veri, t = o.turev, parca = [];
    if (v.ara !== null) parca.push(`Ara sınav ${sayiYaz(v.ara)}`);
    if (v.final !== null) parca.push(`Final ${sayiYaz(v.final)}`);
    if (!parca.length && v.hedef === null) return null;
    let sonuc = null;
    if (t.ortalama !== null) sonuc = el("div", {}, el("span", { class: "buyuk-sayi" }, sayiYaz(t.ortalama)), el("span", { class: "soluk" }, ` ortalama (ara %${sayiYaz(v.ara_agirlik)})`));
    else if (t.gereken_final !== null) sonuc = el("div", {}, el("span", { class: "buyuk-sayi" }, t.ulasilamaz ? "—" : sayiYaz(t.gereken_final)),
      el("span", { class: "soluk" }, t.ulasilamaz ? ` hedef ${sayiYaz(v.hedef)} bu ara sınav notuyla tutmuyor` : ` final gerekli (hedef ${sayiYaz(v.hedef)})`));
    return el("div", {}, sonuc, parca.length ? el("div", { class: "soluk" }, parca.join(" · ")) : null);
  }
  function kart(o) {
    const v = o.veri, t = o.turev, bitti = o.durum === "bitti";
    const yeni = girdi("text", "", { placeholder: "Ünite ekle", maxlength: 160, "aria-label": "Ünite ekle" });
    const uniteEkle = (e) => { e.preventDefault(); if (yeni.value.trim()) kaydet(o, { uniteler: [...v.uniteler, { ad: yeni.value.trim(), durum: "yok" }] }); };
    const unite = (u, i) => el("div", { class: "unite " + u.durum },
      el("span", { class: "ad" }, u.ad),
      el("button", { class: "durum " + u.durum, type: "button", title: "Durumu değiştir",
        onclick: () => kaydet(o, { uniteler: v.uniteler.map((x, j) => j === i ? { ad: x.ad, durum: SONRAKI[x.durum] } : x) }) }, DURUM[u.durum]),
      el("button", { class: "cikar", type: "button", "aria-label": `${u.ad} ünitesini çıkar`, onclick: () => kaydet(o, { uniteler: v.uniteler.filter((_, j) => j !== i) }) }, "×"));
    const dugme = (ad, fn, sinif) => el("button", { class: "dugme kucuk" + (sinif ? " " + sinif : ""), type: "button", onclick: fn }, ad);
    const durumDegis = async (yeniDurum) => { const r = await dene(() => gonder("ders/guncelle", { id: o.id, durum: yeniDurum })); if (r) degistir(r.oge); };
    return el("article", { class: "kart" + (bitti ? " pasif" : "") },
      el("div", { class: "kart-ust" }, el("div", {}, el("h3", {}, v.ad), el("div", { class: "meta" }, [v.kurum, v.donem].filter(Boolean).join(" · ") || null,
        bitti ? rozet("Tamamlandı", "dolu") : null, v.ozel ? rozet("Özel", "dolu") : null)),
        el("span", { class: "buyuk-sayi", title: "İlerleme" }, t.toplam ? `%${t.yuzde}` : "")),
      t.toplam ? [ilerleme(t.yuzde), el("div", { class: "soluk" }, `${t.bitti}/${t.toplam} ünite bitti` + (t.calisiliyor ? ` · ${t.calisiliyor} çalışılıyor` : ""))] : null,
      t.sinavlar.map((s) => el("div", { class: "meta" }, rozet("Sınav", "kotu"), el("span", {}, `${s.baslik} — ${tarihYaz(s.tarih, S.bugun)}${s.saat ? " " + s.saat : ""}`),
        el("span", { class: s.kalan_gun <= 7 ? "kotu" : "" }, s.kalan_gun === 0 ? "bugün" : `${s.kalan_gun} gün kaldı`))),
      notKutusu(o),
      el("div", {}, v.uniteler.map(unite), bitti ? null : el("form", { class: "unite-ekle", onsubmit: uniteEkle }, yeni, el("button", { class: "dugme kucuk", type: "submit" }, "Ekle"))),
      el("div", { class: "eylemler" }, dugme("Düzelt", () => form(o)), bitti ? null : dugme("Sınav ekle", () => sinavEkle(o)),
        bitti ? dugme("Yeniden aç", () => durumDegis("acik"))
          : dugme("Dersi bitir", () => onay("Dersi bitir", `“${v.ad}” tamamlandı olarak işaretlensin mi? Ders listede kalır, istersen yeniden açarsın.`, "Bitir", () => durumDegis("bitti")))));
  }

  function ciz() {
    const acik = S.ogeler.filter((o) => o.durum === "acik"), biten = S.ogeler.filter((o) => o.durum === "bitti");
    U.ustBilgi(`${acik.length} ders`);
    U.koy(
      S.yansit ? null : el("p", { class: "duyuru" }, "Derslerin hafızaya yansıtılması kapalı (Ayarlar)."),
      el("div", { class: "cubuk" }, el("span", { class: "bosluk" }), el("button", { class: "dugme vurgu", type: "button", onclick: () => form(null) }, "Ders ekle")),
      acik.length ? el("div", { class: "izgara" }, acik.map(kart)) : bos("Henüz ders yok", "Ders ekle; ünitelerini yaz, bitirdikçe işaretle. Sınav tarihlerini Takvim'e buradan ekleyebilirsin."),
      biten.length ? [el("h2", {}, "Tamamlananlar"), el("div", { class: "izgara" }, biten.map(kart))] : null);
  }

  dene(yukle);
})();
