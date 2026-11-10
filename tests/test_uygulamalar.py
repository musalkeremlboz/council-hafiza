"""1. dalga uygulamaları: depo tabloları, hafızaya yansıtma, web uçları (oturum + CSRF), ajanlar için günlük özet."""
import datetime as dt
import json

import pytest
from fastmcp import FastMCP
from starlette.testclient import TestClient

from council_hafiza import panel, uygulamalar as U
from council_hafiza.auth import hash_password
from council_hafiza.store import Actor, Store

PAROLA = "dogru-parola-123"


class SahteAuth:
    def __init__(self, h):
        self.admin_hash = h

    def giris_engelli(self, ip):
        return False

    def giris_kaydet(self, ip, ok):
        pass


@pytest.fixture
def depo(tmp_path):
    return Store(tmp_path / "u.sqlite", anahtar="")


# ------------------------------------------------------------------ depo
def test_oge_tablosu_yasam_dongusu_ve_gunluk(depo):
    a = Actor("gorev", "genel")
    i = depo.uyg_ekle(a, "gorev", {"baslik": "Faturayı öde"})
    o = depo.uyg_al(i)
    assert o["uyg"] == "gorev" and o["veri"] == {"baslik": "Faturayı öde"} and o["durum"] == "acik" and o["kayit_id"] is None
    assert depo.uyg_guncelle(a, i, veri={"baslik": "Faturayı öde", "son_tarih": "2026-11-12"}, durum="bitti", kayit_id="R00001")
    o2 = depo.uyg_al(i)
    assert o2["durum"] == "bitti" and o2["kayit_id"] == "R00001" and o2["veri"]["son_tarih"] == "2026-11-12"
    assert o2["guncelleme"] >= o["guncelleme"] and o2["olusturma"] == o["olusturma"]
    assert depo.uyg_guncelle(a, i, kayit_id=None) and depo.uyg_al(i)["kayit_id"] is None and depo.uyg_al(i)["durum"] == "bitti"
    assert not depo.uyg_guncelle(a, 999, durum="silindi") and depo.uyg_al(999) is None

    j = depo.uyg_ekle(Actor("not", "genel"), "not", {"metin": "x"})
    depo.uyg_guncelle(a, j, durum="silindi")
    assert [x["id"] for x in depo.uyg_liste("gorev")] == [i] and depo.uyg_liste("not") == []          # silinen varsayılan listede yok
    assert [x["id"] for x in depo.uyg_liste("not", ("silindi",))] == [j]

    olaylar = depo.q("SELECT action, payload FROM events ORDER BY seq")
    assert [e["action"] for e in olaylar] == ["uyg_ekle", "uyg_guncelle", "uyg_guncelle", "uyg_ekle", "uyg_guncelle"]
    assert "Faturayı" not in "".join(e["payload"] for e in olaylar)                                   # günlükte içerik yok
    assert json.loads(olaylar[1]["payload"]) == {"uyg": "gorev", "id": i, "alanlar": ["baslik", "son_tarih"], "durum": "bitti"}
    assert depo.verify_chain()


def test_gune_bagli_veri_ve_ayarlar(depo):
    a = Actor("aliskanlik", "genel")
    i = depo.uyg_ekle(a, "aliskanlik", {"ad": "Okuma"})
    depo.gun_yaz(a, i, "2026-11-09", {"tamam": True})
    depo.gun_yaz(a, i, "2026-11-10", {"tamam": True})
    depo.gun_yaz(a, i, "2026-11-10", {"tamam": True, "not": "iki kez"})                              # aynı gün: üstüne yazar
    assert depo.gunler(i) == {"2026-11-09": {"tamam": True}, "2026-11-10": {"tamam": True, "not": "iki kez"}}
    assert depo.gunler(i, bas="2026-11-10") == {"2026-11-10": {"tamam": True, "not": "iki kez"}}
    depo.gun_yaz(a, i, "2026-11-09", None)                                                            # None: o gün silinir
    assert list(depo.gunler(i)) == ["2026-11-10"]
    assert depo.ayar_al() == {}
    depo.ayar_yaz(Actor("ayarlar", "genel"), {"saat_dilimi": "Europe/Istanbul", "yansit": {"not": False}})
    depo.ayar_yaz(Actor("ayarlar", "genel"), {"sessiz_acik": True})
    assert depo.ayar_al() == {"saat_dilimi": "Europe/Istanbul", "yansit": {"not": False}, "sessiz_acik": True}
    assert depo.verify_chain()


# ------------------------------------------------------------------ web düzeneği
SIMDI = dt.datetime(2026, 11, 10, 14, 0)        # salı


@pytest.fixture
def ortam(tmp_path, monkeypatch):
    st = Store(tmp_path / "u.sqlite", anahtar="")
    (tmp_path / "denetim").mkdir()
    monkeypatch.setenv("COUNCIL_DENETIM_DIR", str(tmp_path / "denetim"))
    monkeypatch.setattr(U, "_saat", lambda dilim: SIMDI)
    m = FastMCP("t")
    panel.kaydet(m, SahteAuth(hash_password(PAROLA)), st)
    c = TestClient(m.http_app(), base_url="https://test")
    assert c.post("/panel/giris", data={"parola": PAROLA}, follow_redirects=False).status_code == 303
    csrf = c.get("/panel/gezgin/oturum").json()["csrf"]

    def post(yol, govde, kod=200):
        r = c.post(f"/panel/uyg/{yol}", content=json.dumps(govde), headers={"Content-Type": "application/json", "X-CSRF": csrf})
        assert r.status_code == kod, r.text
        return r.json()

    def get(yol):
        r = c.get(f"/panel/uyg/{yol}")
        assert r.status_code == 200, r.text
        return r.json()
    return type("O", (), dict(st=st, c=c, post=staticmethod(post), get=staticmethod(get)))


