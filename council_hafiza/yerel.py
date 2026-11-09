"""COUNCIL yerel (klasör) sürümü: hafıza tek bir klasörde, sunucusuz, tek kullanıcı.

Klasör düzeni (kurucu `kur.py` oluşturur):
  <klasör>/CLAUDE.md                 hafıza kuralları (yönetilen bölüm işaretler arasında; kullanıcı metni korunur)
  <klasör>/.mcp.json                 "council" MCP sunucusu (stdio) → python -m council_hafiza.yerel sunucu
  <klasör>/.claude/settings.json     SessionStart → ozet, Stop/PreCompact/SessionEnd → katip-hook
  <klasör>/.claude/settings.local.json  "council" sunucusunun onayı (enabledMcpjsonServers)
  <veri>/venv/                       Python ortamı (bu paket burada kurulu)
  <veri>/hafiza.sqlite               hafıza (kayıtlar silinmez; değişiklik günlüğü hash zinciriyle)
  <veri>/yedek/                      günlük yerel yedek (14 gün) ve güncelleme öncesi yedekler
  <veri>/ayar.json, surum.json, klasor.json
<veri> normalde <klasör>/.council'dir. Klasör OneDrive/Dropbox/iCloud gibi eşitlenen bir yerdeyse canlı veritabanı
(SQLite WAL) ve Python ortamı eşitlemeye girmesin diye kullanıcının yerel uygulama verisine konur
(Windows: %LOCALAPPDATA%\COUNCIL\<ad>-<özet>); yeri <klasör>/.council/konum.json'da yazılıdır.

Komutlar (klasördeki venv'in python'u ile): python -m council_hafiza.yerel <komut>
  sunucu      MCP sunucusu (stdio)               ozet        SessionStart hook'u
  katip-hook  Stop/PreCompact/SessionEnd hook'u  katip-is    arka plan kâtip işi (hook başlatır)
  bakim-is    arka plan bakım işi                 katip-durum kâtip günlüğünün sonu
  doktor      sağlık kontrolü (--json)           yedekle     yerel yedek al
  vektor-doldur  anlamsal arama açıkken vektörü eksik kayıtları doldur
  kaydet "metin" / ara "soru" / kimlik "amaç" / ozet-goster   kurulum sırasında (MCP araçları henüz yokken)

Kâtip ve bakım, uzak sürümle aynı kodu (istemci.py) kullanır; HTTP yerine sunucu araçlarını süreç içinde çağırır.
Model çağrıları kullanıcının kendi `claude` kurulumu ve aboneliğiyle yapılır.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

try:
    from importlib.metadata import version as _v
    SURUM = _v("council-hafiza")
except Exception:                 # kaynak klasöründen çalışırken
    SURUM = "0.0.0"
ARAC = "claude-code"          # ana oturumdaki kayıtlar bu araç adıyla yazılır
PROJE = "genel"               # yerel sürümde tek proje: klasör tek kişinin hafızası
YEDEK_GUN = 14


# ---------------------------------------------------------------- klasör ve ortam
def klasor_bul(argv: list[str] | None = None) -> Path:
    argv = argv or []
    if "--klasor" in argv:
        i = argv.index("--klasor")
        if i + 1 < len(argv):
            return Path(argv[i + 1]).resolve()
    if os.environ.get("COUNCIL_KLASOR"):
        return Path(os.environ["COUNCIL_KLASOR"]).resolve()
    venv = Path(sys.prefix).resolve()                 # <veri>/venv
    try:
        return Path(json.loads((venv.parent / "klasor.json").read_text(encoding="utf-8-sig"))["klasor"]).resolve()
    except Exception:
        pass
    if venv.parent.name == ".council":
        return venv.parent.parent
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        return Path(os.environ["CLAUDE_PROJECT_DIR"]).resolve()
    raise SystemExit("COUNCIL klasörü bulunamadı (--klasor verin)")


def veri_dir(k: Path) -> Path:
    """Canlı verinin yeri: <klasör>/.council ya da konum.json'da yazan yer (eşitlenen klasörler için)."""
    try:
        v = json.loads((k / ".council" / "konum.json").read_text(encoding="utf-8-sig")).get("veri")
        if v and v != ".":
            return Path(v)
    except Exception:
        pass
    return k / ".council"


