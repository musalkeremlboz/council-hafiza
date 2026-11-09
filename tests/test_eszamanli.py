"""Yerel sürümde MCP sunucusu ve kâtip aynı veritabanına ayrı süreçlerden yazar: kayıt numaraları çakışmamalı,
günlük zinciri bozulmamalı."""
import multiprocessing as mp
import os

from council_hafiza.store import Actor, Store


def _yazar(yol: str, arac: str, n: int) -> None:
    st = Store(yol, anahtar="")
    a = Actor(tool=arac, project="genel", client_id=None)
    for i in range(n):
        st.add_record(a, {"text": f"{arac} kaydı {i}", "kind": "fact", "visibility": "shared", "trust": "agent"})
        if i % 10 == 0:
            st.set_identity(a, f"{arac} amacı {i}", "proje")


def test_iki_surec_ayni_anda_yazar(tmp_path):
    yol = str(tmp_path / "h.sqlite")
    Store(yol, anahtar="")                       # şema bir kez kurulsun
    ctx = mp.get_context("spawn")                # Windows'taki gibi
    ps = [ctx.Process(target=_yazar, args=(yol, ad, 400)) for ad in ("claude-code", "katip")]
    for p in ps:
        p.start()
    for p in ps:
        p.join(120)
        assert p.exitcode == 0
    st = Store(yol, anahtar="")
    ids = [r["id"] for r in st.q("SELECT id FROM records")]
    assert len(ids) == 800 and len(set(ids)) == 800
    assert st.verify_chain()