def kayit_say(st):
    return st.q("SELECT COUNT(*) AS n FROM records")[0]["n"]


def test_sayfalar_dosyalar_ve_koruma(ortam, tmp_path):
    c = ortam.c
    for uyg, ad in (("not", "Not"), ("gorev", "Görev"), ("takvim", "Takvim"), ("ders", "Ders"), ("aliskanlik", "Alışkanlık"),
                    ("oruc", "Oruç"), ("ayarlar", "Ayarlar")):
        r = c.get(f"/panel/{uyg}")
        assert r.status_code == 200 and f'data-uyg="{uyg}"' in r.text and f"<title>COUNCIL {ad}</title>" in r.text
        assert f"/panel/uyg/dosya/{uyg}.js" in r.text and "/panel/kimlik.css" in r.text
        assert "script-src 'self'" in r.headers["content-security-policy"] and "<script>" not in r.text and "style=" not in r.text
        js = c.get(f"/panel/uyg/dosya/{uyg}.js")
        assert js.status_code == 200 and js.headers["content-type"].startswith("text/javascript") and len(js.text) > 200
    for ad in ("uygulama.js", "uygulama.css"):
        assert c.get(f"/panel/uyg/dosya/{ad}").status_code == 200
    for kotu in ("panel.py", "..%2Fserver.py", "yok.js"):
        assert c.get(f"/panel/uyg/dosya/{kotu}").status_code == 404
    # CSRF'siz ya da başka siteden yazma reddedilir; hiçbir şey yazılmaz
    govde = json.dumps({"veri": {"metin": "x"}})
    assert c.post("/panel/uyg/not/ekle", content=govde, headers={"Content-Type": "application/json"}).status_code == 403
    assert ortam.st.uyg_liste("not") == []
    # oturumsuz: sayfa girişe yönlenir, uçlar 401
    m = FastMCP("t2")
    panel.kaydet(m, SahteAuth(hash_password(PAROLA)), Store(tmp_path / "v.sqlite", anahtar=""))
    c2 = TestClient(m.http_app(), base_url="https://test")
    assert c2.get("/panel/gorev", follow_redirects=False).status_code == 303
    assert c2.get("/panel/uyg/gorev/ogeler").status_code == 401 and c2.get("/panel/uyg/ayarlar/veri").status_code == 401
    assert c2.post("/panel/uyg/gorev/ekle", content="{}", headers={"Content-Type": "application/json"}).status_code == 401


# ------------------------------------------------------------------ not
def test_not_hafizaya_yansir_duzeltilince_yenilenir_silinince_arsivlenir(ortam):
    st = ortam.st
    o = ortam.post("not/ekle", {"veri": {"metin": "Kombi bakımı 21.11.2026 günü yapılacak.", "etiketler": ["ev"]}})["oge"]
    r1 = st.get(o["kayit_id"])
    assert (r1["text"], r1["tool"], r1["project"], r1["visibility"], r1["trust"], r1["kind"], r1["valid_from"]) == \
        ("Kombi bakımı 21.11.2026 günü yapılacak.", "not", "genel", "shared", "user", "fact", "2026-11-10")
    assert json.loads(r1["keys"]) == ["ev"] and o["turev"]["tarih_onerisi"] == "2026-11-21"

    n = kayit_say(st)
    o_ayni = ortam.post("not/guncelle", {"id": o["id"], "veri": {"metin": "Kombi bakımı 21.11.2026 günü yapılacak.", "etiketler": ["ev"], "sabit": True}})["oge"]
    assert o_ayni["kayit_id"] == o["kayit_id"] and kayit_say(st) == n and o_ayni["veri"]["sabit"] is True     # yansıma aynı: yeni kayıt yok

    o2 = ortam.post("not/guncelle", {"id": o["id"], "veri": {"metin": "Kombi bakımı 22.11.2026 günü yapılacak.", "etiketler": ["ev"]}})["oge"]
    assert o2["kayit_id"] != o["kayit_id"] and st.get(o["kayit_id"])["superseded_by"] == o2["kayit_id"] and st.is_current(o2["kayit_id"])

    ortam.post("not/sil", {"id": o["id"]})
    assert st.get(o2["kayit_id"])["archived"] == 1 and ortam.get("not/ogeler")["ogeler"] == []
    assert st.uyg_al(o["id"])["durum"] == "silindi" and st.verify_chain()                                    # öğe silinmez, işaretlenir


