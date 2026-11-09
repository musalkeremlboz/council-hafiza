"""Gezgin: süzgeçli liste, düzelt, birleştir, arşiv, öneriler; oturum ve CSRF korumaları; hiçbir kaydın silinmemesi."""
import json

import pytest
from fastmcp import FastMCP
from starlette.testclient import TestClient

from council_hafiza import gezgin, panel
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
