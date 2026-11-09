"""Model yönlendirme: seçim kuralı, sunucu araçları ve doğrulama."""
import os
import tempfile

os.environ.setdefault("COUNCIL_DB", os.path.join(tempfile.mkdtemp(), "t.sqlite"))
os.environ.pop("COUNCIL_BASE_URL", None)
os.environ["COUNCIL_EMBED"] = "none"

import numpy as np
import pytest
from fastmcp import Client

from council_hafiza import yonlendirme as Y
from council_hafiza.server import STORE, mcp


def _g():
    g = Y.Gecmis()
    a, b = np.array([1, 0], dtype=np.float32), np.array([0, 1], dtype=np.float32)
    # 'a' tipi görevlerde haiku yeterli, 'b' tipi görevlerde yalnız opus başarılı; ikisi de aynı iş türünde
    for i in range(5):
        g.ekle(a, "kod-yazma", "haiku/low", 95, 0.001, gorev=f"a{i}")
        g.ekle(a, "kod-yazma", "opus/high", 100, 0.05, gorev=f"a{i}")
        g.ekle(b, "kod-yazma", "haiku/low", 10, 0.001, gorev=f"b{i}")
        g.ekle(b, "kod-yazma", "opus/high", 100, 0.05, gorev=f"b{i}")
    return g, a, b


def test_soguk_baslangic():
    cfg, ger = Y.sec(Y.Gecmis(), np.zeros(2), "belge-soru", Y.Ayar())
    assert cfg == "haiku/low" and ger["kaynak"] == "soğuk başlangıç kuralı"
    assert Y.sec(Y.Gecmis(), np.zeros(2), "bilinmeyen", Y.Ayar())[0] == Y.VARSAYILAN


def test_knn_benzer_goreve_gore_secer():
    g, a, b = _g()
    ay = Y.Ayar(k=5, m=0.0, delta=5)
    assert Y.sec(g, a, "kod-yazma", ay)[0] == "haiku/low"     # benzerleri haiku ile çözülmüş
    assert Y.sec(g, b, "kod-yazma", ay)[0] == "opus/high"     # benzerleri yalnız opus ile çözülmüş


def test_yalniz_tur_ortalamasi_ve_delta():
    g, a, _ = _g()
    # tür ortalaması: haiku 52.5, opus 100 → δ=5 ile opus; δ=50 ile ucuz olan haiku
    assert Y.sec(g, a, "kod-yazma", Y.Ayar(k=0, delta=5, yalniz_tur=True))[0] == "opus/high"
    assert Y.sec(g, a, "kod-yazma", Y.Ayar(k=0, delta=50, yalniz_tur=True))[0] == "haiku/low"


def test_haric_tutulan_gorev_kullanilmaz():
    g = Y.Gecmis()
    g.ekle(np.array([1.0]), "dogrulama", "haiku/low", 100, 0.001, gorev="x")
    assert Y.tahmin(g, np.array([1.0]), "dogrulama", Y.Ayar(), haric="x") == {}


async def call(c, name, **kw):
    r = await c.call_tool(name, kw)
    return r.content[0].text


@pytest.mark.asyncio
async def test_sunucu_araclari():
    async with Client(mcp) as c:
        bos = await call(c, "yonlendirme_tablosu")
        assert "Geçerli kural yok" in bos and "sonuç yok" in bos
        oz = await call(c, "yonlendirme_oner", gorev="Şu e-postaları önceliğe göre etiketle", tur="siniflandirma")
        assert "Öneri yok" in oz and "ana model" in oz
        for _ in range(3):
            assert (await call(c, "yonlendirme_bildir", gorev="etiketleme işi", tur="siniflandirma", model="haiku",
                               effort="low", kalite=40, maliyet=0.001)).startswith("Kaydedildi")
        oz2 = await call(c, "yonlendirme_oner", gorev="etiketleme", tur="siniflandirma")
        assert "Öneri yok" in oz2 and "3 sonuç" in oz2       # canlı veri öneriyi henüz değiştirmez
        tab = await call(c, "yonlendirme_tablosu")
        assert "siniflandirma: haiku/low 40/3" in tab
        # doğrulama
        assert "Geçersiz" in await call(c, "yonlendirme_bildir", gorev="x", tur="uydurma", model="haiku", effort="low", kalite=50)
        assert "Geçersiz" in await call(c, "yonlendirme_bildir", gorev="x", tur="siniflandirma", model="gpt", effort="low", kalite=50)
        assert "0-100" in await call(c, "yonlendirme_bildir", gorev="x", tur="siniflandirma", model="haiku", effort="low", kalite=150)
        # gizli bilgi içeren görev metni saklanmaz
        await call(c, "yonlendirme_bildir", gorev="token: ghp_abcdefghijklmnopqrstuvwxyz123456 ile repo ayarı",
                   tur="kod-yazma", model="sonnet", effort="medium", kalite=80)
        assert all("ghp_" not in r["ozet"] for r in STORE.routing_rows())


@pytest.mark.asyncio
async def test_ilk_gozlem_gommeyi_baslatir(monkeypatch):
    from council_hafiza import search
    monkeypatch.setattr(search, "embed_enabled", lambda: True)
    monkeypatch.setattr(search, "embed", lambda xs: np.ones((len(xs), 4), dtype=np.float32) / 2)
    async with Client(mcp) as c:
        for _ in range(2):
            await call(c, "yonlendirme_bildir", gorev="özetleme işi", tur="belge-soru", model="sonnet", effort="low",
                       kalite=90, degerlendiren="uydurma-deger")
    rows = [r for r in STORE.routing_rows() if r["tur"] == "belge-soru"]
    assert rows and all(r["embedding"] and len(r["embedding"]) == 16 for r in rows)   # gömme boş tablodan da yazılır
    assert {r["degerlendiren"] for r in rows} == {"diger"}