def test_ozel_not_hafizaya_yazilmaz_ve_gizli_bilgi_hic_kaydedilmez(ortam):
    st = ortam.st
    o = ortam.post("not/ekle", {"veri": {"metin": "Bugün moralim bozuktu.", "ozel": True}})["oge"]
    assert o["kayit_id"] is None and kayit_say(st) == 0 and o["turev"]["tarih_onerisi"] is None             # "bugün" bir etkinlik tarihi değil
    acik = ortam.post("not/guncelle", {"id": o["id"], "veri": {"metin": "Bugün moralim bozuktu."}})["oge"]
    assert st.is_current(acik["kayit_id"])
    yine_ozel = ortam.post("not/guncelle", {"id": o["id"], "veri": {"metin": "Bugün moralim bozuktu.", "ozel": True}})["oge"]
    assert yine_ozel["kayit_id"] is None and st.get(acik["kayit_id"])["archived"] == 1
    oncesi = (len(st.uyg_liste("not")), kayit_say(st))
    r = ortam.post("not/ekle", {"veri": {"metin": "Banka şifrem: Abc12345xyz"}}, kod=400)
    assert "gizli bilgi" in r["hata"] and (len(st.uyg_liste("not")), kayit_say(st)) == oncesi
    assert "hata" in ortam.post("not/guncelle", {"id": 999, "veri": {"metin": "x"}}, kod=404)
    assert "hata" in ortam.post("not/guncelle", {"id": o["id"], "durum": "bitti"}, kod=400)                 # notun 'bitti' durumu yok


# ------------------------------------------------------------------ görev
def test_gorev_hizli_ekleme_bitirme_ve_yeniden_acma(ortam):
    st = ortam.st
    o = ortam.post("gorev/hizli", {"metin": "yarın faturayı öde!"})["oge"]
    assert o["veri"]["baslik"] == "faturayı öde" and o["veri"]["son_tarih"] == "2026-11-11" and o["veri"]["oncelik"] == "yuksek"
    assert st.get(o["kayit_id"])["text"] == "Görev: faturayı öde. Son tarih: 2026-11-11. Öncelik: yüksek." and st.get(o["kayit_id"])["kind"] == "task"
    eski = ortam.post("gorev/ekle", {"veri": {"baslik": "Raporu gönder", "son_tarih": "2026-11-09"}})["oge"]
    bugun = ortam.post("gorev/ekle", {"veri": {"baslik": "Ara", "son_tarih": "2026-11-10"}})["oge"]
    assert eski["turev"] == {"gecikti": True, "bugun": False, "bu_hafta": False}
    assert bugun["turev"] == {"gecikti": False, "bugun": True, "bu_hafta": True} and o["turev"]["bu_hafta"] is True

    b = ortam.post("gorev/guncelle", {"id": o["id"], "durum": "bitti"})["oge"]
    r = st.get(o["kayit_id"])
    assert b["durum"] == "bitti" and b["veri"]["bitti_tarih"] == "2026-11-10" and b["kayit_id"] is None
    assert not st.is_current(o["kayit_id"]) and r["archived"] == 0 and r["valid_to"]                         # geçersiz kılındı, arşiv değil
    a = ortam.post("gorev/guncelle", {"id": o["id"], "durum": "acik"})["oge"]
    assert a["durum"] == "acik" and "bitti_tarih" not in a["veri"] and st.is_current(a["kayit_id"]) and a["kayit_id"] != o["kayit_id"]
    assert "hata" in ortam.post("gorev/hizli", {"metin": "   "}, kod=400)


def test_gorev_hafizadaki_gorevleri_gosterir_bitirir_ve_devralir(ortam):
    st = ortam.st
    ajan = st.add_record(Actor("hermes", "genel"), {"text": "Kombi servisini ara.", "kind": "task", "visibility": "shared", "trust": "agent"})
    ozel = st.add_record(Actor("claude-code", "is-yeri"), {"text": "Vardiya listesini güncelle.", "kind": "task", "visibility": "project", "trust": "agent"})
    st.add_record(Actor("hermes", "genel"), {"text": "Kullanıcı çay sever.", "kind": "fact", "visibility": "shared", "trust": "agent"})
    kendi = ortam.post("gorev/ekle", {"veri": {"baslik": "Ekmek al"}})["oge"]
    h = ortam.get("gorev/hafiza")["kayitlar"]
    assert [(k["id"], k["arac"], k["proje"], k["ozel"]) for k in h] == [(ajan, "hermes", "genel", False), (ozel, "claude-code", "is-yeri", True)]
    assert kendi["kayit_id"] not in [k["id"] for k in h]                                                       # uygulamanın kendi görevi iki kez görünmez

    ortam.post("gorev/hafiza-bitir", {"kayit": ajan})
    assert not st.is_current(ajan) and [k["id"] for k in ortam.get("gorev/hafiza")["kayitlar"]] == [ozel]
    assert "hata" in ortam.post("gorev/hafiza-bitir", {"kayit": ajan}, kod=409)                               # artık güncel değil

    n = kayit_say(st)
    al = ortam.post("gorev/hafiza-al", {"kayit": ozel})["oge"]
    assert al["kayit_id"] == ozel and al["veri"]["baslik"] == "Vardiya listesini güncelle." and kayit_say(st) == n and st.is_current(ozel)
    assert ortam.get("gorev/hafiza")["kayitlar"] == []
    # devralınan özel kaydın yenisi de özel kalır: proje, görünürlük ve güven taşınır
    d = ortam.post("gorev/guncelle", {"id": al["id"], "veri": {"baslik": "Vardiya listesini güncelle", "son_tarih": "2026-11-14"}})["oge"]
    yeni = st.get(d["kayit_id"])
    assert st.get(ozel)["superseded_by"] == d["kayit_id"]
    assert (yeni["project"], yeni["visibility"], yeni["trust"], yeni["tool"]) == ("is-yeri", "project", "agent", "gorev")
    assert "hata" in ortam.post("gorev/hafiza-al", {"kayit": "R99999"}, kod=404)
    assert U.gunluk_ozet(st)["gorevler"]["acik"] == 1                              # projeye özel görev ajanlara verilen özete girmez


