"""1. dalga uygulamalarının saf mantığı: alan doğrulama, hafıza yansıması metni, tekrar, seri, not hesabı, oruç durumu."""
import datetime as dt

import pytest

from council_hafiza import uyg_mantik as M

G = dt.date(2026, 11, 10)   # salı


# ------------------------------------------------------------------ doğrulama
def test_not_dogrulama_temizler_ve_sinirlar():
    v = M.dogrula("not", {"metin": "  Fırını saat 7'de kapat.  ", "etiketler": [" ev ", "ev", "", "mutfak"], "sabit": True})
    assert v == {"metin": "Fırını saat 7'de kapat.", "etiketler": ["ev", "mutfak"], "sabit": True, "ozel": False}
    for kotu in ({"metin": ""}, {"metin": "x" * 4001}, {"metin": 5}, {"metin": "a", "etiketler": "ev"},
                 {"metin": "a", "etiketler": ["e"] * 9}, {"metin": "a", "sabit": "evet"}):
        with pytest.raises(M.Gecersiz):
            M.dogrula("not", kotu)


def test_gizli_bilgi_hicbir_alanda_kabul_edilmez():
    for uyg, v in (("not", {"metin": "banka şifrem: Abc12345xyz"}),
                   ("gorev", {"baslik": "öde", "aciklama": "IBAN TR33 0006 1005 1978 6457 8413 26"}),
                   ("ders", {"ad": "Muhasebe", "uniteler": [{"ad": "token: ghp_abcdefghijklmnopqrstuvwxyz123456", "durum": "yok"}]}),
                   ("oruc", {"tur": "su", "baslangic": "2026-11-10T08:00", "hedef_saat": 24, "kirma_plani": "parolam: Abc12345xyz"})):
        with pytest.raises(M.Gecersiz, match="gizli bilgi"):
            M.dogrula(uyg, v)
    with pytest.raises(M.Gecersiz, match="gizli bilgi"):
        M.dogrula_gun("oruc", {"not": "kart 4111 1111 1111 1111"})


def test_bilinmeyen_alan_ve_uygulama_reddedilir():
    with pytest.raises(M.Gecersiz):
        M.dogrula("yok", {"metin": "a"})
    assert "kotu" not in M.dogrula("not", {"metin": "a", "kotu": 1})          # tanımsız alan sessizce atılır


