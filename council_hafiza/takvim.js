// COUNCIL Takvim: ay görünümü, seçili gün, yaklaşanlar; etkinlik / sınav / mesai; tekrar. Görevlerin son tarihleri de görünür.
"use strict";
(() => {
  const { el, al, gonder, dene, bildir, tarihYaz, gunEkle, haftaGunu, alan, girdi, metinAlani, secim, isaretKutusu, pencere, rozet, bos } = U;
  const TUR = { etkinlik: "Etkinlik", sinav: "Sınav", mesai: "Mesai", gorev: "Görev" };
  const TEKRAR = [["yok", "Tekrar yok"], ["gunluk", "Her gün"], ["haftalik", "Her hafta"], ["aylik", "Her ay"], ["yillik", "Her yıl"]];
  const S = { ogeler: [], dersler: [], bugun: "", ay: "", secili: "", gunler: {}, yaklasan: {} };

  const ayBasi = (iso) => iso.slice(0, 7) + "-01";
  const izgaraBasi = () => gunEkle(ayBasi(S.ay), -haftaGunu(ayBasi(S.ay)));
  function ayKaydir(n) {
    const [y, a] = S.ay.split("-").map(Number), d = new Date(Date.UTC(y, a - 1 + n, 1));
    S.ay = d.toISOString().slice(0, 7);
  }

  async function yukle() {
    const v = await al("takvim/ogeler");
    Object.assign(S, { ogeler: v.ogeler, dersler: v.dersler, bugun: v.bugun });
    if (!S.ay) { S.ay = v.bugun.slice(0, 7); S.secili = v.bugun; }
    const bas = izgaraBasi();
    const [ay, yakin] = await Promise.all([al(`takvim/aralik?bas=${bas}&son=${gunEkle(bas, 41)}`), al(`takvim/aralik?bas=${v.bugun}&son=${gunEkle(v.bugun, 30)}`)]);
    S.gunler = ay.gunler; S.yaklasan = yakin.gunler;
    ciz();
  }
  const yenile = () => dene(yukle);

  function form(o, tarih) {
    const v = o ? o.veri : { baslik: "", tarih: tarih || S.secili || S.bugun, saat: "", bitis_saat: "", yer: "", aciklama: "", tur: "etkinlik", tekrar: "yok",
      tekrar_bitis: "", ders_id: null, ozel: false };
    const baslik = girdi("text", v.baslik, { maxlength: 200 }), tur = secim([["etkinlik", "Etkinlik"], ["sinav", "Sınav"], ["mesai", "Mesai"]], v.tur);
    const gun = girdi("date", v.tarih), saat = girdi("time", v.saat), bitis = girdi("time", v.bitis_saat), yer = girdi("text", v.yer, { maxlength: 200 });
    const tekrar = secim(TEKRAR, v.tekrar), tekrarBitis = girdi("date", v.tekrar_bitis), aciklama = metinAlani(v.aciklama, { maxlength: 2000 });
    const ders = secim([["", "—"], ...S.dersler.map((d) => [String(d.id), d.ad])], v.ders_id === null ? "" : v.ders_id);
    const ozel = isaretKutusu(U.OZEL_ETIKET, v.ozel);
    const sil = o ? el("button", { class: "dugme tehlike", type: "button", onclick: async () => {
      if (await dene(() => gonder("takvim/sil", { id: o.id }))) { kapat(); bildir("Etkinlik silindi."); yenile(); }
    } }, "Sil") : null;
    const kapat = pencere(o ? "Etkinliği düzelt" : "Yeni etkinlik", [
      alan("Başlık", baslik), el("div", { class: "uc" }, alan("Tarih", gun), alan("Başlangıç", saat), alan("Bitiş", bitis)),
      el("div", { class: "iki" }, alan("Tür", tur), alan("Yer", yer)),
      el("div", { class: "iki" }, alan("Tekrar", tekrar), alan("Tekrar bitişi", tekrarBitis, "Boşsa süresiz.")),
      S.dersler.length ? alan("Ders", ders, "Sınavı bir derse bağlarsan Ders ekranında da görünür.") : null,
      alan("Açıklama", aciklama), ozel.satir,
    ], { ek: sil, kaydet: async () => {
      const veri = { baslik: baslik.value, tarih: gun.value, saat: saat.value, bitis_saat: bitis.value, yer: yer.value, aciklama: aciklama.value, tur: tur.value,
        tekrar: tekrar.value, tekrar_bitis: tekrar.value === "yok" ? "" : tekrarBitis.value, ders_id: ders.value ? Number(ders.value) : null, ozel: ozel.kutu.checked };
      await gonder(o ? "takvim/guncelle" : "takvim/ekle", o ? { id: o.id, veri } : { veri });
      if (gun.value && (!o || gun.value !== v.tarih)) { S.secili = gun.value; S.ay = gun.value.slice(0, 7); }   // tekrarlayan etkinlikte serinin ilk ayına atlama
      yenile();
    } });
  }
  function ac(e) {
    if (e.uyg === "gorev") { location.href = "/panel/gorev"; return; }
    const o = S.ogeler.find((x) => x.id === e.oge_id);
    if (o) form(o);
  }

  const olayYazi = (e) => (e.saat ? e.saat + " " : "") + e.baslik;
  function gunKutusu(iso) {
    const olaylar = S.gunler[iso] || [], gosterilen = olaylar.slice(0, 3);
    const sinif = "gun" + (iso.slice(0, 7) !== S.ay ? " disi" : "") + (iso === S.bugun ? " bugun" : "") + (iso === S.secili ? " secili" : "");
    return el("button", { class: sinif, type: "button", "aria-label": `${tarihYaz(iso, S.bugun)}, ${olaylar.length} kayıt`, "aria-pressed": String(iso === S.secili),
      onclick: () => { S.secili = iso; ciz(); } },
      el("span", { class: "sayi" }, Number(iso.slice(8))), gosterilen.map((e) => el("span", { class: "olay " + e.tur }, olayYazi(e))),
      olaylar.length > 3 ? el("span", { class: "fazla" }, `+${olaylar.length - 3}`) : null);
  }
  function olaySatiri(e, iso) {
    return el("li", { class: "satir" }, el("div", { class: "govde" },
      el("button", { class: "baslik tik", type: "button", title: e.uyg === "gorev" ? "Görev'de aç" : "Düzelt", onclick: () => ac(e) }, e.baslik),
      el("div", { class: "meta" }, iso ? el("span", {}, tarihYaz(iso, S.bugun)) : null,
        el("span", {}, e.saat ? e.saat + (e.bitis_saat ? "–" + e.bitis_saat : "") : "Tüm gün"), rozet(TUR[e.tur], e.tur === "sinav" ? "kotu" : ""),
        e.yer ? el("span", {}, e.yer) : null)));
  }

  function ciz() {
    const [y, a] = S.ay.split("-").map(Number), bas = izgaraBasi();
    const gunler = Array.from({ length: 42 }, (_, i) => gunEkle(bas, i));
    const secili = S.gunler[S.secili] || [];
    const yakin = Object.entries(S.yaklasan).flatMap(([iso, l]) => l.map((e) => [iso, e])).slice(0, 12);
    U.ustBilgi(`${S.ogeler.length} etkinlik`);
    const git = (n) => async () => { if (n === 0) { S.ay = S.bugun.slice(0, 7); S.secili = S.bugun; } else ayKaydir(n); await yenile(); };
    U.koy(
      el("div", { class: "ay-ust" }, el("h2", {}, `${U.AYLAR[a - 1]} ${y}`),
        el("button", { class: "dugme", type: "button", "aria-label": "Önceki ay", onclick: git(-1) }, "‹"),
        el("button", { class: "dugme", type: "button", onclick: git(0) }, "Bugün"),
        el("button", { class: "dugme", type: "button", "aria-label": "Sonraki ay", onclick: git(1) }, "›"),
        el("span", { class: "bosluk" }), el("button", { class: "dugme vurgu", type: "button", onclick: () => form(null) }, "Etkinlik ekle")),
      el("div", { class: "ay" }, U.GUNLER.map((g) => el("div", { class: "gun-adi" }, g)), gunler.map(gunKutusu)),
      el("h2", {}, tarihYaz(S.secili, S.bugun)),
      secili.length ? el("ul", { class: "liste" }, secili.map((e) => olaySatiri(e))) : bos("Bu gün boş", "Etkinlik eklemek için sağ üstteki düğmeyi kullan."),
      el("h2", {}, "Yaklaşanlar (30 gün)"),
      yakin.length ? el("ul", { class: "liste" }, yakin.map(([iso, e]) => olaySatiri(e, iso))) : bos("Yaklaşan bir şey yok", "Önümüzdeki 30 günde etkinlik ya da son tarihli görev yok."));
  }

  yenile();
})();