# ------------------------------------------------------------------ takvim ve ders
def test_takvim_araligi_tekrarlari_ve_gorev_tarihlerini_icerir(ortam):
    st = ortam.st
    ortam.post("gorev/ekle", {"veri": {"baslik": "Fatura", "son_tarih": "2026-11-12"}})
    ortam.post("gorev/ekle", {"veri": {"baslik": "Gizli iş", "son_tarih": "2026-11-12", "ozel": True}})
    v = ortam.post("takvim/ekle", {"veri": {"baslik": "Vardiya", "tarih": "2026-11-02", "saat": "08:00", "tur": "mesai", "tekrar": "haftalik"}})["oge"]
    s = ortam.post("takvim/ekle", {"veri": {"baslik": "Vize", "tarih": "2026-11-12", "saat": "09:30", "tur": "sinav"}})["oge"]
    assert st.get(v["kayit_id"])["text"] == "Mesai: Vardiya — 2026-11-02 08:00 (her hafta)." and v["turev"] == {"sonraki": "2026-11-16", "gecti": False}
    a = ortam.get("takvim/aralik?bas=2026-11-09&son=2026-11-16")["gunler"]
    assert sorted(a) == ["2026-11-09", "2026-11-12", "2026-11-16"]
    assert [(x["tur"], x["baslik"], x["saat"]) for x in a["2026-11-12"]] == [("gorev", "Fatura", ""), ("gorev", "Gizli iş", ""), ("sinav", "Vize", "09:30")]
    assert a["2026-11-09"][0]["oge_id"] == v["id"] and a["2026-11-12"][2]["oge_id"] == s["id"]
    assert ortam.c.get("/panel/uyg/takvim/aralik?bas=2026-11-01&son=2028-11-01").status_code == 400          # en çok 400 gün
    assert "hata" in ortam.post("takvim/ekle", {"veri": {"baslik": "x", "tarih": "2026-11-12", "ders_id": 999}}, kod=400)
    gecmis = ortam.post("takvim/ekle", {"veri": {"baslik": "Eski", "tarih": "2026-11-01"}})["oge"]
    assert gecmis["turev"] == {"sonraki": None, "gecti": True}


def test_ders_ilerleme_not_hesabi_ve_takvimdeki_sinavlar(ortam):
    st = ortam.st
    d = ortam.post("ders/ekle", {"veri": {"ad": "Muhasebe", "kurum": "Üniversite", "uniteler": [{"ad": "Ünite 1"}, {"ad": "Ünite 2"}],
                                         "ara": 40, "hedef": 50}})["oge"]
    assert d["turev"]["yuzde"] == 0 and d["turev"]["gereken_final"] == 54.3 and d["turev"]["sinavlar"] == []
    assert st.get(d["kayit_id"])["text"] == "Ders: Muhasebe (Üniversite). 0/2 ünite bitti. Ara sınav 40."
    ortam.post("takvim/ekle", {"veri": {"baslik": "Muhasebe finali", "tarih": "2026-12-01", "saat": "10:00", "tur": "sinav", "ders_id": d["id"]}})
    ortam.post("takvim/ekle", {"veri": {"baslik": "Muhasebe vizesi", "tarih": "2026-11-01", "tur": "sinav", "ders_id": d["id"]}})   # geçmiş
    veri = dict(d["veri"], uniteler=[{"ad": "Ünite 1", "durum": "bitti"}, {"ad": "Ünite 2"}])
    d2 = ortam.post("ders/guncelle", {"id": d["id"], "veri": veri})["oge"]
    assert d2["turev"]["yuzde"] == 50 and d2["kayit_id"] != d["kayit_id"]
    assert st.get(d2["kayit_id"])["text"] == "Ders: Muhasebe (Üniversite). 1/2 ünite bitti. Ara sınav 40."
    assert [(x["baslik"], x["tarih"], x["kalan_gun"]) for x in d2["turev"]["sinavlar"]] == [("Muhasebe finali", "2026-12-01", 21)]
    b = ortam.post("ders/guncelle", {"id": d["id"], "durum": "bitti"})["oge"]
    assert st.get(b["kayit_id"])["text"].endswith("Ders tamamlandı.")


