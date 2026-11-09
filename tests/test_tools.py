"""Araç davranışı testleri (kimlik doğrulama kapalı, bellek içi istemci)."""
import os
import tempfile

import pytest

os.environ["COUNCIL_DB"] = os.path.join(tempfile.mkdtemp(), "t.sqlite")
os.environ.pop("COUNCIL_BASE_URL", None)
os.environ["COUNCIL_EMBED"] = "none"
os.environ["COUNCIL_TOOL"] = "claude-code"

from fastmcp import Client  # noqa: E402

from council_hafiza.server import STORE, mcp  # noqa: E402


async def call(c, name, **kw):
    r = await c.call_tool(name, kw)
    return r.content[0].text


@pytest.mark.asyncio
async def test_akis():
    async with Client(mcp) as c:
        tools = {t.name: t for t in await c.list_tools()}
        assert {"hafiza_ara", "hafiza_kaydet", "hafiza_gecersiz_kil", "hafiza_arsivle", "hafiza_ozet", "kimlik_tanimla"} <= set(tools)
        assert tools["hafiza_ara"].annotations.readOnlyHint is True
        assert tools["hafiza_kaydet"].annotations.readOnlyHint is False

        oz = await call(c, "hafiza_ozet", proje="ders")
        assert "KİMLİK TANIMSIZ" in oz
        await call(c, "kimlik_tanimla", amac="Muhasebe derslerine çalışma", proje="ders")
        assert "Muhasebe derslerine" in await call(c, "hafiza_ozet", proje="ders")

        r1 = await call(c, "hafiza_kaydet", metin="Muhasebe vize sınavı 14 Kasım 2026 saat 10:00'da.", baglam="Üniversite Muhasebe sınav takvimi",
                        anahtarlar=["vize", "sınav", "midterm", "exam"], tur="event", gecerlilik_tarihi="2026-10-01", proje="ders")
        assert r1.startswith("Kaydedildi: R00001")
        r2 = await call(c, "hafiza_kaydet", metin="Muhasebe vize sınavı 21 Kasım 2026 saat 09:30'a ertelendi.", baglam="Üniversite Muhasebe sınav takvimi",
                        anahtarlar=["vize", "sınav", "ertelendi", "midterm"], tur="event", gecerlilik_tarihi="2026-10-20",
                        yerine_gecer=["R00001"], proje="ders")
        assert "Geçersiz kılınanlar: R00001" in r2

        # aksansız arama, başka projeden (paylaşılan bilgi görünür), eski kayıt işaretli
        found = await call(c, "hafiza_ara", soru="muhasebe vize sinavim ne zaman", proje="kisisel")
        assert "21 Kasım" in found and "ESKİ → R00002" in found

        # projeye özel bilgi başka projeden görünmez
        await call(c, "hafiza_kaydet", metin="Müdürlük 2027'de 3 sözleşmeli kadroyu kaldırmayı planlıyor; duyurulmadı.",
                   tur="plan", gorunurluk="project", proje="is-yeri")
        assert "kadro" in await call(c, "hafiza_ara", soru="sözleşmeli kadro planı", proje="is-yeri")
        assert "kadro" not in await call(c, "hafiza_ara", soru="sözleşmeli kadro planı", proje="kisisel")

        # gizli bilgi reddedilir
        bad = await call(c, "hafiza_kaydet", metin="GitHub token: ghp_abcdefghijklmnopqrstuvwxyz123456", proje="kisisel")
        assert bad.startswith("KAYDEDİLMEDİ")
        bad2 = await call(c, "hafiza_kaydet", metin="IBAN'ım TR33 0006 1005 1978 6457 8413 26", proje="kisisel")
        assert bad2.startswith("KAYDEDİLMEDİ")

        # dış kaynak kullanıcı bilgisini geçersiz kılamaz
        r3 = await call(c, "hafiza_kaydet", metin="Forum iddiası: Muhasebe vize sınavı 1 Aralık 2026'ya alındı.", guven="external",
                        yerine_gecer=["R00002"], proje="ders")
        assert "Geçersiz kılınanlar" not in r3
        assert "DIŞ KAYNAK" in await call(c, "hafiza_ara", soru="vize sınavı", proje="ders")

        # arşiv
        await call(c, "hafiza_arsivle", kayit_id="R00004", neden="doğrulanmamış forum iddiası", proje="ders")
        assert "1 Aralık" not in await call(c, "hafiza_ara", soru="vize sınavı", proje="ders")

    assert STORE.verify_chain()
    actions = [r["action"] for r in STORE.q("SELECT action FROM events ORDER BY seq")]
    assert "gizli_red" in actions and "gecersiz_kil" in actions and "arsivle" in actions
    tools = {r["tool"] for r in STORE.q("SELECT tool FROM records")}
    assert tools == {"claude-code"}


