"""Gezgin: süzgeçli liste, düzelt, birleştir, arşiv, öneriler; oturum ve CSRF korumaları; hiçbir kaydın silinmemesi."""
import json

import numpy as np
import pytest
from fastmcp import FastMCP
from starlette.testclient import TestClient

from council_hafiza import gezgin, panel, search
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


def kayit(st, metin, tool="claude-code", project="genel", **k):
    rec = {"text": metin, "context": k.get("context", ""), "keys": k.get("keys", []), "kind": k.get("kind", "fact"),
           "visibility": k.get("visibility", "shared"), "trust": k.get("trust", "user"), "valid_from": k.get("valid_from", "2026-11-01")}
    return st.add_record(Actor(tool, project), rec)


@pytest.fixture
def ortam(tmp_path, monkeypatch):
    st = Store(tmp_path / "g.sqlite", anahtar="")
    (tmp_path / "denetim").mkdir()
    monkeypatch.setenv("COUNCIL_DENETIM_DIR", str(tmp_path / "denetim"))
    m = FastMCP("t")
    panel.kaydet(m, SahteAuth(hash_password(PAROLA)), st)
    c = TestClient(m.http_app(), base_url="https://test")
    return st, c, tmp_path / "denetim"


def giris(c):
    r = c.post("/panel/giris", data={"parola": PAROLA}, follow_redirects=False)
    assert r.status_code == 303
    return c.get("/panel/gezgin/oturum").json()["csrf"]


def post(c, yol, govde, csrf, **h):
    return c.post(f"/panel/gezgin/{yol}", content=json.dumps(govde), headers={"Content-Type": "application/json", "X-CSRF": csrf, **h})


# ------------------------------------------------------------------ depo
def test_replace_records_yazdiktan_sonra_geri_alinir(tmp_path, monkeypatch):
    """add_record yazıldıktan SONRA ikinci geçersiz kılma başarısız olursa yeni kayıt, olaylar ve ilk geçersiz kılma geri alınır."""
    st = Store(tmp_path / "s.sqlite", anahtar="")
    a, b = kayit(st, "Bir"), kayit(st, "İki")
    olay = st.q("SELECT COUNT(*) AS n FROM events")[0]["n"]
    gercek, sayac = st.supersede, {"n": 0}

    def bozuk(*args, **kw):
        sayac["n"] += 1
        return gercek(*args, **kw) if sayac["n"] == 1 else False
    monkeypatch.setattr(st, "supersede", bozuk)
    with pytest.raises(ValueError):
        st.replace_records(Actor("gezgin", "genel"), [a, b], {"text": "Birleşik", "kind": "fact", "visibility": "shared", "trust": "user"},
                           "r", "birlestir")
    assert st.q("SELECT COUNT(*) AS n FROM records")[0]["n"] == 2
    assert st.q("SELECT COUNT(*) AS n FROM events")[0]["n"] == olay
    assert st.is_current(a) and st.is_current(b) and st.verify_chain() and st._derinlik == 0