# ------------------------------------------------------------------ alışkanlık ve oruç
def test_aliskanlik_isaretleri_seriyi_gunceller_hafizaya_dusmez(ortam):
    st = ortam.st
    a = ortam.post("aliskanlik/ekle", {"veri": {"ad": "Okuma"}})["oge"]
    assert st.get(a["kayit_id"])["text"] == "Alışkanlık: Okuma (her gün)." and a["turev"]["seri"] == 0 and a["turev"]["risk"] is False
    n = kayit_say(st)
    for gun in ("2026-11-08", "2026-11-09"):
        s = ortam.post("aliskanlik/gun", {"id": a["id"], "gun": gun, "veri": {"tamam": True}})["oge"]
    assert s["turev"]["seri"] == 2 and not s["turev"]["bugun_tamam"]
    s = ortam.post("aliskanlik/gun", {"id": a["id"], "gun": "2026-11-10", "veri": {"tamam": True}})["oge"]
    assert s["turev"]["seri"] == 3 and s["turev"]["bugun_tamam"] and kayit_say(st) == n                       # işaret hafızaya yazılmaz
    s = ortam.post("aliskanlik/gun", {"id": a["id"], "gun": "2026-11-09", "veri": {"tamam": False}})["oge"]
    assert s["turev"]["seri"] == 1
    assert "hata" in ortam.post("aliskanlik/gun", {"id": a["id"], "gun": "2026-11-11", "veri": {"tamam": True}}, kod=400)   # gelecek
    assert "hata" in ortam.post("aliskanlik/gun", {"id": a["id"], "gun": "dün", "veri": {"tamam": True}}, kod=400)
    assert "hata" in ortam.post("not/gun", {"id": a["id"], "gun": "2026-11-10", "veri": {"tamam": True}}, kod=404)          # notta güne bağlı veri yok
    b = ortam.post("aliskanlik/guncelle", {"id": a["id"], "durum": "bitti"})["oge"]
    assert b["kayit_id"] is None and not st.is_current(a["kayit_id"])


def test_aliskanlik_aksam_isaretsizse_risk(ortam, monkeypatch):
    a = ortam.post("aliskanlik/ekle", {"veri": {"ad": "Okuma"}})["oge"]
    ortam.post("aliskanlik/gun", {"id": a["id"], "gun": "2026-11-09", "veri": {"tamam": True}})
    monkeypatch.setattr(U, "_saat", lambda dilim: dt.datetime(2026, 11, 10, 21, 0))
    assert ortam.get("aliskanlik/ogeler")["ogeler"][0]["turev"]["risk"] is True                                # akşam oldu, seri kırılmak üzere


def test_oruc_tek_etkin_gunluk_uyari_ve_bitis(ortam):
    st = ortam.st
    o = ortam.post("oruc/ekle", {"veri": {"tur": "su", "baslangic": "2026-11-10T08:00", "hedef_saat": 672}})["oge"]
    assert st.get(o["kayit_id"])["text"] == "Oruç başladı: 2026-11-10 08:00, hedef 28 gün (su orucu)."
    assert o["turev"]["gecen_saat"] == 6.0 and o["turev"]["gun"] == 1 and o["turev"]["uzun"] is True and o["turev"]["bugun"] is None
    assert "süren bir oruç" in ortam.post("oruc/ekle", {"veri": {"tur": "su", "baslangic": "2026-11-10T09:00", "hedef_saat": 24}}, kod=409)["hata"]

    n = kayit_say(st)
    g = ortam.post("oruc/gun", {"id": o["id"], "gun": "2026-11-10", "veri": {"su_ml": 1500, "elektrolit": True, "kilo": 81.4, "his": 3,
                                                                           "belirtiler": ["bas_agrisi"]}})["oge"]
    assert g["turev"]["bugun"]["su_ml"] == 1500 and g["turev"]["uyari"]["duzey"] == "dikkat" and kayit_say(st) == n
    assert "81" not in "".join(e["payload"] for e in st.q("SELECT payload FROM events"))                       # sağlık verisi günlüğe girmez
    g = ortam.post("oruc/gun", {"id": o["id"], "gun": "2026-11-10", "veri": {"belirtiler": ["carpinti"]}})["oge"]
    assert g["turev"]["uyari"]["duzey"] == "tehlike" and "112" in g["turev"]["uyari"]["mesaj"]
    assert "hata" in ortam.post("oruc/gun", {"id": o["id"], "gun": "2026-11-09", "veri": {}}, kod=400)        # oruç başlamadan önce

    b = ortam.post("oruc/guncelle", {"id": o["id"], "durum": "bitti"})["oge"]
    assert b["veri"]["bitis"] == "2026-11-10T14:00" and b["veri"]["sonuc"] == "erken" and b["turev"]["kalan_saat"] == 0.0
    assert st.get(b["kayit_id"])["text"] == "Oruç: 2026-11-10 08:00 – 2026-11-10 14:00 (6 saat), erken bitirildi (su orucu)."
    assert st.get(o["kayit_id"])["superseded_by"] == b["kayit_id"]
    veri = ortam.get("oruc/ogeler")
    assert set(veri["tehlike"]) <= set(veri["belirtiler"]) and "tıbbi" in veri["uyari"] and veri["ogeler"][0]["turev"]["gunler"]["2026-11-10"]
    ortam.post("oruc/ekle", {"veri": {"tur": "aralikli", "baslangic": "2026-11-10T20:00", "hedef_saat": 16}})  # biten varken yenisi açılır