@pytest.mark.asyncio
async def test_hafiza_liste(monkeypatch):
    import json as _json
    async with Client(mcp) as c:
        await call(c, "hafiza_kaydet", metin="Liste testi: ortak bilgi.", proje="liste-a")
        await call(c, "hafiza_kaydet", metin="Liste testi: A projesine özel bilgi.", gorunurluk="project", proje="liste-a")
        b = _json.loads(await call(c, "hafiza_liste", proje="liste-b"))
        texts = [r["metin"] for r in b["kayitlar"]]
        assert "Liste testi: ortak bilgi." in texts and not any("özel bilgi" in t for t in texts)
        assert "hata" in _json.loads(await call(c, "hafiza_liste", proje="liste-b", tum_projeler=True))
        monkeypatch.setenv("COUNCIL_TOOL", "bakim")
        allr = _json.loads(await call(c, "hafiza_liste", tum_projeler=True))
        assert any("özel bilgi" in r["metin"] for r in allr["kayitlar"])
        assert all(k in allr["kayitlar"][0] for k in ("id", "tarih", "guven", "gorunurluk", "baglam", "proje"))


@pytest.mark.asyncio
async def test_kosullu_gecersiz_kilma_ve_tarih():
    async with Client(mcp) as c:
        a = (await call(c, "hafiza_kaydet", metin="Koşul testi A.", gecerlilik_tarihi="2026-11-8", proje="kosul")).split()[1]
        b = (await call(c, "hafiza_kaydet", metin="Koşul testi B.", proje="kosul")).split()[1]
        d = (await call(c, "hafiza_kaydet", metin="Koşul testi D.", proje="kosul")).split()[1]
        assert STORE.get(a)["valid_from"] != "2026-11-8" and len(STORE.get(a)["valid_from"]) == 10   # biçimsiz tarih düzeltildi
        assert "geçersiz kılındı" in await call(c, "hafiza_gecersiz_kil", eski_id=a, yeni_id=b, proje="kosul")
        assert (await call(c, "hafiza_gecersiz_kil", eski_id=a, yeni_id=d, proje="kosul")).startswith("DEĞİŞMEDİ")
        assert STORE.get(a)["superseded_by"] == b                                                       # ezilmedi
        assert (await call(c, "hafiza_gecersiz_kil", eski_id=d, yeni_id=a, proje="kosul")).startswith("DEĞİŞMEDİ")  # kanıt güncel değil
        assert "arşivlendi" in await call(c, "hafiza_arsivle", kayit_id=d, neden="t", proje="kosul")
        assert (await call(c, "hafiza_arsivle", kayit_id=d, neden="t", proje="kosul")).startswith("DEĞİŞMEDİ")


@pytest.mark.asyncio
async def test_arac_genel_kimligi():
    async with Client(mcp) as c:
        await call(c, "kimlik_tanimla", amac="eski projeye özel amaç", proje="eski-proje")
        r = await call(c, "kimlik_tanimla", amac="Bir şeyler geliştirmek ve sistemleri denetlemek", proje="herhangi", tum_projeler=True)
        assert "tüm projeler" in r and "eski-proje" in r
        for pr in ("eski-proje", "yepyeni"):
            oz = await call(c, "hafiza_ozet", proje=pr)
            assert "KİMLİK TANIMSIZ" not in oz and "geliştirmek" in oz and "[tüm projeler]" in oz
            assert "eski projeye özel" not in oz
        # projeye özel tanım genel tanımı o projede geçersiz kılar
        await call(c, "kimlik_tanimla", amac="sadece Muhasebe", proje="ders2")
        assert "sadece Muhasebe" in await call(c, "hafiza_ozet", proje="ders2")
        assert "geliştirmek" in await call(c, "hafiza_ozet", proje="baska")