def ayar_oku(k: Path) -> dict:
    try:
        return json.loads((veri_dir(k) / "ayar.json").read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


VEKTOR_MODEL = "BAAI/bge-m3"
DOLDUR_ARALIK = 300            # sn: MCP sunucusu vektörü eksik kayıtları bu aralıkla doldurur


def ortam_kur(k: Path, arac: str = ARAC, vektor_sureci: bool = False) -> None:
    """Sunucu modülü içe aktarılmadan ÖNCE çağrılmalı (veritabanı yolu modül yüklenirken okunur).
    Anlamsal arama açıksa modeli (2-3 GB bellek) yalnız MCP sunucusu yükler; hook, kâtip ve bakım süreçleri vektörsüz
    yazar, eksik vektörleri sunucu arka planda doldurur."""
    d = veri_dir(k)
    d.mkdir(parents=True, exist_ok=True)
    os.environ["COUNCIL_DB"] = str(d / "hafiza.sqlite")
    os.environ.pop("COUNCIL_BASE_URL", None)            # kimlik doğrulama yok: yalnız bu kullanıcı, stdio
    os.environ.pop("COUNCIL_DB_ANAHTAR_DOSYASI", None)
    os.environ["COUNCIL_TOOL"] = arac
    vektor = bool(ayar_oku(k).get("vektor"))
    os.environ["COUNCIL_EMBED"] = "bge-m3" if (vektor and vektor_sureci) else "none"
    if vektor:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")          # model kurulumda indirildi; çalışırken ağa çıkma
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ["COUNCIL_KATIP_DIR"] = str(d / "katip")
    os.environ["COUNCIL_BAKIM_DIR"] = str(d / "bakim")
    os.environ["COUNCIL_KLASOR"] = str(k)
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


class YerelMCP:
    """Uzak sürümdeki MCP istemcisinin (istemci.MCP) yerine: aynı `call(ad, argümanlar) -> metin` arayüzü,
    araçlar süreç içinde çalışır. Her çağrı kendi araç adıyla (katip, bakim, claude-code) yazılır."""

    def __init__(self, arac: str):
        self.arac = arac

    def call(self, name: str, args: dict) -> str:
        os.environ["COUNCIL_TOOL"] = self.arac
        from fastmcp import Client

        from .server import mcp

        async def _c() -> str:
            async with Client(mcp) as c:
                r = await c.call_tool(name, args, raise_on_error=False)
                text = "\n".join(getattr(x, "text", "") for x in (r.content or [])).strip()
                if r.is_error:
                    raise RuntimeError(f"{name}: {text[:300]}")
                return text

        return asyncio.run(_c())


def _istemci(k: Path):
    """Kâtip/bakım/özet kodu (uzak sürümle ortak) yerel ayarlarla."""
    from . import istemci as ci
    ci.YEREL = True
    ci.ALT_KOMUT = [sys.executable, "-X", "utf8", "-P", "-m", "council_hafiza.yerel"]
    ci.OZET_MCP = lambda: YerelMCP(ARAC)
    ci.SERVER_NAME = "council"
    ci.STATE_DIR = str(veri_dir(k) / "katip")
    ci.BAKIM_DIR = str(veri_dir(k) / "bakim")
    ci.proje_adi = lambda cwd: PROJE      # tek klasör = tek kişinin hafızası: hepsi tek projede
    return ci


# ---------------------------------------------------------------- anlamsal arama
def vektor_doldur(sinir: int = 64) -> int:
    """Vektörü eksik (ya da başka modelle hesaplanmış) güncel kayıtları doldurur. Sunucu süreci içinde çağrılır."""
    from . import search
    from .server import STORE
    if not search.embed_enabled():
        return 0
    rows = [dict(r) for r in STORE.q("SELECT id, text, context, keys FROM records WHERE archived=0 AND "
                                     "(embedding IS NULL OR COALESCE(emb_model,'') NOT IN (?, '')) LIMIT ?",
                                     (search.EMBED_MODEL, sinir))]
    if not rows:
        return 0
    vecs = search.embed([search.doc_text(r) for r in rows])
    for r, v in zip(rows, vecs):
        STORE.set_embedding(r["id"], v.tobytes(), search.EMBED_MODEL)
    return len(rows)


def _doldur_dongu() -> None:
    import threading

    def is_():
        time.sleep(20)
        while True:
            try:
                while vektor_doldur() > 0:
                    pass
            except Exception:
                pass
            time.sleep(DOLDUR_ARALIK)

    threading.Thread(target=is_, name="vektor-doldur", daemon=True).start()


def model_hazir() -> tuple[bool, str]:
    try:                       # kurulum ONNX kopyasını bilerek indirmez; yalnız kullanılan dosyalar aranır
        from huggingface_hub import try_to_load_from_cache
        gerekli = ["config.json", "modules.json", "tokenizer.json", "sentencepiece.bpe.model", "pytorch_model.bin"]
        eksik = [f for f in gerekli if not isinstance(try_to_load_from_cache(VEKTOR_MODEL, f), str)]
        return (not eksik), ("hazır" if not eksik else "eksik: " + ", ".join(eksik))
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}"