# ------------------------------------------------------------------ ayarlar
def test_ayarlar_sessiz_saat_ve_yansitma_anahtari(ortam):
    st = ortam.st
    v = ortam.get("ayarlar/veri")
    assert v["ayar"]["saat_dilimi"] == "Europe/Istanbul" and v["ayar"]["yansit"]["not"] is True and v["ayar"]["sessiz_acik"] is False
    assert set(v) >= {"ayar", "araclar", "cihazlar", "uygulamalar", "hafiza", "simdi"}
    o = ortam.post("not/ekle", {"veri": {"metin": "Deneme notu."}})["oge"]

    a = ortam.post("ayarlar/kaydet", {"saat_dilimi": "Europe/Istanbul", "sessiz_acik": True, "sessiz_bas": "23:00", "sessiz_son": "08:00"})["ayar"]
    sessiz = [r for r in st.list_records() if r["tool"] == "ayarlar"]
    assert a["sessiz_acik"] and len(sessiz) == 1 and sessiz[0]["kind"] == "preference" and "23:00–08:00" in sessiz[0]["text"]
    ortam.post("ayarlar/kaydet", {"sessiz_acik": True, "sessiz_bas": "22:00", "sessiz_son": "08:00"})
    guncel = [r for r in st.list_records() if r["tool"] == "ayarlar" and st.is_current(r["id"])]
    assert len(guncel) == 1 and "22:00" in guncel[0]["text"] and st.get(sessiz[0]["id"])["superseded_by"] == guncel[0]["id"]
    ortam.post("ayarlar/kaydet", {"sessiz_acik": False})
    assert not [r for r in st.list_records() if r["tool"] == "ayarlar" and st.is_current(r["id"])]

    ortam.post("ayarlar/kaydet", {"yansit": {"not": False}})                                                  # kapatınca var olan yansımalar kalkar
    assert st.get(o["kayit_id"])["archived"] == 1 and st.uyg_al(o["id"])["kayit_id"] is None
    assert ortam.post("not/ekle", {"veri": {"metin": "Kapalıyken yazılan."}})["oge"]["kayit_id"] is None
    ortam.post("ayarlar/kaydet", {"yansit": {"not": True}})                                                   # açınca yeniden yazılır
    assert all(x["kayit_id"] and st.is_current(x["kayit_id"]) for x in ortam.get("not/ogeler")["ogeler"])
    assert "hata" in ortam.post("ayarlar/kaydet", {"saat_dilimi": "Mars/Olympus"}, kod=400)
    assert st.verify_chain()


# ------------------------------------------------------------------ ajanlar için günlük özet
def test_gunluk_ozet_bugunu_toplar_ozel_olani_gostermez(ortam):
    st = ortam.st
    ortam.post("gorev/ekle", {"veri": {"baslik": "Raporu gönder", "son_tarih": "2026-11-09"}})
    ortam.post("gorev/ekle", {"veri": {"baslik": "Faturayı öde", "son_tarih": "2026-11-10"}})
    ortam.post("gorev/ekle", {"veri": {"baslik": "Gizli iş", "son_tarih": "2026-11-10", "ozel": True}})
    ortam.post("gorev/ekle", {"veri": {"baslik": "Sonraki iş", "son_tarih": "2026-12-01"}})
    ortam.post("takvim/ekle", {"veri": {"baslik": "Vardiya", "tarih": "2026-11-03", "saat": "08:00", "tur": "mesai", "tekrar": "haftalik"}})
    ortam.post("takvim/ekle", {"veri": {"baslik": "Vize", "tarih": "2026-11-11", "saat": "09:30", "tur": "sinav"}})
    ok = ortam.post("aliskanlik/ekle", {"veri": {"ad": "Okuma"}})["oge"]
    ortam.post("aliskanlik/ekle", {"veri": {"ad": "Yürüyüş"}})
    ortam.post("aliskanlik/gun", {"id": ok["id"], "gun": "2026-11-10", "veri": {"tamam": True}})
    o = ortam.post("oruc/ekle", {"veri": {"tur": "su", "baslangic": "2026-11-09T08:00", "hedef_saat": 672}})["oge"]
    ortam.post("oruc/gun", {"id": o["id"], "gun": "2026-11-10", "veri": {"kilo": 81.4, "belirtiler": ["bas_agrisi"]}})
    ortam.post("ayarlar/kaydet", {"sessiz_acik": True, "sessiz_bas": "13:00", "sessiz_son": "15:00"})

    d = U.gunluk_ozet(st)
    assert d["bugun"] == "2026-11-10" and d["saat"] == "14:00" and d["sessiz"] is True
    assert [g["baslik"] for g in d["gorevler"]["geciken"]] == ["Raporu gönder"] and [g["baslik"] for g in d["gorevler"]["bugun"]] == ["Faturayı öde"]
    assert d["gorevler"]["acik"] == 3                                                                         # özel görev sayıya da girmez
    assert [(e["baslik"], e["saat"]) for e in d["etkinlikler"]["bugun"]] == [("Vardiya", "08:00")]
    assert [e["baslik"] for e in d["etkinlikler"]["yarin"]] == ["Vize"]
    assert d["aliskanliklar"] == {"tamam": ["Okuma"], "bekleyen": ["Yürüyüş"], "risk": []}
    assert d["oruc"] == {"tur": "su orucu", "gun": 2, "gecen": "1 gün 6 saat", "hedef": "28 gün", "bugun_girildi": True}
    metin = U.ozet_metni(d)
    assert "2026-11-10" in metin and "Raporu gönder" in metin and "Vize" in metin and "Yürüyüş" in metin and "2. gün" in metin
    assert "Gizli" not in metin and "81" not in metin and "bas_agrisi" not in metin and "Baş ağrısı" not in metin   # sağlık verisi ve özel öğe yok

    ortam.post("ayarlar/kaydet", {"sessiz_acik": False, "yansit": {"gorev": False, "oruc": False}})          # yansıtması kapalı uygulama özetten de çıkar
    d2 = U.gunluk_ozet(st)
    assert d2["gorevler"] is None and d2["oruc"] is None and d2["sessiz"] is False and "Faturayı" not in U.ozet_metni(d2)
    assert "bir şey yok" in U.ozet_metni(U.gunluk_ozet(Store(st.path.parent / "bos.sqlite", anahtar="")))