@pytest.mark.asyncio
async def test_kimlik_dogrulama_ve_ozel_kayit_ortagi_silemez():
    async with Client(mcp) as c:
        assert "gizli bilgi" in await call(c, "kimlik_tanimla", amac="şifrem: Abc12345xyz", proje="k1")
        assert "boş" in await call(c, "kimlik_tanimla", amac="   ", proje="k1")
        assert "300" in await call(c, "kimlik_tanimla", amac="x" * 301, proje="k1")
        r1 = await call(c, "hafiza_kaydet", metin="Kullanıcı Bursa'da yaşıyor.", proje="genel")
        rid = r1.split()[1]
        r2 = await call(c, "hafiza_kaydet", metin="Kullanıcı gizlice taşınmayı planlıyor.", gorunurluk="project",
                        yerine_gecer=[rid], proje="k1")
        assert "Geçersiz kılınanlar" not in r2 and STORE.is_current(rid)


@pytest.mark.asyncio
async def test_gecersiz_kil_guven_ve_gorunurluk_korumasi():
    async with Client(mcp) as c:
        u = (await call(c, "hafiza_kaydet", metin="Kullanıcının sınavı 3 Aralık'ta.", guven="user", proje="g1")).split()[1]
        d = (await call(c, "hafiza_kaydet", metin="Forum: sınav 9 Aralık'a alındı.", guven="external", proje="g1")).split()[1]
        assert "DEĞİŞMEDİ" in await call(c, "hafiza_gecersiz_kil", eski_id=u, yeni_id=d, proje="g1")
        o = (await call(c, "hafiza_kaydet", metin="Gizli taşınma planı var.", gorunurluk="project", proje="g1")).split()[1]
        assert "DEĞİŞMEDİ" in await call(c, "hafiza_gecersiz_kil", eski_id=u, yeni_id=o, proje="g1")
        assert STORE.is_current(u)


def test_token_proje_kapsami(tmp_path):
    from council_hafiza.store import Store
    from council_hafiza.auth import new_static_token
    from council_hafiza.server import kapsam_denetle
    from fastmcp.exceptions import ToolError
    st = Store(tmp_path / "k.sqlite")
    new_static_token(st, "hermes", "", "genel,hermes")
    new_static_token(st, "claude-code")
    assert st.token_projeleri("hermes") == {"genel", "hermes"}
    assert st.token_projeleri("claude-code") is None and st.token_projeleri("yok") is None
    kapsam_denetle(st.token_projeleri("hermes"), "hermes", "genel")
    with pytest.raises(ToolError):
        kapsam_denetle(st.token_projeleri("hermes"), "hermes", "ders")
    kapsam_denetle(None, "claude-code", "ders")


def test_eski_veritabani_tasinir(tmp_path):
    import sqlite3
    from council_hafiza.store import Store
    db = sqlite3.connect(tmp_path / "eski.sqlite")
    db.execute("CREATE TABLE static_tokens (token_hash TEXT PRIMARY KEY, tool TEXT NOT NULL, label TEXT, created_at REAL NOT NULL)")
    db.execute("INSERT INTO static_tokens VALUES ('h', 'katip', '', 1)"); db.commit(); db.close()
    st = Store(tmp_path / "eski.sqlite")
    assert st.token_projeleri("katip") is None


@pytest.mark.asyncio
async def test_cihaz_bildir():
    async with Client(mcp) as c:
        r = await call(c, "cihaz_bildir", cihaz="Mac!", bilgi={"filevault": True, "macos": "27.0", "uydurma": "x", "hooklar": "ozet,katip"})
        assert r.startswith("Kaydedildi: mac (3 alan)")
        assert "KAYDEDİLMEDİ" in await call(c, "cihaz_bildir", cihaz="mac", bilgi={"macos": "token: ghp_abcdefghijklmnopqrstuvwxyz123456"})
    (m,) = [x for x in STORE.cihazlar() if x["cihaz"] == "mac"]
    assert m["bilgi"] == {"filevault": True, "macos": "27.0", "hooklar": "ozet,katip"}