# ---------------------------------------------------------------- yedek
def yedekle(k: Path, ad: str | None = None) -> Path | None:
    db = veri_dir(k) / "hafiza.sqlite"
    if not db.exists():
        return None
    from .store import Store
    hedef_dir = veri_dir(k) / "yedek"
    hedef_dir.mkdir(parents=True, exist_ok=True)
    hedef = hedef_dir / (ad or f"hafiza-{time.strftime('%Y-%m-%d')}.sqlite")
    Store(db, anahtar="").yedekle(hedef)
    simdi = time.time()
    for p in hedef_dir.glob("hafiza-*.sqlite"):          # yalnız günlük yedekler temizlenir; güncelleme öncesi yedekler kalır
        if simdi - p.stat().st_mtime > YEDEK_GUN * 86400:
            p.unlink(missing_ok=True)
    return hedef


def _gunluk_yedek(k: Path) -> None:
    hedef = veri_dir(k) / "yedek" / f"hafiza-{time.strftime('%Y-%m-%d')}.sqlite"
    if not hedef.exists():
        yedekle(k)


# ---------------------------------------------------------------- doktor
def doktor(k: Path) -> dict:
    """Kurulumun sağlık kontrolü. Her madde: (ad, tamam mı, açıklama)."""
    d = veri_dir(k)
    out: list[tuple[str, bool, str]] = []

    def ekle(ad: str, ok: bool, aciklama: str = "") -> None:
        out.append((ad, bool(ok), aciklama))

    ekle("python", sys.version_info >= (3, 11), sys.version.split()[0])
    try:
        sj = json.loads((d / "surum.json").read_text(encoding="utf-8-sig"))
        ekle("surum", sj.get("surum") == SURUM, f"kurulu {sj.get('surum')}, paket {SURUM}")
    except Exception:
        ekle("surum", False, ".council/surum.json yok")
    db = d / "hafiza.sqlite"
    try:
        from .store import Store
        st = Store(db, anahtar="")
        ic = st.q("PRAGMA integrity_check")[0][0]
        n = st.q("SELECT COUNT(*) AS n FROM records")[0]["n"]
        ekle("veritabani", ic == "ok", f"{n} kayıt, bütünlük {ic}")
        ekle("zincir", st.verify_chain(), "değişiklik günlüğü hash zinciri")
    except Exception as e:
        ekle("veritabani", False, str(e)[:200])
    try:
        mcp_cfg = json.loads((k / ".mcp.json").read_text(encoding="utf-8-sig"))
        srv = mcp_cfg.get("mcpServers", {}).get("council", {})
        cmd_yol = Path(srv.get("command", ""))
        ok = bool(srv.get("command")) and cmd_yol.exists()
        burada = ok and _icinde(cmd_yol, d / "venv")
        ekle("mcp_tanimi", ok and burada, srv.get("command", ".mcp.json'da council yok") if (not ok or burada) else
             f"başka bir klasörün ortamını gösteriyor ({cmd_yol}); klasör kopyalanmış/taşınmış: kur.py'yi burada çalıştırın")
    except Exception as e:
        ekle("mcp_tanimi", False, f".mcp.json okunamadı: {str(e)[:100]}")
    try:
        sett = json.loads((k / ".claude" / "settings.json").read_text(encoding="utf-8-sig"))
        hooks = sett.get("hooks", {})
        gerekli = ["SessionStart", "Stop", "PreCompact", "SessionEnd"]
        eksik = [h for h in gerekli if not any("council_hafiza.yerel" in json.dumps(g) for g in hooks.get(h, []))]
        ekle("hooklar", not eksik, "eksik: " + ", ".join(eksik) if eksik else "4 hook tanımlı")
    except Exception as e:
        ekle("hooklar", False, f".claude/settings.json okunamadı: {str(e)[:100]}")
    try:
        loc = json.loads((k / ".claude" / "settings.local.json").read_text(encoding="utf-8-sig"))
        onay = "council" in (loc.get("enabledMcpjsonServers") or []) or loc.get("enableAllProjectMcpServers") is True
        red = "council" in (loc.get("disabledMcpjsonServers") or [])
        ekle("mcp_onay", onay and not red, "reddedilmiş: Claude Code'da /mcp ile council'i etkinleştirin" if red else (
             "onaylı" if onay else "onaylı değil: ilk oturumda Claude Code soracak"))
        if red:
            out.append(("mcp_red", False, "council sunucusu kapalı"))
    except Exception:
        ekle("mcp_onay", False, "settings.local.json yok: ilk oturumda Claude Code soracak")
    ekle("veri_yeri", True, str(d))
    try:
        kayitli = json.loads((d / "klasor.json").read_text(encoding="utf-8-sig")).get("klasor")
        ekle("klasor_eslesme", bool(kayitli) and Path(kayitli).resolve() == k.resolve(),
             "tamam" if kayitli and Path(kayitli).resolve() == k.resolve() else
             f"veri başka klasöre ait ({kayitli}); kur.py'yi bu klasörde çalıştırın")
    except Exception:
        ekle("klasor_eslesme", False, "klasor.json yok: kur.py'yi bu klasörde çalıştırın")
    try:
        md = (k / "CLAUDE.md").read_text(encoding="utf-8-sig")
        ekle("claude_md", "<!-- council:basla -->" in md and "<!-- council:bitir -->" in md, "hafıza kuralları bölümü")
    except Exception:
        ekle("claude_md", False, "CLAUDE.md yok")
    try:                                                   # MCP sunucusu gerçekten açılıyor ve araçlarını veriyor mu
        from fastmcp import Client
        from fastmcp.client.transports import StdioTransport
        mcp_cfg = json.loads((k / ".mcp.json").read_text(encoding="utf-8-sig"))["mcpServers"]["council"]

        async def _l():
            tr = StdioTransport(command=mcp_cfg["command"], args=mcp_cfg.get("args", []),
                                env={**os.environ, **mcp_cfg.get("env", {})}, cwd=str(k))
            async with Client(tr) as c:
                return sorted(t.name for t in await c.list_tools())

        araclar = asyncio.run(asyncio.wait_for(_l(), 60))
        ekle("mcp_sunucu", {"hafiza_ara", "hafiza_kaydet", "hafiza_ozet"} <= set(araclar), f"{len(araclar)} araç")
    except Exception as e:
        ekle("mcp_sunucu", False, f"açılmadı: {type(e).__name__}: {str(e)[:150]}")
    try:
        ci = _istemci(k)
        ekle("claude", True, " ".join(ci.claude_komutu()))
    except Exception as e:
        ekle("claude", False, f"{str(e)[:150]} (kâtip ve bakım çalışmaz; hafıza yine çalışır)")
    if ayar_oku(k).get("vektor"):
        ok, ac = model_hazir()
        ekle("vektor_modeli", ok, (f"{VEKTOR_MODEL} hazır" if ok else f"{VEKTOR_MODEL} yok ({ac}); kur.py'yi yeniden çalıştırın"))
        try:
            from .store import Store
            st = Store(db, anahtar="")
            eksik = st.q("SELECT COUNT(*) AS n FROM records WHERE archived=0 AND embedding IS NULL")[0]["n"]
            ekle("vektorler", True, f"vektörü eksik kayıt: {eksik} (sunucu arka planda doldurur)")
        except Exception:
            pass
    else:
        ekle("anlamsal_arama", True, "kapalı (yalnız kelime araması)")
    yedekler = sorted((d / "yedek").glob("*.sqlite")) if (d / "yedek").exists() else []
    ekle("yedek", True, f"{len(yedekler)} yedek" + (f", son: {yedekler[-1].name}" if yedekler else ""))
    zorunlu = {"python", "surum", "veritabani", "zincir", "mcp_tanimi", "hooklar", "claude_md", "mcp_sunucu", "mcp_red",
               "klasor_eslesme", "vektor_modeli"}
    return {"klasor": str(k), "surum": SURUM, "tamam": all(ok for ad, ok, _ in out if ad in zorunlu),
            "maddeler": [{"ad": a, "tamam": ok, "aciklama": x} for a, ok, x in out]}