def test_baskasinin_degistirdigi_yansima_izlenir_iki_guncel_kayit_olusmaz(ortam):
    """Yansıma kaydı Gezgin'de (ya da bir ajan tarafından) yenisiyle değiştirildiyse uygulama zincirin ucundaki güncel
    kaydı izler: bir sonraki yazımda onun yerine geçer, aynı görev için iki güncel kayıt kalmaz."""
    st = ortam.st
    o = ortam.post("gorev/ekle", {"veri": {"baslik": "Raporu gönder"}})["oge"]
    r2 = st.replace_records(Actor("gezgin", "genel"), [o["kayit_id"]], {"text": "Görev: Raporu müdüre gönder.", "kind": "task", "visibility": "shared",
                                                                    "trust": "user", "valid_from": "2026-11-10"}, "Gezgin: düzeltme", "duzelt")
    d = ortam.post("gorev/guncelle", {"id": o["id"], "veri": {"baslik": "Raporu gönder", "son_tarih": "2026-11-12"}})["oge"]
    assert st.get(r2)["superseded_by"] == d["kayit_id"]
    assert [r["id"] for r in st.list_records() if r["kind"] == "task" and st.is_current(r["id"])] == [d["kayit_id"]]
    # bitirince de zincirin ucu geçersiz kılınır
    r3 = st.replace_records(Actor("gezgin", "genel"), [d["kayit_id"]], {"text": "Görev: Raporu müdüre gönder (acele).", "kind": "task",
                                                                   "visibility": "shared", "trust": "user", "valid_from": "2026-11-10"}, "Gezgin: düzeltme", "duzelt")
    ortam.post("gorev/guncelle", {"id": o["id"], "durum": "bitti"})
    assert not st.is_current(r3) and not [r for r in st.list_records() if r["kind"] == "task" and st.is_current(r["id"])]


def test_gun_verilmezse_sunucunun_bugunu_kullanilir(ortam, monkeypatch):
    """Sayfa gece yarısından önce açılıp ertesi gün kullanılırsa tarayıcının bildiği 'bugün' eskidir; bugüne yazan
    düğmeler günü göndermez, sunucu kendi bugününe yazar (dünün girişi ezilmez)."""
    a = ortam.post("aliskanlik/ekle", {"veri": {"ad": "Okuma"}})["oge"]
    o = ortam.post("oruc/ekle", {"veri": {"tur": "su", "baslangic": "2026-11-10T08:00", "hedef_saat": 72}})["oge"]
    ortam.post("oruc/gun", {"id": o["id"], "veri": {"su_ml": 1000}})
    monkeypatch.setattr(U, "_saat", lambda dilim: dt.datetime(2026, 11, 11, 0, 30))
    s = ortam.post("aliskanlik/gun", {"id": a["id"], "veri": {"tamam": True}})["oge"]
    assert s["turev"]["bugun_tamam"] and list(ortam.st.gunler(a["id"])) == ["2026-11-11"]
    g = ortam.post("oruc/gun", {"id": o["id"], "veri": {"su_ml": 250}})["oge"]
    assert g["turev"]["gunler"] == {"2026-11-10": {"su_ml": 1000, "elektrolit": False, "kilo": None, "his": None, "belirtiler": [], "not": ""},
                                    "2026-11-11": {"su_ml": 250, "elektrolit": False, "kilo": None, "his": None, "belirtiler": [], "not": ""}}


def test_takvim_ders_listesi_biten_dersleri_de_icerir(ortam):
    """Biten derse bağlı bir sınav düzenlenirken ders seçilebilir kalmalı; yoksa kayıtta ders bağı silinir."""
    d = ortam.post("ders/ekle", {"veri": {"ad": "Muhasebe"}})["oge"]
    ortam.post("takvim/ekle", {"veri": {"baslik": "Final", "tarih": "2026-12-01", "tur": "sinav", "ders_id": d["id"]}})
    ortam.post("ders/guncelle", {"id": d["id"], "durum": "bitti"})
    assert ortam.get("takvim/ogeler")["dersler"] == [{"id": d["id"], "ad": "Muhasebe"}]