def test_gorev_takvim_ders_aliskanlik_oruc_dogrulama():
    g = M.dogrula("gorev", {"baslik": "Faturayı öde", "son_tarih": "2026-11-12", "oncelik": "yuksek"})
    assert g["son_tarih"] == "2026-11-12" and g["oncelik"] == "yuksek" and g["aciklama"] == "" and g["etiket"] == ""
    assert M.dogrula("gorev", {"baslik": "a"})["oncelik"] == "orta"
    for kotu in ({"baslik": "a", "son_tarih": "12.11.2026"}, {"baslik": "a", "oncelik": "acil"}, {"baslik": " "}):
        with pytest.raises(M.Gecersiz):
            M.dogrula("gorev", kotu)

    t = M.dogrula("takvim", {"baslik": "Vize", "tarih": "2026-11-21", "saat": "09:30", "bitis_saat": "10:30", "tur": "sinav"})
    assert t["tekrar"] == "yok" and t["ders_id"] is None and t["yer"] == ""
    for kotu in ({"baslik": "a", "tarih": "2026-13-01"}, {"baslik": "a", "tarih": "2026-11-21", "saat": "25:00"},
                 {"baslik": "a", "tarih": "2026-11-21", "bitis_saat": "10:00"},                        # başlangıçsız bitiş
                 {"baslik": "a", "tarih": "2026-11-21", "saat": "10:00", "bitis_saat": "09:00"},
                 {"baslik": "a", "tarih": "2026-11-21", "tekrar": "haftalik", "tekrar_bitis": "2026-11-20"},
                 {"baslik": "a", "tarih": "2026-11-21", "tur": "parti"}, {"baslik": "a", "tarih": "2026-11-21", "ders_id": "3"}):
        with pytest.raises(M.Gecersiz):
            M.dogrula("takvim", kotu)

    d = M.dogrula("ders", {"ad": "Muhasebe", "uniteler": [{"ad": "Ünite 1", "durum": "bitti"}, {"ad": "Ünite 2"}], "ara": 60})
    assert d["uniteler"][1] == {"ad": "Ünite 2", "durum": "yok"} and d["ara"] == 60 and d["final"] is None and d["ara_agirlik"] == 30
    for kotu in ({"ad": "a", "ara": 101}, {"ad": "a", "ara": True}, {"ad": "a", "uniteler": [{"ad": "u", "durum": "yarim"}]},
                 {"ad": "a", "uniteler": [{"ad": "u"}] * 61}, {"ad": "a", "ara_agirlik": -1}):
        with pytest.raises(M.Gecersiz):
            M.dogrula("ders", kotu)

    a = M.dogrula("aliskanlik", {"ad": "Okuma", "gunler": [4, 0, 0, 2]})
    assert a["gunler"] == [0, 2, 4]
    for kotu in ({"ad": "a", "gunler": [7]}, {"ad": "a", "gunler": "0"}, {"ad": ""}):
        with pytest.raises(M.Gecersiz):
            M.dogrula("aliskanlik", kotu)

    o = M.dogrula("oruc", {"tur": "su", "baslangic": "2026-11-10T08:00", "hedef_saat": 672})
    assert o["bitis"] == "" and o["sonuc"] == ""
    for kotu in ({"tur": "su", "baslangic": "2026-11-10 08:00", "hedef_saat": 24}, {"tur": "su", "baslangic": "2026-11-10T08:00", "hedef_saat": 0},
                 {"tur": "su", "baslangic": "2026-11-10T08:00", "hedef_saat": 24, "bitis": "2026-11-09T08:00"},
                 {"tur": "hava", "baslangic": "2026-11-10T08:00", "hedef_saat": 24}):
        with pytest.raises(M.Gecersiz):
            M.dogrula("oruc", kotu)


def test_gun_verisi_dogrulama():
    assert M.dogrula_gun("aliskanlik", {"tamam": True}) == {"tamam": True}
    assert M.dogrula_gun("aliskanlik", {"tamam": False}) is None                                  # işaret kaldırılır
    g = M.dogrula_gun("oruc", {"su_ml": 2500, "elektrolit": True, "kilo": 81.4, "his": 3, "belirtiler": ["bas_agrisi"], "not": "iyi"})
    assert g == {"su_ml": 2500, "elektrolit": True, "kilo": 81.4, "his": 3, "belirtiler": ["bas_agrisi"], "not": "iyi"}
    for kotu in ({"su_ml": -1}, {"kilo": 10}, {"his": 6}, {"belirtiler": ["uydurma"]}, {"elektrolit": "evet"}):
        with pytest.raises(M.Gecersiz):
            M.dogrula_gun("oruc", kotu)


