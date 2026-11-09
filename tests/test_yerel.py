"""Yerel (klasör) sürüm: kurucunun yapılandırma birleştirmesi ve süreç içi MCP."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("kur", ROOT / "kur.py")
kur = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kur)


def test_kullanici_ayarlari_korunur(tmp_path):
    k = tmp_path / "Beynim"
    (k / ".claude").mkdir(parents=True)
    (k / "CLAUDE.md").write_text("# Benim kurallarım\nKısa cevap ver.\n", encoding="utf-8")
    (k / ".mcp.json").write_text(json.dumps({"mcpServers": {"baska": {"command": "x"}}}), encoding="utf-8")
    kendi = {"hooks": [{"type": "command", "command": "echo benim"}]}
    (k / ".claude" / "settings.json").write_text(json.dumps({"model": "opus", "hooks": {"Stop": [kendi]}}), encoding="utf-8")
    for _ in range(2):                                      # iki kez: ikinci çalıştırma tekrar eklememeli
        kur.claude_md_guncelle(k, plan=False)
        kur.mcp_json_guncelle(k, plan=False)
        kur.hooklar_guncelle(k, plan=False)
        kur.mcp_onayla(k, plan=False)
    md = (k / "CLAUDE.md").read_text(encoding="utf-8")
    assert md.startswith("# Benim kurallarım\nKısa cevap ver.") and md.count(kur.BASLA) == 1
    mcp = json.loads((k / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert set(mcp) == {"baska", "council"} and mcp["council"]["args"][-1] == "sunucu"
    st = json.loads((k / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert st["model"] == "opus"
    assert st["hooks"]["Stop"][0] == kendi and len(st["hooks"]["Stop"]) == 2      # kullanıcının hook'u yerinde, bizimki bir kez
    for olay in kur.OLAYLAR:
        ours = [g for g in st["hooks"][olay] if kur.HOOK_IMI in json.dumps(g)]
        assert len(ours) == 1
        h = ours[0]["hooks"][0]
        assert h["args"][:2] == ["-X", "utf8"] and h["timeout"] >= 20     # exec biçimi: kabuksuz
    loc = json.loads((k / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert loc["enabledMcpjsonServers"] == ["council"]


def test_reddedilmis_sunucu_onaylanmaz(tmp_path):
    k = tmp_path / "B"
    (k / ".claude").mkdir(parents=True)
    (k / ".claude" / "settings.local.json").write_text(json.dumps({"disabledMcpjsonServers": ["council"]}), encoding="utf-8")
    assert "reddedilmiş" in kur.mcp_onayla(k, plan=False)
    assert "enabledMcpjsonServers" not in json.loads((k / ".claude" / "settings.local.json").read_text(encoding="utf-8"))


def test_bozuk_json_durdurur(tmp_path):
    k = tmp_path / "B"
    k.mkdir()
    (k / ".mcp.json").write_text("{bozuk", encoding="utf-8")
    with pytest.raises(SystemExit):
        kur.mcp_json_guncelle(k, plan=False)
    assert (k / ".mcp.json").read_text(encoding="utf-8") == "{bozuk"      # dosyaya dokunulmadı


@pytest.mark.parametrize("yol,beklenen", [
    ("C:/Users/ali/OneDrive/Belgeler/Beynim", True), ("C:/Users/ali/OneDrive - Şirket/Beynim", True),
    ("/Users/ali/Library/Mobile Documents/com~apple~CloudDocs/Beynim", True), ("/Users/ali/Dropbox/Beynim", True),
    ("C:/Users/ali/Belgeler/Beynim", False), ("/Users/ali/Beynim", False)])
def test_senkron_klasor(yol, beklenen, monkeypatch):
    for v in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(v, raising=False)
    assert kur.senkron_mu(Path(yol)) is beklenen


def test_plan_hicbir_seyi_degistirmez(tmp_path):
    k = tmp_path / "B"
    k.mkdir()
    (k / "not.md").write_text("notum", encoding="utf-8")
    assert kur.main(["--klasor", str(k), "--paket", str(ROOT), "--plan"]) == 0
    assert sorted(p.name for p in k.iterdir()) == ["not.md"]


def test_ev_klasorune_kurulmaz():
    assert kur.main(["--klasor", str(Path.home()), "--paket", str(ROOT), "--plan"]) == 2


def test_surec_ici_mcp_ve_proje(tmp_path):
    """yerel modülü ayrı bir süreçte: kaydet → ara, tek proje (genel), araç adı claude-code."""
    k = tmp_path / "Kardeş Beyni"
    k.mkdir()
    env = {**os.environ, "COUNCIL_KLASOR": str(k), "PYTHONUTF8": "1"}
    env.pop("COUNCIL_BASE_URL", None)
    r1 = subprocess.run([sys.executable, "-m", "council_hafiza.yerel", "kaydet", "En sevdiğim renk mavi."], env=env,
                        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=120)
    assert "Kaydedildi: R00001 (claude-code/genel)" in r1.stdout, r1.stderr
    r2 = subprocess.run([sys.executable, "-m", "council_hafiza.yerel", "ara", "renk"], env=env,
                        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=120)
    assert "mavi" in r2.stdout
    assert (k / ".council" / "hafiza.sqlite").exists()


def test_bozuk_isaretler_kullanici_metnine_dokunmaz(tmp_path):
    k = tmp_path / "B"
    k.mkdir()
    metin = f"# Notlarım\n{kur.BASLA}\neski\n# Kullanıcının sonradan yazdığı\n"     # bitiş işareti silinmiş
    (k / "CLAUDE.md").write_text(metin, encoding="utf-8")
    with pytest.raises(SystemExit):
        kur.claude_md_guncelle(k, plan=False)
    assert (k / "CLAUDE.md").read_text(encoding="utf-8") == metin


def test_ayni_gruptaki_kullanici_hooku_korunur(tmp_path):
    k = tmp_path / "B"
    (k / ".claude").mkdir(parents=True)
    kendi = {"type": "command", "command": "echo benim"}
    kur.hooklar_guncelle(k, plan=False)
    st = json.loads((k / ".claude" / "settings.json").read_text(encoding="utf-8"))
    st["hooks"]["Stop"][0]["hooks"].append(kendi)                  # kullanıcı bizim grubumuza kendi hook'unu ekledi
    (k / ".claude" / "settings.json").write_text(json.dumps(st), encoding="utf-8")
    kur.hooklar_guncelle(k, plan=False)
    st = json.loads((k / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hepsi = [h for g in st["hooks"]["Stop"] for h in g["hooks"]]
    assert kendi in hepsi and sum(kur.bizim_hook(h) for h in hepsi) == 1


def test_kayitli_veri_yoksa_bos_hafiza_kurulmaz(tmp_path):
    k = tmp_path / "B"
    (k / ".council").mkdir(parents=True)
    (k / ".council" / "konum.json").write_text(json.dumps({"veri": str(tmp_path / "yok")}), encoding="utf-8")
    assert kur.main(["--klasor", str(k), "--paket", str(ROOT)]) == 2
    assert not (tmp_path / "yok").exists()


def test_klasordeki_calendar_py_hooku_bozmaz(tmp_path):
    """-P: kullanıcı klasöründeki standart modül adlı dosyalar (calendar.py, email.py) içe aktarılmaz."""
    k = tmp_path / "B"
    k.mkdir()
    (k / "calendar.py").write_text("raise SystemExit('KULLANICI DOSYASI CALISTI')\n", encoding="utf-8")
    (k / "email.py").write_text("raise SystemExit('KULLANICI DOSYASI CALISTI')\n", encoding="utf-8")
    env = {**os.environ, "COUNCIL_KLASOR": str(k), "PYTHONUTF8": "1"}
    env.pop("COUNCIL_BASE_URL", None)
    r = subprocess.run([sys.executable, *kur.PY_BAYRAK, "-m", "council_hafiza.yerel", "kaydet", "deneme bilgisi"], env=env,
                       capture_output=True, text=True, encoding="utf-8", cwd=k, timeout=120)
    assert "KULLANICI DOSYASI" not in r.stdout + r.stderr and "Kaydedildi" in r.stdout, r.stderr[-500:]


def test_kopyalanmis_klasorde_ozet_uyarir(tmp_path):
    asil, kopya = tmp_path / "Asil", tmp_path / "Kopya"
    asil.mkdir(); kopya.mkdir()
    env = {**os.environ, "COUNCIL_KLASOR": str(asil), "CLAUDE_PROJECT_DIR": str(kopya), "PYTHONUTF8": "1"}
    env.pop("COUNCIL_BASE_URL", None)
    r = subprocess.run([sys.executable, "-P", "-m", "council_hafiza.yerel", "ozet"], input=b"{}", env=env,
                       capture_output=True, cwd=tmp_path, timeout=120)
    ctx = json.loads(r.stdout.decode("ascii"))["hookSpecificOutput"]["additionalContext"]
    assert "COUNCIL UYARISI" in ctx


def test_gizli_bilgi_turkce_karaktersiz():
    from council_hafiza.secrets_guard import find_secrets
    for t in ["sifrem Deneme2000", "SIFREM: Ornek.2000!", "Gmail sifresi su: abc12345", "kartın cvv 123", "pin kodum 4821"]:
        assert find_secrets(t), t
    for t in ["Bugün şifre değiştirme kuralını konuştuk", "Toplantı saat 14:30'da", "pin numaramı unuttum"]:
        assert not find_secrets(t), t