def test_replace_records_esz_zamanli_tek_kazanan(tmp_path):
    import threading
    st = Store(tmp_path / "s.sqlite", anahtar="")
    a = kayit(st, "Bir")
    sonuc = []

    def is_(i):
        try:
            sonuc.append(st.replace_records(Actor("gezgin", "genel"), [a], {"text": f"Düzeltme {i}", "kind": "fact",
                                                                           "visibility": "shared", "trust": "user"}, "r", "duzelt"))
        except ValueError:
            sonuc.append(None)
    ts = [threading.Thread(target=is_, args=(i,)) for i in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len([x for x in sonuc if x]) == 1 and st.verify_chain()


def test_replace_records_hep_ya_hic(tmp_path):
    st = Store(tmp_path / "s.sqlite", anahtar="")
    a, b = kayit(st, "Bir"), kayit(st, "İki")
    st.archive(Actor("x", "genel"), b, "test")
    with pytest.raises(ValueError):
        st.replace_records(Actor("gezgin", "genel"), [a, b], {"text": "Birleşik", "kind": "fact", "visibility": "shared", "trust": "user"},
                           "r", "birlestir")
    assert st.q("SELECT COUNT(*) AS n FROM records")[0]["n"] == 2          # yeni kayıt geri alındı
    assert st.is_current(a) and st.verify_chain()


def test_arsivden_cikar_ve_gecmis(tmp_path):
    st = Store(tmp_path / "s.sqlite", anahtar="")
    a = kayit(st, "Bir")
    act = Actor("gezgin", "genel")
    assert st.archive(act, a, "yanlış") and not st.archive(act, a, "yine")
    assert st.unarchive(act, a, "geri") and not st.unarchive(act, a, "yine")
    assert st.is_current(a)
    assert [e["action"] for e in st.record_history(a)] == ["kaydet", "arsivle", "arsivden_cikar"]


def test_kural_denetle():
    ortak = {"visibility": "shared", "trust": "user", "project": "genel"}
    ozel_a = {"visibility": "project", "trust": "user", "project": "a"}
    ozel_b = {"visibility": "project", "trust": "user", "project": "b"}
    assert gezgin.kural_denetle([ozel_a, ozel_b], {"visibility": "project", "trust": "user"})
    assert gezgin.kural_denetle([ortak, ozel_a], {"visibility": "shared", "trust": "user"})
    assert gezgin.kural_denetle([ortak], {"visibility": "project", "trust": "user"})
    assert gezgin.kural_denetle([ortak], {"visibility": "shared", "trust": "external"})
    assert gezgin.kural_denetle([ortak, dict(ortak)], {"visibility": "shared", "trust": "agent"}) is None
    assert gezgin.kural_denetle([ozel_a, dict(ozel_a)], {"visibility": "project", "trust": "user"}) is None


# ------------------------------------------------------------------ http
def test_giris_ve_csrf(ortam):
    st, c, _ = ortam
    a = kayit(st, "Ali yüzmeyi seviyor")
    assert c.get("/panel/gezgin/kayitlar").status_code == 401
    assert c.get("/panel/gezgin", follow_redirects=False).status_code == 303
    csrf = giris(c)
    r = c.get("/panel/gezgin")
    assert r.status_code == 200 and "gezgin.js" in r.text and "script-src 'self'" in r.headers["content-security-policy"]
    assert c.get("/panel/gezgin/gezgin.js").status_code == 200 and c.get("/panel/gezgin/gezgin.css").status_code == 200
    assert post(c, "arsivle", {"id": a, "neden": "deneme"}, "yanlis").status_code == 403
    assert post(c, "arsivle", {"id": a, "neden": "deneme"}, csrf, Origin="https://kotu.example").status_code == 403
    assert post(c, "arsivle", {"id": a, "neden": "deneme"}, csrf, **{"Sec-Fetch-Site": "cross-site"}).status_code == 403
    r = c.post("/panel/gezgin/arsivle", data={"id": a, "neden": "deneme"}, headers={"X-CSRF": csrf})   # form gövdesi kabul edilmez
    assert r.status_code == 400
    assert st.is_current(a)
    assert post(c, "arsivle", {"id": a, "neden": "deneme"}, csrf, Origin="https://test").status_code == 200
    assert not st.is_current(a)
    c.post("/panel/cikis")
    assert post(c, "arsivden-cikar", {"id": a}, csrf).status_code == 401


def test_liste_suzgec_arama(ortam):
    st, c, _ = ortam
    kayit(st, "Yüzme antrenmanı salı günü", tool="hermes", kind="plan", valid_from="2026-11-05")
    b = kayit(st, "Fizik sınavı ocakta", tool="claude-code", project="okul", kind="event", valid_from="2026-10-01")
    kayit(st, "Gizli iş notu", project="is", visibility="project")
    giris(c)
    v = c.get("/panel/gezgin/kayitlar").json()
    assert v["toplam"] == 3 and v["hepsi"] == 3 and "embedding" not in v["kayitlar"][0]
    assert v["secenekler"]["arac"] == {"claude-code": 2, "hermes": 1}
    assert c.get("/panel/gezgin/kayitlar?arac=hermes").json()["toplam"] == 1
    assert c.get("/panel/gezgin/kayitlar?proje=okul,is").json()["toplam"] == 2
    assert c.get("/panel/gezgin/kayitlar?bas=2026-11-01").json()["toplam"] == 2
    assert c.get("/panel/gezgin/kayitlar?tur=event").json()["kayitlar"][0]["id"] == b
    assert c.get(f"/panel/gezgin/kayitlar?q={b}").json()["kayitlar"][0]["id"] == b
    assert c.get("/panel/gezgin/kayitlar?q=sınav").json()["kayitlar"][0]["id"] == b
    st.archive(Actor("x", "okul"), b, "t")
    assert c.get("/panel/gezgin/kayitlar").json()["toplam"] == 2
    assert c.get("/panel/gezgin/kayitlar?durum=arsiv").json()["kayitlar"][0]["id"] == b
    assert c.get("/panel/gezgin/kayitlar?durum=hepsi").json()["toplam"] == 3


def test_duzelt(ortam):
    st, c, _ = ortam
    a = kayit(st, "Sınav 21 Kasım'da", project="okul", tool="hermes")
    csrf = giris(c)
    temel = {"id": a, "metin": "Sınav 22 Kasım 2026'da", "baglam": "AÖF", "anahtarlar": ["sınav", "exam"], "tur": "event",
             "gorunurluk": "shared", "guven": "user", "tarih": "2026-11-09", "neden": "tarih yanlıştı"}
    assert post(c, "duzelt", {**temel, "metin": "IBAN TR330006100519786457841326"}, csrf).status_code == 400   # gizli bilgi
    assert post(c, "duzelt", {**temel, "gorunurluk": "project"}, csrf).status_code == 400                     # ortak → özel yasak
    assert post(c, "duzelt", {**temel, "tur": "uydurma"}, csrf).status_code == 400
    r = post(c, "duzelt", temel, csrf)
    assert r.status_code == 200, r.text
    yeni = r.json()["yeni"]
    n, o = st.get(yeni), st.get(a)
    assert n["text"] == "Sınav 22 Kasım 2026'da" and n["tool"] == "gezgin" and n["project"] == "okul"
    assert o["superseded_by"] == yeni and st.q("SELECT COUNT(*) AS n FROM records")[0]["n"] == 2   # eskisi silinmedi
    assert post(c, "duzelt", temel, csrf).status_code == 409                    # eski kayıt artık düzeltilemez
    d = c.get(f"/panel/gezgin/kayit/{yeni}").json()
    assert d["oncul"][0]["id"] == a and [g["islem"] for g in d["gecmis"]] == ["kaydet", "duzelt"]
    assert c.get(f"/panel/gezgin/kayit/{a}").json()["ardil"][0]["id"] == yeni
    assert st.verify_chain()


def test_birlestir(ortam):
    st, c, _ = ortam
    a, b = kayit(st, "Ali pazartesi yüzer", project="genel"), kayit(st, "Ali pazartesi yüzmeye gider", project="spor")
    oa, ob = kayit(st, "özel a", project="a", visibility="project"), kayit(st, "özel b", project="b", visibility="project")
    csrf = giris(c)
    govde = {"metin": "Ali her pazartesi yüzer.", "tur": "fact", "gorunurluk": "shared", "guven": "user", "tarih": "2026-11-09"}
    assert post(c, "birlestir", {**govde, "ids": [a]}, csrf).status_code == 400
    assert post(c, "birlestir", {**govde, "ids": [oa, ob], "gorunurluk": "project"}, csrf).status_code == 400
    assert post(c, "birlestir", {**govde, "ids": [a, oa]}, csrf).status_code == 400
    r = post(c, "birlestir", {**govde, "ids": [a, b, a]}, csrf)
    assert r.status_code == 200, r.text
    yeni = r.json()["yeni"]
    assert st.get(a)["superseded_by"] == yeni == st.get(b)["superseded_by"]
    assert st.get(yeni)["project"] == "genel"                              # farklı projeler → genel
    assert st.record_history(yeni)[-1]["payload"]["kaynaklar"] == [a, b]
    assert post(c, "birlestir", {**govde, "ids": [a, b]}, csrf).status_code == 409
    assert st.verify_chain()


def test_oneriler_ve_gecersiz_kil(ortam):
    st, c, dd = ortam
    a, b = kayit(st, "Oruç 30 gün"), kayit(st, "Oruç 28 gün")
    g = kayit(st, "Hermes kurulumu bitecek", kind="task")
    rapor = {"zaman": "2026-11-09T08:00:00+00:00", "bulgular": [
        {"id": f"model-celiski-{b}", "baslik": f"Çelişen kayıtlar: {b} ↔ {a}", "ayrinti": "Gün sayısı farklı."},
        {"id": f"gorev-{g}", "baslik": f"20 gündür açık görev: {g}", "ayrinti": ""},
        {"id": "disk", "baslik": "Disk dolu"}]}
    (dd / "son.json").write_text(json.dumps(rapor), encoding="utf-8")
    csrf = giris(c)
    o = c.get("/panel/gezgin/oneriler").json()["oneriler"]
    assert [x["tur"] for x in o] == ["celiski", "gorev"] and {k["id"] for k in o[0]["kayitlar"]} == {a, b} and o[0]["acik"]
    assert post(c, "gecersiz-kil", {"eski": a, "yeni": a}, csrf).status_code == 404
    assert post(c, "gecersiz-kil", {"eski": a, "yeni": b}, csrf).status_code == 200
    assert st.get(a)["superseded_by"] == b
    assert not c.get("/panel/gezgin/oneriler").json()["oneriler"][0]["acik"]


def test_guven_yukseltme_ve_neden_denetimi(ortam):
    st, c, _ = ortam
    d = kayit(st, "Bir web sayfasına göre kurs 3 hafta sürüyor", trust="external")
    csrf = giris(c)
    govde = {"id": d, "metin": "Bir web sayfasına göre kurs 4 hafta sürüyor", "tur": "fact", "gorunurluk": "shared", "tarih": "2026-11-09"}
    r = post(c, "duzelt", {**govde, "guven": "user"}, csrf)
    assert r.status_code == 400 and "Güven" in r.json()["hata"]              # sessiz yükseltme yok
    assert post(c, "duzelt", {**govde, "guven": "external", "neden": "IBAN TR330006100519786457841326"}, csrf).status_code == 400
    assert post(c, "arsivle", {"id": d, "neden": "parola: Gizli12345!"}, csrf).status_code == 400
    assert post(c, "duzelt", {**govde, "guven": "user", "guven_onay": True}, csrf).status_code == 200   # bilerek onaylanırsa olur
    assert st.verify_chain()


def test_gecersiz_kil_projeler_arasi_yasak(ortam):
    st, c, _ = ortam
    o = kayit(st, "Okul notu", project="okul", visibility="project")
    i = kayit(st, "İş notu", project="is", visibility="project")
    g = kayit(st, "Ortak not")
    csrf = giris(c)
    r = post(c, "gecersiz-kil", {"eski": o, "yeni": i}, csrf)
    assert r.status_code == 400 and st.is_current(o)
    assert post(c, "gecersiz-kil", {"eski": o, "yeni": g}, csrf).status_code == 200   # ortak kayıt her yerde görünür


def test_bozuk_govde_500_vermez(ortam):
    st, c, _ = ortam
    a = kayit(st, "Bir")
    csrf = giris(c)
    for govde in ({"id": a, "metin": "abc", "tur": "fact", "gorunurluk": "shared", "anahtarlar": 5},
                  {"id": a, "metin": ["x"], "tur": "fact", "gorunurluk": "shared"},
                  {"id": a, "metin": "abcd", "tur": "fact", "gorunurluk": "shared", "neden": {"a": 1}}):
        assert post(c, "duzelt", govde, csrf).status_code == 400
    assert post(c, "birlestir", {"ids": "R00001", "metin": "abc", "tur": "fact", "gorunurluk": "shared"}, csrf).status_code == 400
    assert c.post("/panel/gezgin/duzelt", content="[1]", headers={"Content-Type": "application/json", "X-CSRF": csrf}).status_code == 400


def test_sayfa_son_sayfaya_sikisir_ve_tarih(ortam):
    st, c, _ = ortam
    for i in range(3):
        kayit(st, f"Kayıt {i}")
    giris(c)
    v = c.get("/panel/gezgin/kayitlar?sayfa=9").json()
    assert v["sayfa"] == 0 and len(v["kayitlar"]) == 3
    st.add_record(Actor("x", "genel"), {"text": "Tarihsiz", "kind": "fact", "visibility": "shared", "trust": "user"})
    assert all(k["tarih"] for k in c.get("/panel/gezgin/kayitlar").json()["kayitlar"])


# ------------------------------------------------------------------ belgedeki kurallar (tasarim/GEZGIN.md §4–§6)
IBAN = "TR330006100519786457841326"          # örnek IBAN; gerçek bir hesaba ait değil
ALANLAR = {"id", "metin", "baglam", "anahtarlar", "tur", "gorunurluk", "guven", "tarih", "bitis", "yerine", "arsiv_neden",
           "arac", "proje", "olusturma", "durum"}


def test_ozel_ortak_birlestirilemez(ortam):
    """Aynı projeden olsalar bile projeye özel ve ortak kayıt birleşmez (özel bilgi öbür projelere taşınırdı)."""
    st, c, _ = ortam
    ozel, ortak = kayit(st, "Projeye özel not", project="a", visibility="project"), kayit(st, "Ortak not", project="a")
    hata = gezgin.kural_denetle([st.get(ozel), st.get(ortak)], {"visibility": "shared", "trust": "user"})
    assert hata and "Projeye özel ve ortak" in hata
    csrf = giris(c)
    r = post(c, "birlestir", {"ids": [ozel, ortak], "metin": "Birleşik not", "tur": "fact", "gorunurluk": "shared", "guven": "user",
                              "tarih": "2026-11-09"}, csrf)
    assert r.status_code == 400 and "Projeye özel ve ortak" in r.json()["hata"]
    assert st.is_current(ozel) and st.is_current(ortak)


def test_json_olmayan_govde_reddedilir(ortam):
    st, c, _ = ortam
    a = kayit(st, "Bir")
    csrf = giris(c)
    r = c.post("/panel/gezgin/arsivle", content=json.dumps({"id": a, "neden": "deneme"}), headers={"Content-Type": "text/plain", "X-CSRF": csrf})
    assert r.status_code == 400 and st.is_current(a)


def test_okuma_uclari_giris_ister(ortam):
    st, c, _ = ortam
    a = kayit(st, "Bir")
    yollar = ("oturum", "kayitlar", f"kayit/{a}", "oneriler")
    for yol in yollar:
        assert c.get(f"/panel/gezgin/{yol}").status_code == 401, yol
    giris(c)
    for yol in yollar:
        assert c.get(f"/panel/gezgin/{yol}").status_code == 200, yol


def test_gunluk_arac_ve_neden(ortam):
    """Her yazma günlüğe 'gezgin' adına, nedeniyle düşer; özgün aracın adına değil."""
    st, c, _ = ortam
    a, b = kayit(st, "Arşivlenecek", tool="hermes"), kayit(st, "Düzeltilecek", tool="hermes")
    csrf = giris(c)
    assert post(c, "arsivle", {"id": a, "neden": "artık gereksiz"}, csrf).status_code == 200
    son = st.record_history(a)[-1]
    assert (son["action"], son["tool"]) == ("arsivle", "gezgin") and "artık gereksiz" in son["payload"]["neden"]
    r = post(c, "duzelt", {"id": b, "metin": "Düzeltildi", "tur": "fact", "gorunurluk": "shared", "guven": "user", "tarih": "2026-11-09",
                           "neden": "yazım hatası"}, csrf)
    assert r.status_code == 200, r.text
    eski, yeni = st.record_history(b)[-1], st.record_history(r.json()["yeni"])[-1]
    assert (eski["action"], eski["tool"]) == ("gecersiz_kil", "gezgin") and "yazım hatası" in eski["payload"]["neden"]
    assert (yeni["action"], yeni["tool"]) == ("duzelt", "gezgin") and "yazım hatası" in yeni["payload"]["neden"]


def test_duzelt_butun_alanlari_tasir(ortam):
    st, c, _ = ortam
    a = kayit(st, "Eski metin", project="okul", visibility="project", trust="agent", valid_from="2026-01-01")
    csrf = giris(c)
    r = post(c, "duzelt", {"id": a, "metin": "Yeni metin", "baglam": "AÖF sınav takvimi", "anahtarlar": ["sınav", "exam"], "tur": "event",
                           "gorunurluk": "project", "guven": "agent", "tarih": "2026-03-15", "neden": "güncellendi"}, csrf)
    assert r.status_code == 200, r.text
    n = st.get(r.json()["yeni"])
    assert (n["text"], n["context"], json.loads(n["keys"]), n["kind"], n["visibility"], n["trust"], n["valid_from"]) == \
        ("Yeni metin", "AÖF sınav takvimi", ["sınav", "exam"], "event", "project", "agent", "2026-03-15")


def test_arsivden_cikar_http(ortam):
    st, c, _ = ortam
    a = kayit(st, "Bir")
    csrf = giris(c)
    assert post(c, "arsivle", {"id": a, "neden": "deneme"}, csrf).status_code == 200 and not st.is_current(a)
    assert post(c, "arsivden-cikar", {"id": a}, csrf).status_code == 200 and st.is_current(a)
    assert post(c, "arsivden-cikar", {"id": a}, csrf).status_code == 409
    assert post(c, "arsivden-cikar", {"id": "R09999"}, csrf).status_code == 404


def test_siralama_tarih_araligi_durum(ortam):
    st, c, _ = ortam
    a, b, d = (kayit(st, m, valid_from=t) for m, t in (("Ocak", "2026-01-10"), ("Mart", "2026-03-10"), ("Mayıs", "2026-05-10")))
    giris(c)

    def ids(**q):
        return [k["id"] for k in c.get("/panel/gezgin/kayitlar", params=q).json()["kayitlar"]]
    assert ids() == [d, b, a] and ids(sira="eski") == [a, b, d]
    assert ids(son="2026-03-10") == [b, a] and ids(bas="2026-03-10", son="2026-04-01") == [b]
    act = Actor("x", "genel")
    st.supersede(act, a, b, "t")
    st.archive(act, d, "t")
    assert ids(durum="eski") == [a] and ids(durum="arsiv") == [d] and ids(durum="guncel") == [b]
    st.archive(act, a, "t")                      # hem geçersiz kılınmış hem arşivde: 'arşiv' sayılır
    assert ids(durum="eski") == [] and ids(durum="arsiv", sira="eski") == [a, d]


def test_sayfalama(ortam):
    st, c, _ = ortam
    for i in range(120):
        kayit(st, f"Kayıt {i}")
    giris(c)
    parcalar = [c.get("/panel/gezgin/kayitlar", params={"sayfa": n}).json() for n in range(3)]
    assert [len(p["kayitlar"]) for p in parcalar] == [50, 50, 20] and all(p["toplam"] == 120 for p in parcalar)
    assert len({k["id"] for p in parcalar for k in p["kayitlar"]}) == 120


def test_sinirlar(ortam):
    st, c, _ = ortam
    a = kayit(st, "Bir")
    notlar = [kayit(st, f"Not {i}") for i in range(21)]
    csrf = giris(c)
    temel = {"id": a, "tur": "fact", "gorunurluk": "shared", "guven": "user", "tarih": "2026-11-09"}
    uzun = "ab " * 1333                                                         # 3999 karakter
    for ek in ({"metin": "ab"}, {"metin": uzun + "ab"}, {"metin": "abc", "baglam": "ab " * 333 + "ab"}):
        assert post(c, "duzelt", {**temel, **ek}, csrf).status_code == 400, {k: len(v) for k, v in ek.items()}
    assert post(c, "arsivle", {"id": a, "neden": "ab"}, csrf).status_code == 400
    assert post(c, "birlestir", {**temel, "metin": "Birleşik", "ids": notlar}, csrf).status_code == 400            # 21 kayıt
    assert st.is_current(a) and all(st.is_current(i) for i in notlar)
    assert post(c, "duzelt", {**temel, "metin": uzun + "a", "baglam": "ab " * 333 + "a"}, csrf).status_code == 200   # 4000 ve 1000
    assert post(c, "birlestir", {**temel, "metin": "Birleşik", "ids": notlar[:20]}, csrf).status_code == 200


def test_gizli_bilgi_baglam_ve_anahtar(ortam):
    st, c, _ = ortam
    a = kayit(st, "Bir")
    csrf = giris(c)
    temel = {"id": a, "metin": "Zararsız metin", "tur": "fact", "gorunurluk": "shared", "guven": "user", "tarih": "2026-11-09"}
    assert post(c, "duzelt", {**temel, "baglam": f"IBAN {IBAN}"}, csrf).status_code == 400
    assert post(c, "duzelt", {**temel, "anahtarlar": ["banka", IBAN]}, csrf).status_code == 400
    assert st.is_current(a)


def test_birlestir_hedef_proje_ve_guven(ortam):
    """Kaynaklar tek projedense yeni kayıt o projeye yazılır; güven tabanı kaynakların en düşüğüdür."""
    st, c, _ = ortam
    a, b = kayit(st, "Sınav ocakta", project="okul"), kayit(st, "Sınav ocak ayında", project="okul", trust="agent")
    csrf = giris(c)
    govde = {"ids": [a, b], "metin": "Sınav ocak ayında.", "tur": "event", "gorunurluk": "shared", "tarih": "2026-11-09"}
    r = post(c, "birlestir", {**govde, "guven": "user"}, csrf)
    assert r.status_code == 400 and "Güven" in r.json()["hata"]
    r = post(c, "birlestir", {**govde, "guven": "agent"}, csrf)
    assert r.status_code == 200, r.text
    assert st.get(r.json()["yeni"])["project"] == "okul"


def test_gecersiz_kil_yeni_guncel_olmali(ortam):
    st, c, _ = ortam
    a, b = kayit(st, "Oruç 30 gün"), kayit(st, "Oruç 29 gün")
    st.archive(Actor("x", "genel"), b, "t")
    csrf = giris(c)
    assert post(c, "gecersiz-kil", {"eski": a, "yeni": b}, csrf).status_code == 409 and st.is_current(a)


def test_yanitta_vektor_yok(ortam):
    st, c, _ = ortam
    a = kayit(st, "Bir")
    st.set_embedding(a, b"\x00" * 16, "bge-m3")
    giris(c)
    assert set(c.get("/panel/gezgin/kayitlar").json()["kayitlar"][0]) == ALANLAR
    assert set(c.get(f"/panel/gezgin/kayit/{a}").json()["kayit"]) == ALANLAR


def test_tarihsiz_kayit_yazildigi_gunu_gosterir(ortam):
    import time
    st, c, _ = ortam
    a = st.add_record(Actor("x", "genel"), {"text": "Tarihsiz", "kind": "fact", "visibility": "shared", "trust": "user"})
    st.x("UPDATE records SET created_at=? WHERE id=?", (time.mktime((2025, 3, 3, 12, 0, 0, 0, 0, -1)), a))
    giris(c)
    assert c.get("/panel/gezgin/kayitlar", params={"durum": "hepsi"}).json()["kayitlar"][0]["tarih"] == "2025-03-03"


# ------------------------------------------------------------------ arama (tasarim/GEZGIN.md §5.1)
def test_numara_aramasi_suzgecleri_yok_sayar(ortam):
    st, c, _ = ortam
    a = kayit(st, "Güncel not", project="genel")
    b = kayit(st, "Arşivlenecek not", project="okul", tool="hermes", kind="event", valid_from="2026-01-01")
    st.archive(Actor("x", "okul"), b, "t")
    giris(c)

    def al(q):
        return c.get("/panel/gezgin/kayitlar", params=q).json()
    assert [k["id"] for k in al({"q": b})["kayitlar"]] == [b]                              # durum varsayılanı 'guncel'
    assert [k["id"] for k in al({"q": f" {b.lower()} "})["kayitlar"]] == [b]               # küçük harf + boşluk
    assert [k["id"] for k in al({"q": b, "proje": "genel", "arac": "claude-code", "tur": "fact",
                                 "bas": "2026-11-01", "durum": "guncel"})["kayitlar"]] == [b]
    assert al({"q": "R99999"})["toplam"] == 0                                              # yok: hata değil, boş
    assert al({"q": a, "durum": "arsiv"})["toplam"] == 1
    kayit(st, "R00517 kaydının yerine yazıldı")            # 5 harfli kök: R00517 ve R00518 ikisi de 'r0051'
    assert al({"q": "R00518"})["toplam"] == 0              # var olmayan numara ilgisiz kayıt getirmez
    assert al({"q": "R00517 kaydı"})["toplam"] == 1        # tam numara değilse normal metin araması


def vek(cos):
    """İlk bileşeni 'cos' olan birim vektör; sahte sorgu vektörü [1, 0] ile kosinüs benzerliği tam 'cos' olur."""
    return np.array([cos, (1 - cos * cos) ** 0.5], dtype=np.float32).tobytes()


def ham(i, metin, cos=None, emb=None):
    r = {"id": f"R{i:05d}", "text": metin, "context": "", "keys": "[]"}
    if cos is not None or emb is not None:
        r["embedding"] = vek(cos) if emb is None else emb
    return r


@pytest.fixture
def sahte_gomme(monkeypatch):
    """Gömme açık, model yok: her sorgunun vektörü [1, 0]. Çağrı sayısı döner."""
    sayac = {"n": 0}

    def embed(texts):
        sayac["n"] += 1
        return np.array([[1.0, 0.0]] * len(texts), dtype=np.float32)
    monkeypatch.setattr(search, "EMBED_MODEL", "bge-m3")
    monkeypatch.setattr(search, "embed", embed)
    return sayac


def test_ilgili_esik_siniri(sahte_gomme):
    e = gezgin.ANLAM_ESIK
    kayitlar = [ham(1, "elma armut", e + 0.02), ham(2, "kiraz vişne", e - 0.02)]
    assert [r["id"] for r in gezgin.ilgili(kayitlar, "bambaşka sorgu")] == ["R00001"]          # eşiğin üstü girer, altı girmez
    assert gezgin.ilgili(kayitlar, "bambaşka sorgu", esik=e + 0.05) == []
    assert [r["id"] for r in gezgin.ilgili(kayitlar, "bambaşka sorgu", esik=e - 0.05)] == ["R00001", "R00002"]


def test_ilgili_kelime_eslesmesi_esikten_bagimsiz(sahte_gomme):
    kayitlar = [ham(1, "Yüzme antrenmanı salı günü", 0.0), ham(2, "Fizik sınavı ocakta", 0.0)]
    assert [r["id"] for r in gezgin.ilgili(kayitlar, "yüzme")] == ["R00001"]


def test_ilgili_gomme_hatasi_bm25e_duser(sahte_gomme, monkeypatch):
    def bozuk(texts):
        raise RuntimeError("model yüklenemedi")
    monkeypatch.setattr(search, "embed", bozuk)
    kayitlar = [ham(1, "Yüzme antrenmanı salı günü", 0.99), ham(2, "Fizik sınavı ocakta", 0.99)]
    assert [r["id"] for r in gezgin.ilgili(kayitlar, "yüzme")] == ["R00001"]                   # istisna çıkmaz, kelime araması sürer


def test_ilgili_vektorsuz_ve_boyutu_uymayan_yok_sayilir(sahte_gomme):
    uc_boyutlu = np.array([1.0, 0.0, 0.0], dtype=np.float32).tobytes()                         # başka modelden kalmış vektör
    kayitlar = [ham(1, "elma armut"), ham(2, "kiraz vişne", emb=uc_boyutlu), ham(3, "muz çilek", gezgin.ANLAM_ESIK + 0.1)]
    assert [r["id"] for r in gezgin.ilgili(kayitlar, "bambaşka sorgu")] == ["R00003"]          # bozuk vektör sonrakileri engellemez
    assert {r["id"] for r in gezgin.ilgili(kayitlar, "kiraz")} == {"R00002", "R00003"}        # kelime eşleşmesi + anlam


def test_ilgili_gomme_kapali_embed_cagirmaz(sahte_gomme, monkeypatch):
    monkeypatch.setattr(search, "EMBED_MODEL", "none")
    kayitlar = [ham(1, "Yüzme antrenmanı salı günü", 0.99), ham(2, "Fizik sınavı ocakta", 0.99)]
    assert [r["id"] for r in gezgin.ilgili(kayitlar, "yüzme")] == ["R00001"]
    assert sahte_gomme["n"] == 0


def test_arama_ilgisiz_sorguda_bos_http(ortam, sahte_gomme):
    """Az ama isabetli: kelimesi geçmeyen ve anlamca uzak bir aramada liste boş kalır."""
    st, c, _ = ortam
    e = gezgin.ANLAM_ESIK
    a, b = kayit(st, "Yüzme antrenmanı salı günü"), kayit(st, "Fizik sınavı ocakta")
    for i in (a, b):
        st.set_embedding(i, vek(e - 0.1), "bge-m3")
    giris(c)

    def ara(q):
        return c.get("/panel/gezgin/kayitlar", params={"q": q}).json()
    assert ara("kuantum dolanıklığı")["toplam"] == 0
    st.set_embedding(b, vek(e + 0.1), "bge-m3")
    v = ara("kuantum dolanıklığı")
    assert [k["id"] for k in v["kayitlar"]] == [b] and set(v["kayitlar"][0]) == ALANLAR


def test_ilgili_sorguyu_bir_kez_gomer(sahte_gomme):
    """CPU'da model çağrısı pahalı: bir arama sorguyu yalnız bir kez gömer."""
    e = gezgin.ANLAM_ESIK
    kayitlar = [ham(1, "elma armut", e + 0.1), ham(2, "Yüzme antrenmanı", e - 0.1)]
    assert {r["id"] for r in gezgin.ilgili(kayitlar, "yüzme")} == {"R00001", "R00002"}
    assert sahte_gomme["n"] == 1


def test_scores_ve_rank_gommeli(sahte_gomme):
    """search.scores / search.rank (MCP hafiza_ara'nın yolu): kosinüsler doğru hesaplanır, gömme açıkken kayıt elenmez."""
    kayitlar = [ham(1, "kiraz vişne"), ham(2, "muz çilek", 0.5), ham(3, "Yüzme antrenmanı", 0.9)]
    bm, dense = search.scores(kayitlar, "yüzme")
    assert (bm > 0).tolist() == [False, False, True]
    assert dense.tolist() == pytest.approx([-1.0, 0.5, 0.9])                      # vektörsüz kayıt -1
    assert sahte_gomme["n"] == 1
    sirali = [r["id"] for r in search.rank(kayitlar, "yüzme")]
    assert sirali[0] == "R00003" and sorted(sirali) == ["R00001", "R00002", "R00003"]


def test_ilgili_kelime_yaridan_fazla_kok(sahte_gomme):
    """Anlam yolu varken tek bir ortak kök yetmez: kayıt, sorgudaki farklı köklerin yarıdan fazlasını içermeli (tek
    kelimelik arama aynı kalır). Kayıtların kosinüsü 0: sonuç yalnız kelime yolundan gelir."""
    kayitlar = [ham(1, "Bonsai budama teknikleri kursu", 0.0), ham(2, "Yüzme teknikleri antrenmanı", 0.0), ham(3, "Fizik sınavı ocakta", 0.0)]

    def ara(q):
        return [r["id"] for r in gezgin.ilgili(kayitlar, q)]
    assert ara("bonsai budama teknikleri") == ["R00001"]            # R00002 yalnız 'teknik' kökünü paylaşıyor: 3'te 1
    assert sorted(ara("teknikleri")) == ["R00001", "R00002"]        # tek kelime: o kelime yeter
    assert ara("yüzme teknikleri") == ["R00002"]                    # 2'de 1 tam yarı: yetmez
    assert ara("bonsai budama yüzme") == ["R00001"]                 # 3'te 2
    assert ara("?!") == []


def test_ilgili_tek_kok_ve_dusuk_benzerlik_girmez(sahte_gomme):
    e = gezgin.ANLAM_ESIK
    assert gezgin.ilgili([ham(1, "Yüzme teknikleri antrenmanı", e - 0.1)], "bonsai budama teknikleri") == []
    assert [r["id"] for r in gezgin.ilgili([ham(1, "Yüzme teknikleri antrenmanı", e + 0.1)], "bonsai budama teknikleri")] == ["R00001"]


# ------------------------------------------------------------------ girdi doğrulama ve hata yanıtları
DUZ = {"tur": "fact", "gorunurluk": "shared", "guven": "user"}


def test_tarih_bos_eski_tarihi_korur(ortam):
    """Formda tarihi silmek kaydın tarihini bugüne çekmez."""
    st, c, _ = ortam
    a, b = kayit(st, "Bir", valid_from="2025-03-03"), kayit(st, "İki", valid_from="2025-03-03")
    x, y = kayit(st, "Üç", valid_from="2025-03-03"), kayit(st, "Dört", valid_from="2025-06-01")
    csrf = giris(c)
    r = post(c, "duzelt", {**DUZ, "id": a, "metin": "Bir (düzeltildi)", "tarih": ""}, csrf)
    assert r.status_code == 200 and st.get(r.json()["yeni"])["valid_from"] == "2025-03-03"
    r = post(c, "duzelt", {**DUZ, "id": b, "metin": "İki (düzeltildi)"}, csrf)                       # tarih alanı hiç yok
    assert r.status_code == 200 and st.get(r.json()["yeni"])["valid_from"] == "2025-03-03"
    r = post(c, "birlestir", {**DUZ, "ids": [x, y], "metin": "Üç ve dört", "tarih": ""}, csrf)
    assert r.status_code == 200 and st.get(r.json()["yeni"])["valid_from"] == "2025-06-01"        # kaynakların en yenisi


def test_tarih_gecersiz_400(ortam):
    st, c, _ = ortam
    a = kayit(st, "Bir", valid_from="2025-03-03")
    csrf = giris(c)
    for t in ("31.12.2026", "2026-02-30", "yarın"):
        assert post(c, "duzelt", {**DUZ, "id": a, "metin": "Bir (düzeltildi)", "tarih": t}, csrf).status_code == 400, t
    assert st.is_current(a)


def test_beklenmeyen_hata_500_ic_ileti_sizmaz(ortam, monkeypatch):
    """Yalnız 'kayıt bu arada değişti' çakışması 409'dur; başka her hata 500 ve iç ayrıntı sızdırmaz."""
    from council_hafiza import store as depo
    st, c, _ = ortam
    a = kayit(st, "Bir")
    csrf = giris(c)
    govde = {**DUZ, "id": a, "metin": "Bir (düzeltildi)", "tarih": "2026-11-09"}

    def patlar(hata):
        def f(*args, **kw):
            raise hata
        return f
    monkeypatch.setattr(st, "replace_records", patlar(ValueError("ic ayrinti: tablo records")))
    r = post(c, "duzelt", govde, csrf)
    assert r.status_code == 500 and "ic ayrinti" not in r.text
    monkeypatch.setattr(st, "replace_records", patlar(depo.Cakisma(f"{a} artık güncel değil")))
    r = post(c, "duzelt", govde, csrf)
    assert r.status_code == 409 and "güncel değil" in r.json()["hata"]


def test_replace_records_cakisma_atar(tmp_path):
    from council_hafiza import store as depo
    st = Store(tmp_path / "s.sqlite", anahtar="")
    a = kayit(st, "Bir")
    st.archive(Actor("x", "genel"), a, "t")
    with pytest.raises(depo.Cakisma):
        st.replace_records(Actor("gezgin", "genel"), [a], {"text": "Düzeltme", "kind": "fact", "visibility": "shared", "trust": "user"}, "r", "duzelt")


def test_kodlanamayan_metin_400(ortam):
    st, c, _ = ortam
    a = kayit(st, "Bir")
    csrf = giris(c)
    yarim = "abc\ud800"                                   # tek başına vekil karakter: UTF-8'e yazılamaz
    assert post(c, "duzelt", {**DUZ, "id": a, "metin": yarim, "tarih": "2026-11-09"}, csrf).status_code == 400
    assert post(c, "duzelt", {**DUZ, "id": a, "metin": "Düzgün metin", "baglam": yarim, "tarih": "2026-11-09"}, csrf).status_code == 400
    assert post(c, "arsivle", {"id": a, "neden": yarim}, csrf).status_code == 400
    assert st.is_current(a) and st.verify_chain()


def test_baglam_uzun_iletisi(ortam):
    st, c, _ = ortam
    a = kayit(st, "Bir")
    csrf = giris(c)
    r = post(c, "duzelt", {**DUZ, "id": a, "metin": "abc", "baglam": "ab " * 333 + "ab", "tarih": "2026-11-09"}, csrf)
    assert r.status_code == 400 and "Bağlam" in r.json()["hata"] and "Metin" not in r.json()["hata"]


def test_karisik_proje_iletisi():
    ozel_a = {"visibility": "project", "trust": "user", "project": "a"}
    ortak_b = {"visibility": "shared", "trust": "user", "project": "b"}
    assert gezgin.kural_denetle([ozel_a, ortak_b], {"visibility": "shared", "trust": "user"}).startswith("Projeye özel ve ortak")
    assert gezgin.kural_denetle([ozel_a, {**ozel_a, "project": "b"}], {"visibility": "project", "trust": "user"}).startswith("Farklı projelerin")


# ------------------------------------------------------------------ depo ve öneri sağlamlığı
def test_supersede_yeni_guncel_olmali(tmp_path):
    """Yerine geçen kayıt işlem anında güncel olmalı: arşivdeki kayda bağlanma, A↔B döngüsü ve kendine bağlanma olmaz."""
    st = Store(tmp_path / "s.sqlite", anahtar="")
    a, b, arsivde, d = kayit(st, "A"), kayit(st, "B"), kayit(st, "Arşivde"), kayit(st, "D")
    act = Actor("gezgin", "genel")
    st.archive(act, arsivde, "t")
    assert st.supersede(act, a, arsivde, "t") is False and st.is_current(a)
    assert st.supersede(act, a, a, "t") is False and st.is_current(a)
    assert st.supersede(act, a, b, "t") is True
    assert st.supersede(act, b, a, "t") is False and st.is_current(b)          # a artık güncel değil: döngü oluşmaz
    assert st.supersede(act, d, None, "t") is True                             # yerine kayıt vermeden geçersiz kılma sürer
    assert [r["id"] for r in st.list_records() if st.is_current(r["id"])] == [b] and st.verify_chain()


def test_oneriler_bozuk_rapor(ortam):
    st, c, dd = ortam
    kayit(st, "Bir")
    giris(c)
    for icerik in ("[1, 2]", '{"bulgular": [5]}', '{"bulgular": "x"}', '{"bulgular": null}', "{bozuk"):
        (dd / "son.json").write_text(icerik, encoding="utf-8")
        r = c.get("/panel/gezgin/oneriler")
        assert r.status_code == 200 and r.json() == {"oneriler": []}, icerik


def test_oneriler_kimlik_siniri(ortam):
    st, c, dd = ortam
    a = kayit(st, "Oruç 30 gün")                                              # R00001
    giris(c)

    def oneriler(bulgu_id):
        (dd / "son.json").write_text(json.dumps({"bulgular": [{"id": bulgu_id, "baslik": "Çelişen kayıtlar"}]}), encoding="utf-8")
        return c.get("/panel/gezgin/oneriler").json()["oneriler"]
    assert [k["id"] for k in oneriler(f"model-celiski-{a}")[0]["kayitlar"]] == [a]
    assert oneriler("model-celiski-R000011") == []                             # 6 rakamlı kimlik R00001 sayılmaz


def test_ozel_ortak_onay_ister(ortam):
    """Projeye özel bir kaydı ortak yapmak (bütün projelere açmak) açık onay ister; özel kalırsa onay gerekmez."""
    st, c, _ = ortam
    a, b, x, y = (kayit(st, m, project="is", visibility="project") for m in ("İş notu", "İş notu 2", "Özel 1", "Özel 2"))
    csrf = giris(c)
    govde = {**DUZ, "id": a, "metin": "İş notu (düzeltildi)", "tarih": "2026-11-09"}               # DUZ: gorunurluk shared
    r = post(c, "duzelt", govde, csrf)
    assert r.status_code == 400 and "Görünürlük" in r.json()["hata"] and st.is_current(a)
    assert post(c, "duzelt", {**govde, "gorunurluk_onay": "true"}, csrf).status_code == 400       # metin değil, gerçek true
    r = post(c, "duzelt", {**govde, "gorunurluk_onay": True}, csrf)
    assert r.status_code == 200 and st.get(r.json()["yeni"])["visibility"] == "shared"
    assert post(c, "duzelt", {**govde, "id": b, "gorunurluk": "project"}, csrf).status_code == 200    # özel → özel
    birlesik = {**DUZ, "ids": [x, y], "metin": "Birleşik özel not", "tarih": "2026-11-09"}
    assert post(c, "birlestir", birlesik, csrf).status_code == 400 and st.is_current(x)
    assert post(c, "birlestir", {**birlesik, "gorunurluk_onay": True}, csrf).status_code == 200


def test_ilgili_anlam_yolu_yokken_tek_kok_yeter(sahte_gomme, monkeypatch):
    """Yarıdan fazla kök kuralı anlam yolunun telafisine dayanır. Gömme kapalıysa ya da model hata verirse çok kelimeli
    arama boş dönmesin diye kelime yolu eski hâline (herhangi bir ortak kök) döner."""
    kayitlar = [ham(1, "Bonsai budama teknikleri kursu", 0.0), ham(2, "Yüzme teknikleri antrenmanı", 0.0), ham(3, "Fizik sınavı ocakta", 0.0)]
    assert [r["id"] for r in gezgin.ilgili(kayitlar, "bonsai budama teknikleri")] == ["R00001"]          # anlam yolu var: sıkı kural

    def bozuk(texts):
        raise RuntimeError("model yüklenemedi")
    monkeypatch.setattr(search, "embed", bozuk)
    assert sorted(r["id"] for r in gezgin.ilgili(kayitlar, "bonsai budama teknikleri")) == ["R00001", "R00002"]
    monkeypatch.setattr(search, "EMBED_MODEL", "none")
    assert sorted(r["id"] for r in gezgin.ilgili(kayitlar, "bonsai budama teknikleri")) == ["R00001", "R00002"]
    assert gezgin.ilgili(kayitlar, "kuantum dolanıklığı") == []