# ------------------------------------------------------------------ hafıza yansıması
def test_yansima_metinleri_mutlak_tarihli_ve_tek_bilgi():
    n = M.kayit("not", M.dogrula("not", {"metin": "Fırını kapat.", "etiketler": ["ev"]}), "acik")
    assert n == {"text": "Fırını kapat.", "context": "Not uygulaması", "keys": ["ev"], "kind": "fact"}

    g = M.kayit("gorev", M.dogrula("gorev", {"baslik": "Faturayı öde.", "son_tarih": "2026-11-12", "oncelik": "yuksek", "etiket": "ev"}), "acik")
    assert g["text"] == "Görev: Faturayı öde. Son tarih: 2026-11-12. Öncelik: yüksek." and g["kind"] == "task" and g["keys"] == ["ev"]
    assert M.kayit("gorev", M.dogrula("gorev", {"baslik": "Ara"}), "acik")["text"] == "Görev: Ara."

    t = M.kayit("takvim", M.dogrula("takvim", {"baslik": "Muhasebe vizesi", "tarih": "2026-11-21", "saat": "09:30", "bitis_saat": "10:30",
                                              "yer": "A Blok", "tur": "sinav"}), "acik")
    assert t["text"] == "Sınav: Muhasebe vizesi — 2026-11-21 09:30–10:30, A Blok." and t["kind"] == "event"
    t2 = M.kayit("takvim", M.dogrula("takvim", {"baslik": "Vardiya", "tarih": "2026-11-09", "tur": "mesai", "tekrar": "haftalik",
                                               "tekrar_bitis": "2026-12-31"}), "acik")
    assert t2["text"] == "Mesai: Vardiya — 2026-11-09 (her hafta, 2026-12-31 tarihine kadar)."

    d = M.kayit("ders", M.dogrula("ders", {"ad": "Muhasebe", "kurum": "Üniversite", "donem": "2026 güz", "ara": 60, "final": 80,
                                          "uniteler": [{"ad": "1", "durum": "bitti"}, {"ad": "2"}, {"ad": "3", "durum": "bitti"}]}), "acik")
    assert d["text"] == "Ders: Muhasebe (Üniversite, 2026 güz). 2/3 ünite bitti. Ara sınav 60, final 80, ortalama 74." and d["kind"] == "fact"
    assert M.kayit("ders", M.dogrula("ders", {"ad": "Hukuk"}), "bitti")["text"] == "Ders: Hukuk. Ders tamamlandı."

    a = M.kayit("aliskanlik", M.dogrula("aliskanlik", {"ad": "Okuma", "gunler": [0, 2, 4]}), "acik")
    assert a["text"] == "Alışkanlık: Okuma (Pzt, Çar, Cum)." and a["kind"] == "plan"
    assert M.kayit("aliskanlik", M.dogrula("aliskanlik", {"ad": "Su"}), "acik")["text"] == "Alışkanlık: Su (her gün)."

    o = M.dogrula("oruc", {"tur": "su", "baslangic": "2026-11-10T08:00", "hedef_saat": 672})
    assert M.kayit("oruc", o, "acik")["text"] == "Oruç başladı: 2026-11-10 08:00, hedef 28 gün (su orucu)."
    o2 = dict(o, bitis="2026-11-12T20:00", sonuc="erken")
    assert M.kayit("oruc", o2, "bitti")["text"] == "Oruç: 2026-11-10 08:00 – 2026-11-12 20:00 (2 gün 12 saat), erken bitirildi (su orucu)."


def test_ozel_silinen_ve_biten_ogeler_yansimaz():
    ozel = M.dogrula("not", {"metin": "Günlük.", "ozel": True})
    assert M.kayit("not", ozel, "acik") is None and M.kapanis("not", "acik") == ("arsiv", "Not: özel yapıldı, hafızadan kaldırıldı")
    acik = M.dogrula("gorev", {"baslik": "Ara"})
    assert M.kayit("gorev", acik, "silindi") is None and M.kapanis("gorev", "silindi") == ("arsiv", "Görev: uygulamadan silindi")
    assert M.kayit("gorev", acik, "bitti") is None and M.kapanis("gorev", "bitti") == ("gecersiz", "Görev: tamamlandı")
    assert M.kayit("aliskanlik", M.dogrula("aliskanlik", {"ad": "Su"}), "bitti") is None
    assert M.kapanis("aliskanlik", "bitti") == ("gecersiz", "Alışkanlık: bırakıldı")


def test_sure_yazimi():
    assert [M.sure_yaz(s) for s in (0.4, 1, 16, 24, 52, 672, 60.5)] == ["1 saatten az", "1 saat", "16 saat", "1 gün", "2 gün 4 saat", "28 gün", "2 gün 12 saat"]