def _icinde(yol: Path, kok: Path) -> bool:
    try:                       # venv/bin/python bir sembolik bağ: kendisi değil klasörü çözülür
        yol.parent.resolve().relative_to(kok.resolve())
        return True
    except (ValueError, OSError):
        return False


def _kopya_mi(k: Path) -> bool:
    """Hook'u çalıştıran oturumun klasörü bu kurulumun klasörü değilse (klasör kopyalanmış): başka klasörün verisine yazma."""
    p = os.environ.get("CLAUDE_PROJECT_DIR")
    if not p:
        return False
    try:
        return Path(p).resolve() != k.resolve()
    except OSError:
        return False


def _yaz_doktor(r: dict) -> None:
    for m in r["maddeler"]:
        print(f"[{'TAMAM' if m['tamam'] else 'SORUN'}] {m['ad']}: {m['aciklama']}")
    print("SONUÇ:", "kurulum sağlıklı" if r["tamam"] else "sorun var")


# ---------------------------------------------------------------- giriş
def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.reconfigure(encoding="utf-8")
        except Exception:
            pass
    os.umask(0o077)                                  # hafıza, yedek, günlük yalnız bu kullanıcıya açık
    cmd = argv[0] if argv else ""
    k = klasor_bul(argv[1:])
    arac = {"katip-is": "katip", "bakim-is": "bakim"}.get(cmd, ARAC)
    ortam_kur(k, arac, vektor_sureci=cmd in ("sunucu", "vektor-doldur"))
    if cmd == "sunucu":
        from .server import mcp
        if os.environ.get("COUNCIL_EMBED") != "none":
            _doldur_dongu()
        mcp.run(transport="stdio", show_banner=False)
    elif cmd == "vektor-doldur":
        n = toplam = 0
        while True:
            n = vektor_doldur()
            toplam += n
            if not n:
                break
        print(f"vektörü doldurulan kayıt: {toplam}")
    elif cmd in ("ozet", "katip-hook", "katip-durum"):
        ci = _istemci(k)
        try:
            if cmd == "ozet" and _kopya_mi(k):
                ctx = (f"COUNCIL UYARISI: Bu klasörün hafıza ayarları başka bir klasöre ({k}) ait; klasör kopyalanmış ya da "
                       "taşınmış. Hafıza araçlarını kullanma ve kullanıcıya kurulumu bu klasörde yenilemesini söyle "
                       "(kur.md'deki adımlar). Kâtip bu oturumda kayıt yazmaz.")
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}}), flush=True)
            elif cmd == "ozet":
                try:
                    _gunluk_yedek(k)
                except Exception as e:
                    ci.log(f"yedek alınamadı: {str(e)[:200]}")
                ci.cmd_ozet()
            elif cmd == "katip-hook":
                if not _kopya_mi(k):
                    ci.cmd_katip_hook()
            else:
                ci.cmd_katip_durum()
        except Exception as e:                       # hook'lar oturumu asla engellemez
            ci.log(f"beklenmeyen hata ({cmd}): {str(e)[:300]}")
    elif cmd == "katip-is" and len(argv) >= 5:
        ci = _istemci(k)
        try:
            ci.cmd_katip_is(*argv[1:5], mcp_fn=lambda: YerelMCP("katip"))
        except Exception as e:
            ci.log(f"beklenmeyen hata (katip-is): {str(e)[:300]}")
    elif cmd == "bakim-is":
        ci = _istemci(k)
        try:
            res = ci.cmd_bakim_is(kuru="--kuru" in argv, zorla="--zorla" in argv, mcp_fn=lambda: YerelMCP("bakim"))
            if "--kuru" in argv:
                print(json.dumps(res, ensure_ascii=False, indent=1))
        except Exception as e:
            ci.log(f"beklenmeyen hata (bakim-is): {str(e)[:300]}")
    elif cmd == "doktor":
        r = doktor(k)
        print(json.dumps(r, ensure_ascii=False, indent=1)) if "--json" in argv else _yaz_doktor(r)
        sys.exit(0 if r["tamam"] else 1)
    elif cmd == "yedekle":
        p = yedekle(k, f"elle-{time.strftime('%Y%m%d-%H%M%S')}.sqlite")
        print(f"yedek: {p}" if p else "veritabanı yok")
    elif cmd == "kaydet" and len(argv) >= 2:
        print(YerelMCP(ARAC).call("hafiza_kaydet", {"metin": argv[1], "guven": "user", "proje": _proje(k)}))
    elif cmd == "kimlik" and len(argv) >= 2:
        print(YerelMCP(ARAC).call("kimlik_tanimla", {"amac": argv[1], "proje": _proje(k)}))
    elif cmd == "ozet-goster":
        print(YerelMCP(ARAC).call("hafiza_ozet", {"proje": _proje(k)}))
    elif cmd == "ara" and len(argv) >= 2:
        print(YerelMCP(ARAC).call("hafiza_ara", {"soru": argv[1], "proje": _proje(k)}))
    else:
        print(__doc__)


def _proje(k: Path) -> str:
    return PROJE


if __name__ == "__main__":
    main()
