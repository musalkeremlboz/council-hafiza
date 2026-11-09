"""Panel: imzalı oturum, giriş/çıkış, korunan veri ucu ve güvenlik başlıkları."""
import json
import time

from fastmcp import FastMCP
from starlette.testclient import TestClient

from council_hafiza import panel
from council_hafiza.auth import hash_password
from council_hafiza.store import Store


class SahteAuth:
    def __init__(self, h):
        self.admin_hash, self.kayit = h, []

    def giris_engelli(self, ip):
        return False

    def giris_kaydet(self, ip, ok):
        self.kayit.append((ip, ok))


def test_oturum_imzasi():
    h = hash_password("dogru-parola-123")
    o = panel.oturum_imzala(h)
    assert panel.oturum_gecerli(h, o)
    assert not panel.oturum_gecerli(hash_password("baska-parola-456"), o)          # parola değişince düşer
    assert not panel.oturum_gecerli(h, o, simdi=time.time() + panel.OTURUM_SURE + 5)   # süre doldu
    assert not panel.oturum_gecerli(h, o[:-1] + ("0" if o[-1] != "0" else "1"))
    assert not panel.oturum_gecerli(h, None) and not panel.oturum_gecerli("", o)
    assert not panel.oturum_gecerli(h, "\u00b2.abc")                         # Unicode rakamı 500 hatası vermez


def test_panel_akisi(tmp_path, monkeypatch):
    st = Store(tmp_path / "p.sqlite", anahtar="")
    (tmp_path / "denetim" / "gecmis").mkdir(parents=True)
    rapor = {"zaman": "2026-11-08T10:00:00+00:00", "ozet": {"kritik": 1}, "bulgular": [{"baslik": "<script>x</script>"}]}
    (tmp_path / "denetim" / "son.json").write_text(json.dumps(rapor))
    monkeypatch.setenv("COUNCIL_DENETIM_DIR", str(tmp_path / "denetim"))
    m = FastMCP("t")
    auth = SahteAuth(hash_password("dogru-parola-123"))
    panel.kaydet(m, auth, st)
    c = TestClient(m.http_app(), base_url="https://test")
    r = c.get("/panel")
    assert r.status_code == 200 and 'name="parola"' in r.text and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert c.get("/panel/veri").status_code == 401
    assert c.post("/panel/giris", data={"parola": "yanlis"}).status_code == 401
    r = c.post("/panel/giris", data={"parola": "dogru-parola-123"}, follow_redirects=False)
    assert r.status_code == 303 and "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    v = c.get("/panel/veri").json()
    assert v["hazir"] and v["rapor"]["ozet"]["kritik"] == 1
    assert "panel.js" in c.get("/panel").text and c.get("/panel/panel.js").status_code == 200
    c.post("/panel/cikis")
    assert c.get("/panel/veri").status_code == 401
    assert [ok for _, ok in auth.kayit] == [False, True]


def test_dev_cerez_500_vermez():
    """Binlerce rakamlı 'bitiş' değeri int() sınırına takılıp 500 üretmesin; geçersiz oturum sayılsın."""
    assert panel.oturum_gecerli("h", "9" * 5000 + ".x") is False


def _istemci(tmp_path):
    m = FastMCP("t")
    panel.kaydet(m, SahteAuth(hash_password("dogru-parola-123")), Store(tmp_path / "p.sqlite", anahtar=""))
    return TestClient(m.http_app(), base_url="https://test")


def test_kimlik_yazilari_sunucudan_gelir(tmp_path):
    """Kimlik yazıları (Anton, IBM Plex Mono, Kapsül) paketten sunulur; dışarıya istek gitmez, giriş sayfası da kullanır."""
    import re
    c = _istemci(tmp_path)
    giris = c.get("/panel")
    assert "font-src 'self'" in giris.headers["content-security-policy"]
    assert "/panel/kimlik.css" in giris.text                                  # giriş sayfası da kimliği kullanır
    css = c.get("/panel/kimlik.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    adlar = re.findall(r"url\(/panel/font/([^)]+)\)", css.text)
    assert {"Anton-Regular.ttf", "IBMPlexMono-Regular.ttf", "IBMPlexMono-Medium.ttf", "COUNCIL-Kapsul-Kalin.otf"} == set(adlar)
    assert "http" not in css.text                                             # dış kaynak yok
    for ad in adlar:
        r = c.get(f"/panel/font/{ad}")                                        # girişsiz: giriş sayfası da yazıyı yükler
        assert r.status_code == 200 and r.headers["content-type"].startswith("font/") and len(r.content) > 5000
        assert r.headers["x-content-type-options"] == "nosniff"
    for kotu in ("yok.ttf", "..%2Fpanel.py", "OFL-Anton.md"):
        assert c.get(f"/panel/font/{kotu}").status_code == 404


def test_panel_ve_gezgin_ortak_kimligi_kullanir(tmp_path):
    c = _istemci(tmp_path)
    c.post("/panel/giris", data={"parola": "dogru-parola-123"})
    for yol in ("/panel", "/panel/gezgin"):
        assert "/panel/kimlik.css" in c.get(yol).text
    for yol in ("/panel/panel.css", "/panel/gezgin/gezgin.css"):
        t = c.get(yol).text
        assert "#2d5bd7" not in t and "border-radius: 10px" not in t          # eski mavi-gri görünüm kalmadı
        assert "--kagit:" not in t                                            # renkler tek yerde: kimlik.css


def test_yazilar_pakete_girer():
    """Yazı dosyaları kurulan pakette yoksa ekran yedek yazıya düşer. (Yayın listesi denetimi: tests/test_yayin.py)"""
    from pathlib import Path
    kok = Path(panel.__file__).resolve().parents[1]
    fontlar = sorted(p.name for p in (kok / "council_hafiza" / "fontlar").iterdir())
    assert len([f for f in fontlar if f.endswith((".ttf", ".otf"))]) == 4
    assert any(f.startswith("OFL-Anton") for f in fontlar) and any(f.startswith("OFL-IBMPlexMono") for f in fontlar)   # lisans metinleri
    assert '"fontlar/*"' in (kok / "pyproject.toml").read_text(encoding="utf-8")