# ------------------------------------------------------------------ takvim
def test_tekrarlayan_etkinlik_gunleri():
    f = lambda **k: [d.isoformat() for d in M.olay_gunleri(M.dogrula("takvim", {"baslik": "x", **k}), dt.date(2026, 11, 1), dt.date(2026, 11, 30))]
    assert f(tarih="2026-11-21") == ["2026-11-21"]
    assert f(tarih="2026-10-21") == [] and f(tarih="2026-12-01") == []
    assert f(tarih="2026-11-27", tekrar="gunluk") == ["2026-11-27", "2026-11-28", "2026-11-29", "2026-11-30"]
    assert f(tarih="2026-10-05", tekrar="haftalik") == ["2026-11-02", "2026-11-09", "2026-11-16", "2026-11-23", "2026-11-30"]
    assert f(tarih="2026-10-05", tekrar="haftalik", tekrar_bitis="2026-11-10") == ["2026-11-02", "2026-11-09"]
    assert f(tarih="2026-08-15", tekrar="aylik") == ["2026-11-15"]
    assert f(tarih="2026-08-31", tekrar="aylik") == []                              # kasımda 31 yok: o ay atlanır
    assert f(tarih="2020-11-03", tekrar="yillik") == ["2026-11-03"]
    g = lambda y: [d.isoformat() for d in M.olay_gunleri(M.dogrula("takvim", {"baslik": "x", "tarih": "2024-02-29", "tekrar": "yillik"}),
                                                       dt.date(y, 1, 1), dt.date(y, 12, 31))]
    assert g(2026) == [] and g(2028) == ["2028-02-29"]


# ------------------------------------------------------------------ ders
def test_not_hesabi():
    assert M.not_hesabi(60, 80, 30, None) == {"ortalama": 74.0, "gereken_final": None, "ulasilamaz": False}
    assert M.not_hesabi(40, None, 30, 50) == {"ortalama": None, "gereken_final": 54.3, "ulasilamaz": False}
    assert M.not_hesabi(10, None, 30, 90)["ulasilamaz"] is True
    assert M.not_hesabi(100, None, 30, 20)["gereken_final"] == 0.0                  # hedef zaten tutmuş: eksi not olmaz
    assert M.not_hesabi(None, None, 30, 50) == {"ortalama": None, "gereken_final": None, "ulasilamaz": False}
    assert M.not_hesabi(50, None, 100, 60)["gereken_final"] is None                 # finalin ağırlığı yok
    d = M.dogrula("ders", {"ad": "a", "uniteler": [{"ad": "1", "durum": "bitti"}, {"ad": "2", "durum": "calisiliyor"}, {"ad": "3"}, {"ad": "4"}]})
    assert M.ders_ilerleme(d) == {"bitti": 1, "calisiliyor": 1, "toplam": 4, "yuzde": 25}
    assert M.ders_ilerleme(M.dogrula("ders", {"ad": "a"}))["yuzde"] == 0


# ------------------------------------------------------------------ alışkanlık
def test_seri_bugun_isaretlenmediyse_bozulmaz_dun_bos_kaldiysa_bozulur():
    gun = lambda n: (G - dt.timedelta(days=n)).isoformat()
    s = M.seri([], {gun(1), gun(2), gun(3)}, G)
    assert s["seri"] == 3 and s["bugun_planli"] and not s["bugun_tamam"] and s["en_uzun"] == 3
    assert M.seri([], {gun(0), gun(1), gun(2), gun(3)}, G)["seri"] == 4
    assert M.seri([], {gun(2), gun(3)}, G)["seri"] == 0                             # dün boş: seri bitti
    assert M.seri([], set(), G)["seri"] == 0
    uzun = M.seri([], {gun(0), gun(5), gun(6), gun(7), gun(8)}, G)
    assert uzun["seri"] == 1 and uzun["en_uzun"] == 4


def test_seri_yalniz_planli_gunleri_sayar():
    # Pzt-Çar-Cum alışkanlığı; bugün salı (planlı değil). Pzt (dün) ve geçen Cum, Çar işaretli; aradaki günler sayılmaz.
    isaret = {"2026-11-09", "2026-11-06", "2026-11-04"}
    s = M.seri([0, 2, 4], isaret, G)
    assert s["seri"] == 3 and not s["bugun_planli"]
    assert M.seri([0, 2, 4], {"2026-11-09", "2026-11-04"}, G)["seri"] == 1         # cuma atlandı
    assert [x["gun"] for x in s["son7"]] == [(G - dt.timedelta(days=n)).isoformat() for n in range(6, -1, -1)]
    assert [x["planli"] for x in s["son7"]] == [True, False, True, False, False, True, False]
    assert s["son7"][5] == {"gun": "2026-11-09", "planli": True, "tamam": True}


