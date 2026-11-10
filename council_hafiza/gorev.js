// COUNCIL Görev: hızlı ekleme, Bugün / Bu hafta / Hepsi / Bitenler, hafızadaki (ajanların yazdığı) görevler.
"use strict";
(() => {
  const { el, al, gonder, dene, bildir, tarihYaz, alan, girdi, metinAlani, secim, isaretKutusu, pencere, rozet, cipler, bos } = U;
  const ONCELIK = { yuksek: "Yüksek", orta: "Orta", dusuk: "Düşük" }, SIRA = { yuksek: 0, orta: 1, dusuk: 2 };
  const S = { ogeler: [], hafiza: [], bugun: "", gorunum: "bugun", yansit: true, taslak: "" };

  async function yukle() {
    const [v, h] = await Promise.all([al("gorev/ogeler"), al("gorev/hafiza")]);
    Object.assign(S, { ogeler: v.ogeler, bugun: v.bugun, yansit: v.yansit, hafiza: h.kayitlar });
    ciz();
  }
  const acik = () => S.ogeler.filter((o) => o.durum === "acik");
  const gruplar = () => ({
    bugun: acik().filter((o) => o.turev.gecikti || o.turev.bugun),
    hafta: acik().filter((o) => o.turev.gecikti || o.turev.bu_hafta),
    hepsi: acik(),
    biten: S.ogeler.filter((o) => o.durum === "bitti").sort((a, b) => (b.veri.bitti_tarih || "").localeCompare(a.veri.bitti_tarih || "")),
  });
  const sirala = (l) => l.slice().sort((a, b) => (b.turev.gecikti - a.turev.gecikti) || ((a.veri.son_tarih || "9999").localeCompare(b.veri.son_tarih || "9999"))
    || (SIRA[a.veri.oncelik] - SIRA[b.veri.oncelik]) || (a.id - b.id));

  function degistir(o) {                                   // sunucudan dönen öğeyi listeye koyar
    const i = S.ogeler.findIndex((x) => x.id === o.id);
    if (i < 0) S.ogeler.push(o); else S.ogeler[i] = o;
    ciz();
  }
  const durum = U.tekSefer(async (o, yeni) => {
    const v = await dene(() => gonder("gorev/guncelle", { id: o.id, durum: yeni }));
    if (v) { degistir(v.oge); bildir(yeni === "bitti" ? "Görev tamamlandı." : "Görev yeniden açıldı."); }
  });

  function form(o) {
    const v = o ? o.veri : { baslik: "", aciklama: "", son_tarih: "", oncelik: "orta", etiket: "", ozel: false };
    const baslik = girdi("text", v.baslik, { maxlength: 300 }), aciklama = metinAlani(v.aciklama, { maxlength: 2000 });
    const son = girdi("date", v.son_tarih), oncelik = secim(Object.entries(ONCELIK), v.oncelik), etiket = girdi("text", v.etiket, { maxlength: 40 });
    const ozel = isaretKutusu(U.OZEL_ETIKET, v.ozel);
    const sil = o ? el("button", { class: "dugme tehlike", type: "button", onclick: async () => {
      const r = await dene(() => gonder("gorev/sil", { id: o.id }));
      if (r) { S.ogeler = S.ogeler.filter((x) => x.id !== o.id); kapat(); ciz(); bildir("Görev silindi."); }
    } }, "Sil") : null;
    const kapat = pencere(o ? "Görevi düzelt" : "Yeni görev", [
      alan("Başlık", baslik), alan("Açıklama", aciklama),
      el("div", { class: "uc" }, alan("Son tarih", son), alan("Öncelik", oncelik), alan("Etiket", etiket)), ozel.satir,
    ], { ek: sil, kaydet: async () => {
      const veri = { baslik: baslik.value, aciklama: aciklama.value, son_tarih: son.value, oncelik: oncelik.value, etiket: etiket.value, ozel: ozel.kutu.checked };
      const r = await gonder(o ? "gorev/guncelle" : "gorev/ekle", o ? { id: o.id, veri } : { veri });
      degistir(r.oge);
    } });
  }

  function satir(o) {
    const v = o.veri, bitti = o.durum === "bitti";
    const meta = el("div", { class: "meta" },
      v.son_tarih ? el("span", { class: o.turev.gecikti ? "kotu" : "" }, (o.turev.gecikti ? "Gecikti · " : "") + tarihYaz(v.son_tarih, S.bugun)) : null,
      v.oncelik === "yuksek" ? rozet("Yüksek", "vurgu") : (v.oncelik === "dusuk" ? rozet("Düşük") : null),
      v.etiket ? rozet(v.etiket) : null, v.ozel ? rozet("Özel", "dolu") : null,
      v.koken && v.koken.gorunurluk === "project" ? el("span", { class: "rozet dolu" }, el("span", { lang: "en" }, v.koken.proje), " projesine özel") : null,
      bitti && v.bitti_tarih ? el("span", {}, "Bitti: " + tarihYaz(v.bitti_tarih, S.bugun)) : null,
      o.kayit_id ? el("span", { title: "Hafızadaki kaydı" }, o.kayit_id) : null);
    return el("li", { class: "satir" + (bitti ? " bitti" : "") },
      el("button", { class: "kutucuk" + (bitti ? " dolu" : ""), type: "button", "aria-label": bitti ? "Yeniden aç" : "Tamamlandı olarak işaretle",
        onclick: () => durum(o, bitti ? "acik" : "bitti") }),
      el("div", { class: "govde" }, el("button", { class: "baslik tik", type: "button", title: "Düzelt", onclick: () => form(o) }, v.baslik),
        v.aciklama ? el("div", { class: "soluk" }, v.aciklama.length > 160 ? v.aciklama.slice(0, 160) + "…" : v.aciklama) : null, meta));
  }

  function hafizaSatiri(k) {
    const bitir = U.tekSefer(async () => {
      if (await dene(() => gonder("gorev/hafiza-bitir", { kayit: k.id }))) { S.hafiza = S.hafiza.filter((x) => x.id !== k.id); ciz(); bildir(`${k.id} tamamlandı olarak işaretlendi.`); }
    });
    const devral = U.tekSefer(async () => {
      const r = await dene(() => gonder("gorev/hafiza-al", { kayit: k.id }));
      if (r) { S.hafiza = S.hafiza.filter((x) => x.id !== k.id); S.gorunum = "hepsi"; degistir(r.oge); bildir("Görev alındı; tarih ve öncelik ekleyebilirsin."); }
    });
    return el("li", { class: "satir" },
      el("div", { class: "govde" }, el("div", { class: "baslik" }, k.metin),
        el("div", { class: "meta" }, el("span", {}, k.id), el("span", {}, `${k.arac}/${k.proje}`), k.tarih ? el("span", {}, k.tarih) : null,
          k.ozel ? rozet("Projeye özel", "dolu") : null)),
      el("div", { class: "eylemler" }, el("button", { class: "dugme", type: "button", onclick: bitir }, "Bitti"),
        el("button", { class: "dugme vurgu", type: "button", onclick: devral }, "Göreve al")));
  }

  function ciz() {
    const g = gruplar();
    U.ustBilgi(`${g.hepsi.length} açık · ${g.bugun.length} bugün`);
    const hizli = girdi("text", S.taslak, { placeholder: "Yeni görev: “yarın faturayı öde”, “cuma rapor !”", maxlength: 400, "aria-label": "Yeni görev" });
    hizli.addEventListener("input", () => { S.taslak = hizli.value; });      // yeniden çizimde yazılan kaybolmasın
    const gonderHizli = U.tekSefer(async () => {
      const r = await dene(() => gonder("gorev/hizli", { metin: hizli.value }));
      if (r) { S.taslak = ""; S.gorunum = r.oge.turev.bugun ? "bugun" : (r.oge.turev.bu_hafta ? "hafta" : "hepsi"); degistir(r.oge); U.$("uyg").querySelector(".hizli input").focus(); }
    });
    const ekle = (e) => {
      e.preventDefault();
      if (!hizli.value.trim()) { form(null); return; }
      gonderHizli();
    };
    const liste = S.gorunum === "hafiza" ? S.hafiza : (S.gorunum === "biten" ? g.biten : sirala(g[S.gorunum]));
    const BOS = { bugun: ["Bugün için görev yok", "Bugüne ya da geçmişe tarihlenmiş açık görev kalmadı."],
      hafta: ["Bu hafta boş", "Pazar gününe kadar tarihlenmiş açık görev yok."], hepsi: ["Açık görev yok", "Yukarıdaki satıra yazıp Enter'a bas."],
      biten: ["Biten görev yok", "Tamamladığın görevler burada durur."],
      hafiza: ["Hafızada bekleyen görev yok", "Hermes'e ya da Claude'a söylediğin işler hafızaya görev olarak düşünce burada görünür."] };
    U.koy(
      S.yansit ? null : el("p", { class: "duyuru" }, "Görevlerin hafızaya yansıtılması kapalı (Ayarlar). Ajanlar buradaki görevleri görmez."),
      el("form", { class: "hizli", onsubmit: ekle }, hizli, el("button", { class: "dugme vurgu", type: "submit" }, "Ekle")),
      el("p", { class: "not" }, "Tarih: bugün, yarın, gün adı, 21.11, 21 Kasım. Ünlem (!) yüksek öncelik. Boş bırakıp Ekle'ye basarsan ayrıntılı form açılır."),
      el("div", { class: "cubuk" }, cipler([["bugun", "Bugün", g.bugun.length], ["hafta", "Bu hafta", g.hafta.length], ["hepsi", "Hepsi", g.hepsi.length],
        ["biten", "Bitenler", g.biten.length], ["hafiza", "Hafızadan", S.hafiza.length]], S.gorunum, (k) => { S.gorunum = k; ciz(); })),
      liste.length ? el("ul", { class: "liste" }, liste.map(S.gorunum === "hafiza" ? hafizaSatiri : satir)) : bos(...BOS[S.gorunum]));
  }

  dene(yukle);
})();