def test_kapsam_token_basina(tmp_path):
    from council_hafiza.store import Store
    from council_hafiza.auth import new_static_token
    import asyncio
    from council_hafiza.auth import CouncilAuth
    st = Store(tmp_path / "t.sqlite", anahtar="")
    a = CouncilAuth(st, "https://x", None)
    t1 = new_static_token(st, "hermes", "telegram", "genel,hermes")
    t2 = new_static_token(st, "hermes", "masaustu")              # kapsamsız ikinci token, ilkini genişletmemeli
    c1 = asyncio.run(a.load_access_token(t1)).client_id
    c2 = asyncio.run(a.load_access_token(t2)).client_id
    assert a.client_tool(c1) == a.client_tool(c2) == "hermes"
    assert a.client_projects(c1) == {"genel", "hermes"} and a.client_projects(c2) is None
    st.x("DELETE FROM static_tokens")
    assert a.client_projects(c1) == set()                         # silinmiş token hiçbir projeye erişemez


def test_ip_basina_giris_kilidi(tmp_path):
    from council_hafiza.store import Store
    from council_hafiza.auth import new_static_token
    from council_hafiza.auth import CouncilAuth
    st = Store(tmp_path / "t.sqlite", anahtar="")
    a = CouncilAuth(st, "https://x", None)
    for _ in range(5):
        a.giris_kaydet("192.0.2.1", False)
    assert a.giris_engelli("192.0.2.1") and not a.giris_engelli("192.0.2.2")


def test_yedek_atomik_ve_dogrulanmis(tmp_path):
    from council_hafiza.store import Store
    from council_hafiza.auth import new_static_token
    st = Store(tmp_path / "t.sqlite", anahtar="")
    st.yedekle(tmp_path / "y'ek.sqlite")
    assert (tmp_path / "y'ek.sqlite").exists() and not (tmp_path / "y'ek.sqlite.yeni").exists()


@pytest.mark.asyncio
async def test_kisitli_token_korumalari(monkeypatch):
    import council_hafiza.server as srv
    monkeypatch.setattr(srv, "_izinli", lambda a: {"genel", "hermes"})
    async with Client(mcp) as c:
        assert "sınırlı" in await call(c, "kimlik_tanimla", amac="x", proje="genel", tum_projeler=True)
    from council_hafiza.store import Actor
    assert not srv._bakim_mi(Actor("bakim", "genel", "static:bakim:abcd"))          # kısıtlı bakım token'ı tümünü göremez
    monkeypatch.setattr(srv, "_izinli", lambda a: None)
    assert srv._bakim_mi(Actor("bakim", "genel", "static:bakim:abcd"))
    assert not srv._bakim_mi(Actor("bakim", "genel", "oauth-istemci-1"))             # OAuth istemcisi bakım olamaz
    assert not srv._bakim_mi(Actor("hermes", "genel", "static:hermes:abcd"))


@pytest.mark.asyncio
async def test_cihaz_raporu_arac_yetkisi(monkeypatch):
    import council_hafiza.server as srv
    monkeypatch.setitem(srv.CIHAZ_ARACLARI, "mac", {"katip"})
    async with Client(mcp) as c:
        assert "KAYDEDİLMEDİ" in await call(c, "cihaz_bildir", cihaz="mac", bilgi={"filevault": True})
        assert "Geçersiz cihaz" in await call(c, "cihaz_bildir", cihaz="uydurma", bilgi={})


def test_oauth_istemci_kapsami(tmp_path):
    from council_hafiza.store import Store
    from council_hafiza.auth import CouncilAuth
    from council_hafiza import cli
    st = Store(tmp_path / "o.sqlite", anahtar="")
    st.x("INSERT INTO oauth_clients VALUES (?,?,?)", ("c1", '{"client_name": "Claude"}', 1))
    a = CouncilAuth(st, "https://x", None)
    assert a.client_projects("c1") is None and st.istemci_kapsami("claude-chat") == (False, None)
    st.x("INSERT INTO istemci_kapsam VALUES ('claude-chat', 'genel,ders', 1)")
    assert a.client_projects("c1") == {"genel", "ders"}