# ------------------------------------------------------------------ oruç
def test_oruc_durumu_sayac_evre_ve_hedef():
    o = M.dogrula("oruc", {"tur": "su", "baslangic": "2026-11-10T08:00", "hedef_saat": 672})
    d = M.oruc_durumu(o, "acik", dt.datetime(2026, 11, 11, 20, 0))
    assert d["gecen_saat"] == 36.0 and d["kalan_saat"] == 636.0 and d["yuzde"] == 5 and d["gun"] == 2
    assert d["hedef_bitis"] == "2026-12-08T08:00" and d["evre"]["ad"] == "İlk günler" and d["uzun"] is True
    assert M.oruc_durumu(o, "acik", dt.datetime(2026, 11, 10, 7, 0))["gecen_saat"] == 0.0          # henüz başlamadı: eksi olmaz
    bitmis = dict(o, bitis="2026-11-12T20:00", sonuc="erken")
    b = M.oruc_durumu(bitmis, "bitti", dt.datetime(2026, 12, 1, 0, 0))
    assert b["gecen_saat"] == 60.0 and b["kalan_saat"] == 0.0                                       # biten oruçta sayaç durur
    kisa = M.dogrula("oruc", {"tur": "aralikli", "baslangic": "2026-11-10T20:00", "hedef_saat": 16})
    k = M.oruc_durumu(kisa, "acik", dt.datetime(2026, 11, 11, 13, 0))
    assert k["yuzde"] == 100 and k["kalan_saat"] == 0.0 and k["uzun"] is False and k["evre"]["ad"] == "Geçiş"
    evreler = [M.oruc_durumu(o, "acik", dt.datetime(2026, 11, 10, 8, 0) + dt.timedelta(hours=h))["evre"]["ad"] for h in (1, 13, 30, 100, 200)]
    assert evreler == ["Başlangıç", "Geçiş", "İlk günler", "Uyum", "Uzun oruç"]


def test_belirti_uyarisi_tehlikeyi_one_alir():
    assert M.belirti_uyarisi([]) == {"duzey": "", "mesaj": ""}
    d = M.belirti_uyarisi(["bas_agrisi", "halsizlik"])
    assert d["duzey"] == "dikkat" and "artarsa" in d["mesaj"]
    t = M.belirti_uyarisi(["bas_agrisi", "gogus_agrisi"])
    assert t["duzey"] == "tehlike" and "112" in t["mesaj"] and "bırak" in t["mesaj"]
    assert set(M.TEHLIKE) <= set(M.BELIRTILER) and len(M.TEHLIKE) >= 5


# ------------------------------------------------------------------ tarih bulma ve hızlı görev
def test_tarih_bul():
    f = lambda s: (M.tarih_bul(s, G) or (None,))[0]
    assert f("toplantı 2026-11-21 günü") == "2026-11-21"
    assert f("21.11.2026 teslim") == "2026-11-21" and f("21/11/2026") == "2026-11-21"
    assert f("teslim 21.11") == "2026-11-21" and f("teslim 05.01") == "2027-01-05"        # geçmiş gün/ay: gelecek yıl
    assert f("21 Kasım 2026 sınav") == "2026-11-21" and f("3 aralık toplantı") == "2026-12-03" and f("3 ARALIK") == "2026-12-03"
    assert f("bugün ara") == "2026-11-10" and f("Yarın ara") == "2026-11-11"
    assert f("cuma teslim") == "2026-11-13" and f("salı toplantı") == "2026-11-17"       # bugün salı: gelecek salı
    assert f("pazartesi") == "2026-11-16" and f("PAZAR gezi") == "2026-11-15"
    assert f("fırını kapat") is None and f("sürüm 1.2.3 çıktı") is None and f("32.13.2026") is None
    assert f("yarınki iş") is None and f("pazarlama toplantısı") is None                  # sözcüğün parçası tarih sayılmaz
    assert M.tarih_bul("ara yarın sabah", G) == ("2026-11-11", 4, 9)
    # notlarda yalnız açık yazılmış tarih önerilir: "bugün yorgunum" bir etkinlik değildir
    acik = lambda s: (M.tarih_bul(s, G, goreli=False) or (None,))[0]
    assert acik("bugün yorgunum") is None and acik("cuma günü güzeldi") is None and acik("yarın bakarım") is None
    assert acik("bakım 21.11.2026 günü") == "2026-11-21" and acik("3 aralık toplantı") == "2026-12-03"


