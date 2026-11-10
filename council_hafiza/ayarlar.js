// COUNCIL Ayarlar: saat dilimi, sessiz saatler, uygulama başına hafızaya yansıtma; bağlı araçlar, cihazlar ve sayılar (salt okunur).
"use strict";
(() => {
  const { el, al, gonder, dene, bildir, alan, girdi, isaretKutusu, zamanYaz, anYaz } = U;
  const UYG = [["not", "Not"], ["gorev", "Görev"], ["takvim", "Takvim"], ["ders", "Ders"], ["aliskanlik", "Alışkanlık"], ["oruc", "Oruç"]];
  let V = null;

  const tablo = (basliklar, satirlar, bosMetin) => satirlar.length
    ? el("div", { class: "tablo-sar" }, el("table", {}, el("tr", {}, basliklar.map((b) => el("th", {}, b))), satirlar.map((s) => el("tr", {}, s.map((h) => el("td", {}, h))))))
    : el("p", { class: "soluk" }, bosMetin);

  function ciz() {
    const a = V.ayar;
    const dilim = girdi("text", a.saat_dilimi, { list: "dilimler", autocomplete: "off" });
    const sessiz = isaretKutusu("Sessiz saatler açık", a.sessiz_acik), bas = girdi("time", a.sessiz_bas), son = girdi("time", a.sessiz_son);
    const yansit = UYG.map(([kod, ad]) => [kod, isaretKutusu(ad, a.yansit[kod])]);
    const kaydet = async (e) => {
      e.preventDefault();
      const r = await dene(() => gonder("ayarlar/kaydet", { saat_dilimi: dilim.value.trim(), sessiz_acik: sessiz.kutu.checked, sessiz_bas: bas.value, sessiz_son: son.value,
        yansit: Object.fromEntries(yansit.map(([kod, k]) => [kod, k.kutu.checked])) }));
      if (r) { bildir("Ayarlar kaydedildi."); dene(yukle); }
    };
    U.ustBilgi(anYaz(V.simdi));
    U.koy(
      el("form", { class: "form-kutu", onsubmit: kaydet },
        el("h3", {}, "Zaman"),
        alan("Saat dilimi", dilim, `“Bugün” ve hatırlatmalar bu saate göre hesaplanır. Şu an: ${anYaz(V.simdi)}.`),
        el("datalist", { id: "dilimler" }, ["Europe/Istanbul", "Europe/Berlin", "Europe/London", "America/New_York", "Asia/Tokyo", "UTC"].map((d) => el("option", { value: d }))),
        el("h3", {}, "Sessiz saatler"), sessiz.satir, el("div", { class: "iki" }, alan("Başlangıç", bas), alan("Bitiş", son)),
        el("p", { class: "not" }, "Açıkken hafızaya bir tercih kaydı düşer; Hermes ve diğer ajanlar bu saatlerde bildirim göndermemeyi buradan öğrenir."),
        el("h3", {}, "Hafızaya yansıtma"), el("div", { class: "secmeli" }, yansit.map(([, k]) => k.satir)),
        el("p", { class: "not" }, "Kapatılan uygulamanın hafızadaki kayıtları arşivlenir ve ajanlara verilen günlük özette o uygulama görünmez. Yeniden açınca kayıtlar baştan yazılır."),
        el("div", { class: "alt" }, el("button", { class: "dugme vurgu", type: "submit" }, "Kaydet"))),
      el("h2", {}, "Uygulamalar"),
      tablo(["Uygulama", "Açık", "Biten", "Hafızaya yansıtma"], UYG.map(([kod, ad]) => [el("a", { href: "/panel/" + kod }, ad), V.uygulamalar[kod].acik, V.uygulamalar[kod].bitti, a.yansit[kod] ? "açık" : "kapalı"]), ""),
      el("h2", {}, "Hafıza"),
      el("p", {}, `${V.hafiza.guncel} güncel kayıt (toplam ${V.hafiza.toplam}). Kayıtları görmek ve düzeltmek için `, el("a", { href: "/panel/gezgin" }, "Gezgin"), "."),
      el("h2", {}, "Bağlı araçlar"),
      tablo(["Araç", "Etiket", "Erişebildiği projeler", "Eklenme"], V.araclar.map((t) => [t.arac, t.etiket || "—", t.projeler === "*" ? "bütün projeler" : t.projeler, zamanYaz(t.olusturma)]),
        "Kayıtlı araç anahtarı yok."),
      el("h2", {}, "Araç kimlikleri"),
      tablo(["Araç", "Proje", "Ne için kullanılıyor"], V.kimlikler.map((k) => [k.arac, k.proje === "*" ? "tüm projeler" : k.proje, k.amac]), "Tanımlı kimlik yok."),
      el("h2", {}, "Cihazlar"),
      tablo(["Cihaz", "Son rapor", "Bildiren araç"], V.cihazlar.map((c) => [c.cihaz, zamanYaz(c.zaman), c.arac || "—"]), "Rapor gönderen cihaz yok."),
      el("h2", {}, "Hesap"),
      el("p", { class: "soluk" }, "Tek hesap: yönetici parolası. Parola şimdilik sunucuda komut satırından değiştirilir (council-hafiza parola-ayarla); araç anahtarları da oradan üretilir."));
  }
  async function yukle() { V = await al("ayarlar/veri"); ciz(); }

  dene(yukle);
})();
