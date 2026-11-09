"""Yönetim komutları.

  council-hafiza sunucu                      # MCP sunucusunu başlat (ortam değişkenleri: server.py)
  council-hafiza parola-ayarla               # yönetici parolası sor, scrypt özetini yaz (COUNCIL_ADMIN_HASH için)
  council-hafiza token-olustur claude-code [etiket] [--projeler a,b]   # statik token üret (bir kez gösterilir)
  council-hafiza token-kapsam hermes genel,hermes   # aracın token'larını projelerle sınırla ('*' = hepsi)
  council-hafiza istemci-kapsam claude-chat '*'    # OAuth istemcisinin (claude.ai) projelerini açıkça tanımla
  council-hafiza tokenlar                    # statik token listesi (değerler değil)
  council-hafiza disa-aktar ./ayna           # bütün kayıtları okunabilir Markdown olarak dışa aktar
  council-hafiza zincir                      # denetim günlüğünün hash zincirini doğrula
  council-hafiza denetle [--cikti DIR]       # denetim ajanı: sunucu, hafıza, Hermes, Mac raporu → DIR/son.json (root ile)
  council-hafiza yedekle hedef.sqlite        # tutarlı yedek (şifreli veritabanında aynı anahtarla şifreli)
  council-hafiza sifrele duz.sqlite sifreli.sqlite   # şifresiz veritabanını COUNCIL_DB_ANAHTAR_DOSYASI anahtarıyla şifreli kopyala
"""
from __future__ import annotations

import getpass
import json
import os
import sys
import time
from pathlib import Path