def test_hizli_gorev_cozumu():
    assert M.gorev_coz("yarın faturayı öde", G) == {"baslik": "faturayı öde", "son_tarih": "2026-11-11", "oncelik": "orta"}
    assert M.gorev_coz("! raporu gönder cuma", G) == {"baslik": "raporu gönder", "son_tarih": "2026-11-13", "oncelik": "yuksek"}
    assert M.gorev_coz("ekmek al", G) == {"baslik": "ekmek al", "son_tarih": "", "oncelik": "orta"}
    assert M.gorev_coz("21.11 vize!", G) == {"baslik": "vize", "son_tarih": "2026-11-21", "oncelik": "yuksek"}
    assert M.gorev_coz("yarın", G)["baslik"] == "yarın"                                    # yalnız tarih: başlık boş kalmaz


# ------------------------------------------------------------------ ayarlar
def test_ayar_dogrulama_ve_sessiz_saat():
    a = M.ayar_dogrula({"saat_dilimi": "Europe/Istanbul", "sessiz_acik": True, "sessiz_bas": "23:00", "sessiz_son": "08:00",
                        "yansit": {"not": False}})
    assert a["yansit"] == {"not": False, "gorev": True, "takvim": True, "ders": True, "aliskanlik": True, "oruc": True}
    assert M.ayar_dogrula({}) == M.VARSAYILAN_AYAR
    for kotu in ({"saat_dilimi": "Mars/Olympus"}, {"sessiz_bas": "25:00"}, {"yansit": {"yok": True}}, {"sessiz_acik": "evet"}):
        with pytest.raises(M.Gecersiz):
            M.ayar_dogrula(kotu)
    assert [M.sessiz_mi(a, s) for s in ("22:59", "23:00", "03:00", "07:59", "08:00")] == [False, True, True, True, False]
    gunduz = dict(a, sessiz_bas="13:00", sessiz_son="14:00")
    assert [M.sessiz_mi(gunduz, s) for s in ("12:59", "13:30", "14:00")] == [False, True, False]
    assert M.sessiz_mi(dict(a, sessiz_acik=False), "03:00") is False
    assert M.sessiz_kaydi(a) == {"text": "Sessiz saatler: 23:00–08:00. Bu saatlerde bildirim ve hatırlatma gönderilmez.",
                                 "context": "Ayarlar uygulaması", "keys": ["sessiz saat", "bildirim", "quiet hours"], "kind": "preference"}
    assert M.sessiz_kaydi(dict(a, sessiz_acik=False)) is None


# ------------------------------------------------------------------ bağımsız incelemenin bulguları (2026-11-10)
def test_dogrulama_bozuk_girdide_hata_verir_cokmez():
    oruc = {"tur": "su", "baslangic": "2026-11-10T08:00", "hedef_saat": 24}
    for uyg, v in (("oruc", dict(oruc, hedef_saat=None)),                           # zorunlu alan açıkça boş
                   ("oruc", dict(oruc, hedef_saat=float("inf"))), ("oruc", dict(oruc, baslangic="9999-12-31T23:59")),
                   ("oruc", dict(oruc, tur=[])), ("takvim", {"baslik": "a", "tarih": "2026-11-21", "tur": []}),
                   ("takvim", {"baslik": "a", "tarih": "2026-11-21", "tekrar": {}}),
                   ("takvim", {"baslik": "a", "tarih": "1899-12-31"}), ("takvim", {"baslik": "a", "tarih": "2201-01-01"}),
                   ("takvim", {"baslik": "a", "tarih": "2026-11-21", "ders_id": 10 ** 30}),
                   ("not", {"metin": "a", "etiketler": ["\ud800"]}), ("gorev", {"baslik": "a", "oncelik": ["orta"]})):
        with pytest.raises(M.Gecersiz):
            M.dogrula(uyg, v)
    for v in ({"su_ml": float("inf")}, {"his": 1e999}, {"kilo": float("nan")}):
        with pytest.raises(M.Gecersiz):
            M.dogrula_gun("oruc", v)
    assert M.dogrula("takvim", {"baslik": "Doğum günü", "tarih": "1990-05-04", "tekrar": "yillik"})["tarih"] == "1990-05-04"


