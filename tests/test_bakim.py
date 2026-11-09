"""Bakım ajanı korumaları ve akışı (sahte MCP / sahte model)."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("council_istemci_b", ROOT / "council_hafiza" / "istemci.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


@pytest.fixture(autouse=True)
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "BAKIM_DIR", str(tmp_path / "bakim"))
    monkeypatch.setattr(ci, "STATE_DIR", str(tmp_path / "katip"))


def k(i, tarih="2026-10-01", guven="user", gor="shared", proje="genel", metin="x"):
    return {"id": i, "tarih": tarih, "arac": "katip", "proje": proje, "tur": "fact", "guven": guven, "gorunurluk": gor,
            "baglam": "b", "metin": metin}


RECS = [k("R1", "2026-09-01"), k("R2", "2026-10-01"), k("R3", "2026-10-05", guven="external"),
        k("R4", "2026-10-02", gor="project", proje="a"), k("R5", "2026-10-03", gor="project", proje="b"),
        k("R6", "2026-11-01")]


def test_korumalar():
    ops = [
        {"tur": "celiski", "eski": "R1", "yeni": "R2", "neden": "güncel değer"},                 # geçerli
        {"tur": "celiski", "eski": "R6", "yeni": "R2", "neden": "ters tarih"},                   # eski → yeni ezemez
        {"tur": "celiski", "eski": "R6", "yeni": "R3", "neden": "dış kaynak"},                   # dış kaynak ezemez
        {"tur": "tekrar", "sakla": "R4", "kaldir": ["R6"], "neden": "ortak→özel"},               # ortak kayıt özel kayıtla kaldırılamaz
        {"tur": "tekrar", "sakla": "R5", "kaldir": ["R4"], "neden": "farklı proje"},             # farklı projelerin özel kayıtları
        {"tur": "tekrar", "sakla": "R6", "kaldir": ["R4"], "neden": "özel→ortak"},               # geçerli
        {"tur": "tekrar", "sakla": "R1", "kaldir": ["R5"], "neden": "R1 zaten kaldırıldı"},      # kanıt kaldırılmış
        {"tur": "tamamlandi", "eski": "R99", "yeni": "R2", "neden": "uydurma"},                  # bilinmeyen
        {"tur": "tamamlandi", "eski": "R2 (2026-10-01): metin", "yeni": "[R6]", "neden": "zincir"},  # R2 bu çalışmada kanıttı: bekler
        {"tur": "tekrar", "sakla": "R6", "kaldir": ["R6"], "neden": "kendisi"},
        "çöp",
    ]
    out, rej = ci.bakim_dogrula(ops, RECS)
    assert [(o["islem"], o["id"], o["kanit"]) for o in out] == [("gecersiz", "R1", "R2"), ("arsivle", "R4", "R6")]
    joined = " | ".join(rej)
    for msg in ["daha eski kayıt", "dış kaynak", "ortak kayıt projeye özel", "farklı projelerin", "kanıt kaydı bu çalışmada kaldırıldı",
                "bilinmeyen kayıt", "kendisiyle", "zaten kullanıldı"]:
        assert msg in joined, msg


def test_kimlik_bicimi_ayiklanir():
    out, _ = ci.bakim_dogrula([{"tur": "celiski", "eski": "R1 (2026-09-01): metin", "yeni": "[R2]", "neden": "x"}], RECS)
    assert [(o["id"], o["kanit"]) for o in out] == [("R1", "R2")]


def test_islem_siniri():
    recs = [k(f"R{i}", f"2026-10-{i % 28 + 1:02d}") for i in range(1, 101)]
    ops = [{"tur": "tekrar", "sakla": "R1", "kaldir": [f"R{i}"], "neden": "x"} for i in range(2, 101)]
    out, rej = ci.bakim_dogrula(ops, recs)
    assert len(out) == min(ci.BAKIM_MAX_OPS, max(ci.BAKIM_MIN_OPS, int(100 * ci.BAKIM_MAX_FRAC)))
    assert any("işlem sınırı" in r for r in rej)


class FakeMCP:
    def __init__(self, recs):
        self.recs, self.calls = list(recs), []

    def call(self, name, args):
        self.calls.append((name, args))
        if name == "hafiza_liste":
            assert args["tum_projeler"] is True
            return json.dumps({"toplam": len(self.recs), "kayitlar": self.recs}, ensure_ascii=False)
        rid = args.get("kayit_id") or args.get("eski_id")
        self.recs = [r for r in self.recs if r["id"] != rid]
        return f"{rid} arşivlendi." if name == "hafiza_arsivle" else f"{rid} geçersiz kılındı, yerine {args['yeni_id']}."


def test_bakim_is_kuru_uygula_ve_degismeyen_hafiza():
    mcp = FakeMCP(RECS)
    model = lambda *a, **kw: {"islemler": [{"tur": "celiski", "eski": "R1", "yeni": "R2", "neden": "güncel"}]}
    dry = ci.cmd_bakim_is(kuru=True, mcp_fn=lambda: mcp, llm_fn=model)
    assert dry["islemler"][0]["id"] == "R1" and not [c for c in mcp.calls if c[0] != "hafiza_liste"]
    res = ci.cmd_bakim_is(mcp_fn=lambda: mcp, llm_fn=model)
    assert res["uygulanan"] == 1
    gk = [c for c in mcp.calls if c[0] == "hafiza_gecersiz_kil"][0][1]
    assert gk["eski_id"] == "R1" and gk["yeni_id"] == "R2" and gk["proje"] == "genel"
    # hafıza değişmedi: model çağrılmaz
    again = ci.cmd_bakim_is(mcp_fn=lambda: mcp, llm_fn=lambda *a, **kw: pytest.fail("çağrılmamalı"))
    assert again == {"atlandi": True}


def test_bakim_tetikleyici(monkeypatch, tmp_path):
    spawned = []
    monkeypatch.setattr(ci.subprocess, "Popen", lambda *a, **kw: spawned.append(a))
    ci.bakim_baslat_gerekirse()
    assert not spawned                                       # token yoksa başlamaz
    Path(ci.BAKIM_DIR).mkdir(parents=True)
    (Path(ci.BAKIM_DIR) / "token").write_text("chz_x")
    ci.bakim_baslat_gerekirse()
    assert len(spawned) == 1
    ci._yaz_bakim({"last_run": ci.time.time(), "hash": "h"})
    ci.bakim_baslat_gerekirse()
    assert len(spawned) == 1                                 # yakın zamanda çalıştı


def test_bakim_hatasinda_bir_saat_sonra_tekrar():
    def bad():
        raise ci.urllib.error.URLError("sunucu kapalı")
    assert ci.cmd_bakim_is(mcp_fn=bad) is None
    st = ci.bakim_durum()
    assert ci.time.time() - st["last_run"] > ci.BAKIM_GAP - 3700


def test_ayni_gun_ve_bicimsiz_tarih():
    recs = [k("R10", "2026-11-08"), k("R12", "2026-11-08"), k("R13", "2026-11-8")]
    out, rej = ci.bakim_dogrula([{"tur": "celiski", "eski": "R12", "yeni": "R10", "neden": "ters"},
                                 {"tur": "celiski", "eski": "R10", "yeni": "R13", "neden": "biçimsiz"},
                                 {"tur": "celiski", "eski": "R10", "yeni": "R12", "neden": "doğru"}], recs)
    assert [(o["id"], o["kanit"]) for o in out] == [("R10", "R12")]
    assert any("aynı gün" in r for r in rej) and any("tarih biçimi" in r for r in rej)


def test_ertelenen_islem_varsa_sonraki_calisma_modeli_cagirir():
    mcp = FakeMCP(RECS)
    chain = lambda *a, **kw: {"islemler": [{"tur": "celiski", "eski": "R1", "yeni": "R2", "neden": "a"},
                                           {"tur": "celiski", "eski": "R2", "yeni": "R6", "neden": "zincir"}]}
    ci.cmd_bakim_is(mcp_fn=lambda: mcp, llm_fn=chain)
    assert ci.bakim_durum()["hash"] == ""
    called = []
    ci.cmd_bakim_is(mcp_fn=lambda: mcp, llm_fn=lambda *a, **kw: called.append(1) or {"islemler": []})
    assert called                                            # ertelenen zincir yeniden değerlendirildi


def test_hata_beklemesi_ve_kuru_calisma():
    def bad():
        raise ci.urllib.error.URLError("sunucu kapalı")
    assert ci.cmd_bakim_is(kuru=True, mcp_fn=bad) is None
    assert ci.bakim_durum().get("fails", 0) == 0             # kuru çalışma durumu değiştirmez
    ci.cmd_bakim_is(mcp_fn=bad)
    ci.cmd_bakim_is(mcp_fn=bad)
    st = ci.bakim_durum()
    assert st["fails"] == 2
    kalan = ci.BAKIM_GAP - (ci.time.time() - st["last_run"])
    assert 4 * 3600 - 60 < kalan <= 4 * 3600                 # ikinci hatadan sonra 4 saat


def test_uygulanmayan_islem_sayilmaz():
    class StaleMCP(FakeMCP):
        def call(self, name, args):
            if name == "hafiza_gecersiz_kil":
                self.calls.append((name, args))
                return "DEĞİŞMEDİ: R1 zaten geçersiz ya da arşivde."
            return super().call(name, args)
    res = ci.cmd_bakim_is(mcp_fn=lambda: StaleMCP(RECS),
                          llm_fn=lambda *a, **kw: {"islemler": [{"tur": "celiski", "eski": "R1", "yeni": "R2", "neden": "a"}]})
    assert res["uygulanan"] == 0
    assert "UYGULANMADI" in (Path(ci.BAKIM_DIR) / "bakim.log").read_text()