def _store():
    from .store import Store
    return Store(os.environ.get("COUNCIL_DB", str(Path.cwd() / "veri" / "council.sqlite")))


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "yardim"
    if cmd == "sunucu":
        from .server import main as run
        run()
    elif cmd == "parola-ayarla":
        from .auth import hash_password
        p1 = getpass.getpass("Yeni yönetici parolası (en az 12 karakter): ")
        p2 = getpass.getpass("Tekrar: ")
        if p1 != p2 or len(p1) < 12:
            sys.exit("Parolalar eşleşmiyor ya da 12 karakterden kısa.")
        print(hash_password(p1))
    elif cmd == "token-olustur":
        if len(argv) < 2:
            sys.exit("Kullanım: council-hafiza token-olustur <arac-adi> [etiket]")
        from .auth import new_static_token
        rest, projeler = argv[2:], "*"
        if "--projeler" in rest:
            i = rest.index("--projeler"); projeler = rest[i + 1]; rest = rest[:i] + rest[i + 2:]
        print(new_static_token(_store(), argv[1], " ".join(rest), projeler))
    elif cmd == "istemci-kapsam":
        if len(argv) < 3:
            sys.exit("Kullanım: council-hafiza istemci-kapsam <arac> <proje1,proje2|*>")
        s = _store()
        s.x("INSERT INTO istemci_kapsam VALUES (?,?,?) ON CONFLICT(tool) DO UPDATE SET projeler=excluded.projeler, ts=excluded.ts",
            (argv[1], argv[2], time.time()))
        s.log(None, "istemci_kapsam", None, {"arac": argv[1], "projeler": argv[2]})
        print(f"{argv[1]} (OAuth) → projeler {argv[2]}")
    elif cmd == "token-kapsam":
        if len(argv) < 3:
            sys.exit("Kullanım: council-hafiza token-kapsam <arac> <proje1,proje2|*>")
        s = _store()
        n = s.q("SELECT COUNT(*) AS n FROM static_tokens WHERE tool=?", (argv[1],))[0]["n"]
        if not n:
            sys.exit(f"{argv[1]} için token yok.")
        s.x("UPDATE static_tokens SET projeler=? WHERE tool=?", (argv[2], argv[1]))
        s.log(None, "token_kapsam", None, {"arac": argv[1], "projeler": argv[2]})
        print(f"{argv[1]}: {n} token → projeler {argv[2]}")
    elif cmd == "tokenlar":
        for r in _store().q("SELECT tool, label, created_at, projeler FROM static_tokens ORDER BY created_at"):
            print(f"{r['tool']:20s} {time.strftime('%Y-%m-%d %H:%M', time.localtime(r['created_at']))}  projeler={r['projeler']}  {r['label'] or ''}")
    elif cmd == "token-sil":
        s = _store()
        s.x("DELETE FROM static_tokens WHERE tool=?", (argv[1],))
        s.log(None, "token_sil", None, {"arac": argv[1]})
        print("silindi:", argv[1])
    elif cmd == "disa-aktar":
        out = Path(argv[1] if len(argv) > 1 else "ayna")
        s = _store()
        rows = [dict(r) for r in s.q("SELECT * FROM records ORDER BY project, created_at")]
        by: dict[str, list[dict]] = {}
        for r in rows:
            by.setdefault(r["project"], []).append(r)
        out.mkdir(parents=True, exist_ok=True)
        for proj, rs in by.items():
            lines = [f"# {proj}", ""]
            for r in rs:
                st = "arşiv" if r["archived"] else ("eski → " + r["superseded_by"] if r["superseded_by"] else ("geçersiz" if r["valid_to"] else "güncel"))
                lines.append(f"- **{r['id']}** ({r['valid_from']}, {r['tool']}, {r['kind']}, {r['visibility']}, {r['trust']}, {st}): {r['text']}")
            (out / f"{proj}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{len(rows)} kayıt → {out}/")
    elif cmd == "denetle":
        from .denetim import calistir
        from .store import anahtar_oku, sifreli_mi
        opt = dict(zip(argv[1::2], argv[2::2]))
        src = Path("/opt/council-hafiza/src")
        if not (src / "deploy" / "sistem.json").exists():
            src = Path(__file__).resolve().parents[1]
        db = os.environ.get("COUNCIL_DB", "/var/lib/council-hafiza/council.sqlite")
        if os.path.exists(db) and sifreli_mi(db) and not anahtar_oku():
            sys.exit("Veritabanı şifreli ama COUNCIL_DB_ANAHTAR_DOSYASI tanımlı değil. Elle çalıştırmak için: systemctl start council-denetim")
        base = os.environ.get("COUNCIL_BASE_URL", "https://localhost")
        rapor = calistir(Path(opt.get("--cikti", "/var/lib/council-denetim")),
                         Path(opt.get("--envanter", src / "deploy" / "sistem.json")),
                         base.split("//", 1)[-1].split("/")[0], Path(opt.get("--istemci", src / "istemci" / "council_istemci.py")))
        print(json.dumps(rapor["ozet"], ensure_ascii=False), f"({rapor['sure_sn']} sn)")
    elif cmd == "yedekle":
        _store().yedekle(argv[1])
        print("yedek:", argv[1])
    elif cmd == "sifrele":
        from .store import anahtar_oku, baglan, sifreli_mi
        k = anahtar_oku()
        if not k:
            sys.exit("COUNCIL_DB_ANAHTAR_DOSYASI tanımlı değil.")
        if sifreli_mi(argv[1]):
            sys.exit(f"{argv[1]} zaten şifreli.")
        hedef = Path(argv[2])
        if hedef.exists():
            sys.exit(f"{hedef} zaten var.")
        import sqlcipher3.dbapi2 as drv
        db = drv.connect(argv[1])
        db.execute(f"ATTACH DATABASE '{str(hedef).replace(chr(39), chr(39) * 2)}' AS s KEY \"x'{k}'\"")
        db.execute("SELECT sqlcipher_export('s')")
        db.execute("DETACH DATABASE s")
        db.close()
        os.chmod(hedef, 0o600)
        a = baglan(argv[1], None).execute("SELECT (SELECT count(*) FROM records), (SELECT count(*) FROM events)").fetchone()
        b = baglan(hedef, k).execute("SELECT (SELECT count(*) FROM records), (SELECT count(*) FROM events)").fetchone()
        if tuple(a) != tuple(b):
            hedef.unlink()
            sys.exit(f"Doğrulama başarısız: {tuple(a)} != {tuple(b)}")
        print(f"şifrelendi: {tuple(b)[0]} kayıt, {tuple(b)[1]} olay → {hedef}")
    elif cmd == "zincir":
        print("zincir sağlam" if _store().verify_chain() else "ZİNCİR BOZUK")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