def test_gizli_bilgi_denetimi_alanlari_birlestirmez():
    """Alanlar ayrı ayrı taranır: başlığın sonundaki sayı bir sonraki alandaki tarihle birleşip kart numarası sanılmasın."""
    assert M.dogrula("gorev", {"baslik": "Kira 15000", "son_tarih": "2026-11-01"})["baslik"] == "Kira 15000"
    assert M.dogrula("gorev", {"baslik": "Kira 15000", "son_tarih": "2026-11-19"})
    assert M.dogrula("gorev", {"baslik": "yenile e-devlet şifresi", "son_tarih": "2026-11-11"})
    assert M.dogrula("takvim", {"baslik": "Sınav 203", "tarih": "2026-11-01", "saat": "15:30"})
    for kotu in ({"baslik": "şifre Abc12345xyz"}, {"baslik": "a", "aciklama": "kart 4111 1111 1111 1111"}):
        with pytest.raises(M.Gecersiz, match="gizli bilgi"):
            M.dogrula("gorev", kotu)


def test_tarih_bul_nokta_yil_ve_ondalik():
    f = lambda s: (M.tarih_bul(s, G) or (None,))[0]
    assert f("Sınav tarihi 21.11.2026.") == "2026-11-21" and f("Teslim 2026-11-21.") == "2026-11-21"       # cümle sonu noktası
    assert f("faturayı öde yarın.") == "2026-11-11" and f("raporu gönder cuma.") == "2026-11-13"
    assert f("Sözleşme bitişi 15 Haziran 2028.") == "2028-06-15"                                           # yıl düşmez
    assert f("1.5 litre su iç") is None and f("iOS 18.2 güncelle") is None and f("saat 9.05 dişçi") is None   # ondalık, sürüm, saat
    assert f("saat 10.12'de toplantı") is None and f("teslim 21.11") == "2026-11-21" and f("5.1.2027 teslim") == "2027-01-05"
    assert M.gorev_coz("Sözleşme bitişi 15 Haziran 2028.", G) == {"baslik": "Sözleşme bitişi", "son_tarih": "2028-06-15", "oncelik": "orta"}
    assert M.gorev_coz("1.5 litre su iç", G) == {"baslik": "1.5 litre su iç", "son_tarih": "", "oncelik": "orta"}


def test_saat_dilimi_verisi_olmayan_sistemde_varsayilan_calisir(monkeypatch):
    """Windows'ta sistemde saat dilimi verisi yoktur (tzdata paketi de kurulu değilse ZoneInfo hata verir). Varsayılan
    Europe/Istanbul ve UTC yine çalışmalı: Türkiye 2016'dan beri sabit UTC+3. Başka dilim istenirse anlaşılır hata."""
    import zoneinfo

    def yok(ad):
        raise zoneinfo.ZoneInfoNotFoundError(ad)
    monkeypatch.setattr(M, "_zoneinfo", yok)
    assert M.dilim("Europe/Istanbul").utcoffset(None) == dt.timedelta(hours=3) and M.dilim("UTC").utcoffset(None) == dt.timedelta(0)
    assert M.ayar_dogrula({}) == M.VARSAYILAN_AYAR and M.ayar_dogrula({"saat_dilimi": "UTC"})["saat_dilimi"] == "UTC"
    with pytest.raises(M.Gecersiz, match="saat dilimi verisi"):
        M.ayar_dogrula({"saat_dilimi": "Europe/Berlin"})
    from council_hafiza import uygulamalar as U
    utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    assert abs((U._saat("Europe/Istanbul") - utc).total_seconds() - 3 * 3600) < 120