# ------------------------------------------------------------------ bağımsız incelemenin bulguları (2026-11-10)
def test_devralinan_ozel_gorev_bag_kopunca_da_ozel_kalir(ortam):
    """Hafızadan devralınan projeye özel, dış kaynaklı bir görevin kökeni öğede saklanır: bitir/geri al, özel yap/kaldır ve
    yansıtmayı kapat/aç sonrasında yazılan yeni kayıt aynı projede, projeye özel ve aynı güvenle yazılır; özete girmez."""
    st = ortam.st
    for adim in ("bitir-geri-al", "ozel-yap-kaldir", "yansitma-kapat-ac"):
        kaynak = st.add_record(Actor("hermes", "is-yeri"), {"text": f"Gizli iş ({adim}).", "kind": "task", "visibility": "project", "trust": "external"})
        o = ortam.post("gorev/hafiza-al", {"kayit": kaynak})["oge"]
        if adim == "bitir-geri-al":
            ortam.post("gorev/guncelle", {"id": o["id"], "durum": "bitti"})
            o = ortam.post("gorev/guncelle", {"id": o["id"], "durum": "acik"})["oge"]
        elif adim == "ozel-yap-kaldir":
            ortam.post("gorev/guncelle", {"id": o["id"], "veri": dict(o["veri"], ozel=True)})
            o = ortam.post("gorev/guncelle", {"id": o["id"], "veri": dict(o["veri"], ozel=False, son_tarih="2026-11-10")})["oge"]
        else:
            ortam.post("ayarlar/kaydet", {"yansit": {"gorev": False}})
            ortam.post("ayarlar/kaydet", {"yansit": {"gorev": True}})
            o = next(x for x in ortam.get("gorev/ogeler")["ogeler"] if x["id"] == o["id"])
        yeni = st.get(o["kayit_id"])
        assert yeni["id"] != kaynak and (yeni["project"], yeni["visibility"], yeni["trust"]) == ("is-yeri", "project", "external"), adim
        assert not [r for r in st.visible_records("baska-proje") if "Gizli iş" in r["text"]], adim
        ozet = U.gunluk_ozet(st)
        assert ozet["gorevler"]["acik"] == 0 and "Gizli" not in U.ozet_metni(ozet), adim


def test_bozuk_istek_500_vermez_ve_uygulamayi_kilitlemez(ortam):
    c = ortam.c
    ortam.post("oruc/ekle", {"veri": {"tur": "su", "baslangic": "2026-11-10T08:00", "hedef_saat": None, "ozel": True}}, kod=400)
    ortam.post("oruc/ekle", {"veri": {"tur": "su", "baslangic": "9999-12-31T23:59", "hedef_saat": 24}}, kod=400)
    assert ortam.get("oruc/ogeler")["ogeler"] == []                                              # yarım kayıt kalmadı, liste açılıyor
    ortam.post("takvim/ekle", {"veri": {"baslik": "a", "tarih": "2026-11-21", "tur": []}}, kod=400)
    ortam.post("gorev/guncelle", {"id": 10 ** 30, "durum": "bitti"}, kod=404)
    ortam.post("gorev/hafiza-al", {"kayit": "\ud800"}, kod=404)
    assert c.get("/panel/uyg/takvim/aralik?bas=9999-12-01&son=9999-12-31").status_code == 400
    a = ortam.post("aliskanlik/ekle", {"veri": {"ad": "Okuma"}})["oge"]
    assert "hata" in ortam.post("aliskanlik/gun", {"id": a["id"], "gun": "0001-01-01", "veri": {"tamam": True}}, kod=400)   # en çok bir yıl geriye


def test_biten_oruc_duzeltilince_sonuc_yeniden_belirlenir(ortam):
    st = ortam.st
    o = ortam.post("oruc/ekle", {"veri": {"tur": "su", "baslangic": "2026-11-09T08:00", "hedef_saat": 72}})["oge"]
    b = ortam.post("oruc/guncelle", {"id": o["id"], "durum": "bitti"})["oge"]
    assert b["veri"]["sonuc"] == "erken"                                                         # 30 saat < 72
    d = ortam.post("oruc/guncelle", {"id": o["id"], "veri": dict(b["veri"], hedef_saat=16)})["oge"]   # form eski 'erken'i geri gönderir
    assert d["veri"]["sonuc"] == "tamamlandi" and "tamamlandı" in st.get(d["kayit_id"])["text"]


def test_kapanis_tarihi_kullanicinin_gunudur(ortam, monkeypatch):
    """Geçersiz kılınan kaydın bitiş tarihi sunucu saatinden değil, kullanıcının saat dilimindeki günden gelir."""
    st = ortam.st
    monkeypatch.setattr(U, "_saat", lambda dilim: dt.datetime(2026, 11, 14, 0, 30))
    o = ortam.post("gorev/ekle", {"veri": {"baslik": "Ara"}})["oge"]
    ortam.post("gorev/guncelle", {"id": o["id"], "durum": "bitti"})
    assert (st.get(o["kayit_id"])["valid_from"], st.get(o["kayit_id"])["valid_to"]) == ("2026-11-14", "2026-11-14")
    ajan = st.add_record(Actor("hermes", "genel"), {"text": "Servisi ara.", "kind": "task", "visibility": "shared", "trust": "agent"})
    ortam.post("gorev/hafiza-bitir", {"kayit": ajan})
    assert st.get(ajan)["valid_to"] == "2026-11-14"
