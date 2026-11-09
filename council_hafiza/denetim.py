"""COUNCIL denetim ajanı: sunucuyu, ortak hafızayı, Hermes'i ve Mac raporunu denetler; açıkları ve çelişkileri raporlar.

Sunucuda root olarak, systemd zamanlayıcısıyla günde 3 kez çalışır (deploy/kur.sh): `council-hafiza denetle`.
Hafıza kayıtlarını değiştirmez. Rapor: /var/lib/council-denetim/son.json (+ gecmis/; root:council, 640), panel (/panel) bunu gösterir.
İsteğe bağlı model katmanı: sunucuda `claude` komutu ve oturumu varsa, güncel kayıtlar arasındaki çelişki ve eskimiş
bilgileri bakım ajanının yöntemiyle (yalnız rapor, değişiklik yok) tarar.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

CIDDIYET = ("kritik", "yuksek", "orta", "dusuk", "bilgi")


def _kos(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "komut yok"
    except subprocess.TimeoutExpired:
        return 124, "zaman aşımı"


class Rapor:
    def __init__(self):
        self.bulgular: list[dict] = []
        self.veri: dict = {}

    def bulgu(self, bid: str, ciddiyet: str, alan: str, tur: str, baslik: str, ayrinti: str = "", oneri: str = "") -> None:
        assert ciddiyet in CIDDIYET
        self.bulgular.append({"id": bid, "ciddiyet": ciddiyet, "alan": alan, "tur": tur, "baslik": baslik,
                              "ayrinti": ayrinti, "oneri": oneri})


# ------------------------------------------------------------------ sunucu
def sunucu(r: Rapor, bek: dict, host: str) -> None:
    v: dict = {}
    try:
        v["isletim"] = next((ln.split("=", 1)[1].strip('"') for ln in open("/etc/os-release") if ln.startswith("PRETTY_NAME=")), "")
    except OSError:
        v["isletim"] = ""
    try:
        v["acik_kalma_gun"] = round(float(open("/proc/uptime").read().split()[0]) / 86400, 1)
        v["yuk"] = os.getloadavg()[0]
        mem = {ln.split(":")[0]: int(ln.split()[1]) for ln in open("/proc/meminfo")}
        v["ram_mb"], v["ram_bos_mb"] = mem["MemTotal"] // 1024, mem["MemAvailable"] // 1024
    except Exception:
        pass
    du = shutil.disk_usage("/")
    v["disk_doluluk"] = round(100 * du.used / du.total)
    if v["disk_doluluk"] >= 90:
        r.bulgu("disk", "yuksek", "sunucu", "saglik", f"Disk %{v['disk_doluluk']} dolu", "", "Eski yedekleri ve günlükleri temizle.")
    elif v["disk_doluluk"] >= 80:
        r.bulgu("disk", "orta", "sunucu", "saglik", f"Disk %{v['disk_doluluk']} dolu")

    # servisler
    hizmet = {}
    for s in bek["servisler"]:
        hizmet[s] = _kos(["systemctl", "is-active", s])[1].strip()
        if hizmet[s] != "active" and _kos(["systemctl", "is-active", s + ".socket"])[1].strip() == "active":
            hizmet[s] = "active"   # Ubuntu 24.04: ssh soketle başlar, servis ilk bağlantıya kadar 'inactive' görünür
    _, out = _kos(["systemctl", "list-units", "--type=service", "--all", "--no-legend", "--plain"])
    for desen in bek.get("servis_desenleri", []):
        bul = [ln.split()[0] for ln in out.splitlines() if ln.startswith(desen)]
        if not bul:
            hizmet[desen] = "yok"
        for u in bul:
            hizmet[u.removesuffix(".service")] = _kos(["systemctl", "is-active", u])[1].strip()
    v["servisler"] = hizmet
    for s in bek.get("istenmeyen_servisler", []):
        if _kos(["systemctl", "is-active", s])[1].strip() == "active":
            r.bulgu(f"istenmeyen-{s}", "yuksek", "sunucu", "celiski", f"Envanterde olmayan web sunucusu çalışıyor: {s}",
                    "Açılışta 80/443 portunu Caddy'den önce alırsa HTTPS kapanır (8 Kasım'da sslh ile gelen Apache bunu yaptı).",
                    f"systemctl disable --now {s}")
    for s, d in hizmet.items():
        if d != "active":
            r.bulgu(f"servis-{s}", "yuksek", "sunucu", "saglik", f"Servis çalışmıyor: {s} ({d})", "", f"journalctl -u {s} ile nedenine bak.")

    # güncellemeler
    _, out = _kos(["apt", "list", "--upgradable"], 60)
    paket = [ln for ln in out.splitlines() if "/" in ln and "[upgradable" in ln]
    guv = [ln for ln in paket if "-security" in ln]
    v["guncelleme"], v["guvenlik_guncellemesi"] = len(paket), len(guv)
    if guv:
        r.bulgu("guvenlik-guncellemesi", "yuksek" if len(guv) >= 10 else "orta", "sunucu", "acik",
                f"{len(guv)} güvenlik güncellemesi bekliyor ({len(paket)} paket güncellenebilir)",
                ", ".join(ln.split("/")[0] for ln in guv[:12]), "apt upgrade ile kur (unattended-upgrades açılabilir).")
    elif paket:
        r.bulgu("guncelleme", "dusuk", "sunucu", "saglik", f"{len(paket)} paket güncellenebilir")
    v["yeniden_baslatma"] = os.path.exists("/var/run/reboot-required")
    if v["yeniden_baslatma"]:
        r.bulgu("yeniden-baslatma", "orta", "sunucu", "saglik", "Sunucu yeniden başlatma bekliyor (çekirdek ya da kütüphane güncellemesi)")
    v["otomatik_guvenlik"] = _kos(["systemctl", "is-enabled", "unattended-upgrades"])[1].strip()

    # sertifika
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection(("127.0.0.1", 443), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ss:
                bitis = ssl.cert_time_to_seconds(ss.getpeercert()["notAfter"])
        v["sertifika_gun"] = int((bitis - time.time()) // 86400)
        if v["sertifika_gun"] < 14:
            r.bulgu("sertifika", "yuksek", "sunucu", "saglik", f"HTTPS sertifikası {v['sertifika_gun']} gün sonra bitiyor", "",
                    "Caddy normalde kendisi yeniler; journalctl -u caddy'ye bak.")
    except Exception as e:
        r.bulgu("sertifika", "yuksek", "sunucu", "saglik", "HTTPS sertifikası denetlenemedi", str(e)[:200])

    # SSH
    rc, out = _kos(["sshd", "-T"])
    if rc != 0:
        r.bulgu("ssh-denetlenemedi", "yuksek", "sunucu", "saglik", "SSH ayarı denetlenemedi (sshd -T başarısız)",
                (out.strip().splitlines() or [""])[0][:200], "sshd -t ile yapılandırma hatası var mı bak.")
    else:
        cfg = dict(ln.split(None, 1) for ln in out.splitlines() if " " in ln)
        v["ssh"] = {k: cfg.get(k, "") for k in bek["ssh"]}
        es = {"without-password": "prohibit-password"}   # sshd -T eski adı yazabiliyor
        for k, w in bek["ssh"].items():
            if es.get(cfg.get(k, "").lower(), cfg.get(k, "").lower()) != w:
                r.bulgu(f"ssh-{k}", "kritik" if k == "passwordauthentication" else "yuksek", "sunucu", "acik",
                        f"SSH ayarı beklenenden farklı: {k} = {cfg.get(k)}", f"beklenen: {w}", "/etc/ssh/sshd_config.d/ altındaki ayarı düzelt.")
    rc, out = _kos(["journalctl", "-u", "ssh", "--since", "-24h", "--no-pager", "-q"], 30)
    v["ssh_basarisiz_24s"] = len(re.findall(r"Failed |Invalid user|authentication failure", out))
    if v["ssh_basarisiz_24s"] > 200 and _kos(["systemctl", "is-active", "fail2ban"])[1].strip() != "active":
        r.bulgu("ssh-saldiri", "dusuk", "sunucu", "acik", f"Son 24 saatte {v['ssh_basarisiz_24s']} başarısız SSH denemesi",
                "Parolayla giriş kapalı olduğu için tehlike düşük, ama günlükler doluyor.", "fail2ban kurulabilir.")

    # root şifresi: sızıntıdan sonra değiştirildi ya da kilitlendi mi?
    rc, out = _kos(["passwd", "-S", "root"])
    if rc == 0 and bek.get("root_sifre_sizinti"):
        parca = out.split()
        durum, tarih = (parca[1], parca[2]) if len(parca) > 2 else ("?", "")
        try:
            degisim = datetime.strptime(tarih, "%m/%d/%Y").date() if "/" in tarih else datetime.strptime(tarih, "%Y-%m-%d").date()
        except ValueError:
            degisim = None
        v["root_sifre"] = {"durum": {"P": "şifreli", "L": "kilitli", "NP": "şifresiz"}.get(durum, durum), "son_degisim": str(degisim)}
        sizinti = datetime.strptime(bek["root_sifre_sizinti"], "%Y-%m-%d").date()
        if durum == "P" and (degisim is None or degisim <= sizinti):
            r.bulgu("root-sifre", "orta", "sunucu", "acik", "Sohbette paylaşılan root şifresi hâlâ geçerli",
                    f"Son şifre değişimi: {degisim}; şifre {bek['root_sifre_sizinti']} tarihinde sohbette paylaşıldı. "
                    "Parolayla SSH kapalı, ama sağlayıcının web konsolu bu şifreyle açılıyor.",
                    "ssh <sunucu> ile girip passwd komutunu çalıştır (ya da passwd -l root ile kilitle).")
    # aynı SSH anahtarı birden çok hesapta mı?
    def _anahtarlar(yol):
        try:
            return {ln.split()[1] for ln in open(yol) if ln.strip() and not ln.startswith("#") and len(ln.split()) > 1}
        except OSError:
            return set()
    ortak = _anahtarlar("/root/.ssh/authorized_keys") & _anahtarlar("/home/hermes/.ssh/authorized_keys")
    if ortak:
        r.bulgu("ayni-ssh-anahtari", "dusuk", "sunucu", "acik", "Aynı SSH anahtarı hem root hem hermes hesabına giriş veriyor",
                "Bu anahtar ele geçerse ikisi birden açılır.", "Hermes için ayrı bir anahtar kullan.")
    # güvenlik duvarı ve dinleyen portlar
    _, out = _kos(["ufw", "status"])
    v["guvenlik_duvari"] = "aktif" if "Status: active" in out else "kapalı"
    if v["guvenlik_duvari"] != "aktif":
        r.bulgu("ufw", "yuksek", "sunucu", "acik", "Güvenlik duvarı (ufw) kapalı", "", "ufw enable (22, 80, 443 açık kalmalı).")
    _, out = _kos(["ss", "-ltnH"])
    dis = set()
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) >= 4:
            adr, _, port = parts[3].rpartition(":")
            if not (adr.startswith("127.") or adr in ("[::1]", "::1") or adr.startswith("[::ffff:127.")):
                try:
                    dis.add(int(port))
                except ValueError:
                    pass
    v["dis_portlar"] = sorted(dis)
    fazla = sorted(dis - set(bek["acik_portlar"]))
    if fazla:
        r.bulgu("port", "orta" if v["guvenlik_duvari"] == "aktif" else "yuksek", "sunucu", "celiski",
                f"Beklenmeyen dinleyen port: {', '.join(map(str, fazla))}",
                "Envanterde yalnız " + ", ".join(map(str, bek["acik_portlar"])) + " bekleniyor; güvenlik duvarı dışarıdan erişimi kesiyor olabilir.",
                "Hangi programın dinlediğine bak (ss -ltnp) ve envanteri ya da ayarı düzelt.")
    r.veri["sunucu"] = v


# ------------------------------------------------------------------ hafıza
def hafiza(r: Rapor, store, envanter: dict, data_dir: Path) -> None:
    from .secrets_guard import find_secrets
    bek = envanter["beklenen"]
    now = time.time()
    v: dict = {}
    v["zincir"] = store.verify_chain()
    if not v["zincir"]:
        r.bulgu("zincir", "kritik", "hafiza", "acik", "Değişiklik günlüğünün hash zinciri bozuk", "Günlük sonradan değiştirilmiş olabilir.",
                "council-hafiza zincir ile doğrula, yedekle karşılaştır.")
    dbp = Path(store.path)
    v["sifreli"] = open(dbp, "rb").read(15) != b"SQLite format 3"
    if not v["sifreli"]:
        r.bulgu("sifreleme", "yuksek", "hafiza", "acik", "Veritabanı diskte şifresiz", "", "kur.sh --guncelle şifreli kopyaya taşır.")
    try:
        izin = oct(os.stat(dbp).st_mode & 0o777)
        v["db_izin"] = izin
        if izin != "0o600":
            r.bulgu("db-izin", "orta", "hafiza", "acik", f"Veritabanı dosya izni geniş: {izin}", "", "chmod 600")
    except OSError:
        pass
    q = store.q
    cur = store.CURRENT
    v["kayit_guncel"] = q(f"SELECT COUNT(*) AS n FROM records WHERE {cur}")[0]["n"]
    v["kayit_toplam"] = q("SELECT COUNT(*) AS n FROM records")[0]["n"]
    v["projeye_ozel"] = q(f"SELECT COUNT(*) AS n FROM records WHERE {cur} AND visibility='project'")[0]["n"]
    v["projeler"] = {x["project"]: x["n"] for x in q(f"SELECT project, COUNT(*) AS n FROM records WHERE {cur} GROUP BY project")}
    v["olay"] = q("SELECT COUNT(*) AS n FROM events")[0]["n"]
    # gizli bilgi taraması (sunucu bekçisi yazmayı engeller; eski kayıtlar için ikinci kontrol)
    gizli = [x["id"] for x in q(f"SELECT id, text, context FROM records WHERE {cur}") if find_secrets(f"{x['text']} {x['context']}")]
    if gizli:
        r.bulgu("gizli-kayit", "kritik", "hafiza", "acik", f"{len(gizli)} güncel kayıtta gizli bilgi deseni", ", ".join(gizli[:10]),
                "Kaydı arşivle ve gizli bilgiyi değiştir (şifre/token).")
    # açık görevler
    gor = [dict(x) for x in q(f"SELECT id, text, valid_from, project, created_at FROM records WHERE {cur} AND kind='task' ORDER BY created_at")]
    v["acik_gorevler"] = [{"id": g["id"], "metin": g["text"][:200], "tarih": g["valid_from"], "proje": g["project"]} for g in gor]
    for g in gor:
        gun = (now - g["created_at"]) / 86400
        if gun > bek["gorev_eskime_gun"]:
            r.bulgu(f"gorev-{g['id']}", "dusuk", "hafiza", "celiski", f"{int(gun)} gündür açık görev: {g['id']}", g["text"][:200],
                    "Yapıldıysa hafızada kapat; yapılmadıysa sahibine hatırlat.")
    # araç etkinliği, kimlikler, token'lar
    son = {x["tool"]: x["ts"] for x in q("SELECT tool, MAX(ts) AS ts FROM events WHERE tool IS NOT NULL GROUP BY tool")}
    kimlik = {}
    for x in store.identities():
        kimlik.setdefault(x["tool"], x["purpose"])
    tokenlar = {}
    for x in q("SELECT tool, projeler, created_at FROM static_tokens ORDER BY created_at"):
        t = tokenlar.setdefault(x["tool"], {"projeler": [], "olusturma": x["created_at"], "adet": 0})
        t["adet"] += 1
        t["projeler"].append(x["projeler"])
    for t in tokenlar.values():   # token başına kapsam; panelde hepsi görünür
        t["projeler"] = " | ".join(t["projeler"])
    araclar = []
    for a in envanter["araclar"]:
        aid = a["id"]
        if aid in ("hafiza-sunucusu",):
            continue
        rec = {"id": aid, "ad": a["ad"], "cihaz": a["cihaz"], "gorev": a["gorev"], "baglanti": a["baglanti"],
               "kimlik": kimlik.get(aid), "token": tokenlar.get(aid), "son_etkinlik": son.get(aid), "ic": a.get("ic", False)}
        araclar.append(rec)
        if aid == "denetci":
            continue
        if not a.get("ic") and not kimlik.get(aid):
            r.bulgu(f"kimlik-{aid}", "dusuk", "araclar", "celiski", f"{a['ad']} için hafızada kimlik tanımı yok",
                    "Envanterde görevi var ama sunucudaki kimlik tablosunda amacı kayıtlı değil.", "Araçta kimlik_tanimla çağır.")
        if a["baglanti"].startswith("MCP · statik") and aid not in tokenlar:
            r.bulgu(f"token-{aid}", "orta", "araclar", "celiski", f"{a['ad']} için sunucuda token yok", "Envanter statik token diyor.")
        if son.get(aid) and (now - son[aid]) / 86400 > bek["arac_sessizlik_gun"]:
            r.bulgu(f"sessiz-{aid}", "bilgi", "araclar", "saglik", f"{a['ad']} {int((now - son[aid]) / 86400)} gündür hafızayı kullanmadı")
        elif not son.get(aid):
            r.bulgu(f"sessiz-{aid}", "bilgi", "araclar", "saglik", f"{a['ad']} hafızayı hiç kullanmadı")
    bilinen = {a["id"] for a in envanter["araclar"]} | {"bakim", "katip", "yerel", "web-istemci"}
    for t in tokenlar:
        if t not in bilinen:
            r.bulgu(f"token-envanter-{t}", "orta", "araclar", "celiski", f"Envanterde olmayan bir araç için token var: {t}", "",
                    "Kullanılmıyorsa council-hafiza token-sil ile kaldır; kullanılıyorsa envantere ekle.")
    # OAuth istemcileri (claude.ai vb.): proje kapsamı açıkça kararlaştırılmış mı?
    from .auth import tool_slug
    oauth = sorted({tool_slug(json.loads(x["data"]).get("client_name")) for x in q("SELECT data FROM oauth_clients")})
    v["oauth_istemciler"] = {}
    for t in oauth:
        tanimli, pr = store.istemci_kapsami(t)
        v["oauth_istemciler"][t] = ("hepsi" if pr is None else ", ".join(sorted(pr))) if tanimli else "tanımsız"
        if not tanimli:
            r.bulgu(f"oauth-kapsam-{t}", "orta", "hafiza", "acik", f"OAuth istemcisi '{t}' için proje kapsamı tanımlanmamış",
                    "Bu istemcinin bağlantısı bütün projelere açık ve proje adı istemcinin beyanına dayanıyor.",
                    f"Bilinçli karar ver: council-hafiza istemci-kapsam {t} '*' (hepsi) ya da belirli projeler.")
        else:
            for a in araclar:
                if a["id"] == t:
                    a["token"] = {"projeler": "*" if pr is None else ",".join(sorted(pr)), "adet": 0, "oauth": True}
    v["kimlik_sayisi"] = len(kimlik)
    v["yonlendirme_gozlem"] = q("SELECT COUNT(*) AS n FROM routing_obs")[0]["n"]
    if not v["yonlendirme_gozlem"]:
        r.bulgu("yonlendirme-veri", "bilgi", "hafiza", "saglik", "Model yönlendirme için henüz gözlem yok",
                "Yönlendirmenin gerçek veriyle yeniden test edilebilmesi için ana ajanların yonlendirme_bildir çağırması gerekiyor.")
    # bakım ajanının (Mac'te, Sonnet ile) son 7 günde bulup çözdüğü çelişki, tekrar ve eskimiş kayıtlar
    cozulen = []
    for x in q("SELECT action, record_id, payload, ts FROM events WHERE tool='bakim' AND action IN ('arsivle','gecersiz_kil','supersede','gecersiz') "
               "AND ts>? ORDER BY ts DESC", (now - 7 * 86400,)):
        try:
            neden = json.loads(x["payload"] or "{}").get("neden", "")
        except ValueError:
            neden = ""
        m = re.match(r"bakım \((\w+)\):\s*(.*)", neden or "")
        tur = m.group(1) if m else x["action"]
        cozulen.append({"kayit": x["record_id"], "tur": tur, "neden": (m.group(2) if m else neden)[:300], "zaman": x["ts"]})
        ad = {"tekrar": "Tekrar kayıt", "tamamlandi": "Tamamlanmış ama açık görünen kayıt", "celiski": "Çelişen kayıt"}.get(tur, tur)
        r.bulgu(f"bakim-cozdu-{x['record_id']}", "bilgi", "hafiza", "celiski", f"{ad} bulundu ve çözüldü: {x['record_id']} (bakım ajanı)",
                (m.group(2) if m else neden)[:300], "Kayıt silinmedi; geri almak için olay günlüğüne bak.")
    v["bakim_cozulen_7g"] = cozulen
    # bakım ve kâtip
    for arac, gun, ad in (("bakim", 3, "Bakım ajanı"), ("katip", 3, "Kâtip")):
        if son.get(arac) and (now - son[arac]) / 86400 > gun:
            r.bulgu(f"{arac}-calismiyor", "orta", "hafiza", "saglik", f"{ad} {int((now - son[arac]) / 86400)} gündür çalışmadı",
                    "Mac'te Claude Code oturumu açılmadıysa normal.")
    # yedekler
    yd = data_dir / "yedek"
    yed = sorted(yd.glob("council-*.sqlite"), key=lambda p: p.stat().st_mtime)
    if yed:
        yas = (now - yed[-1].stat().st_mtime) / 3600
        v["yedek"] = {"son": yed[-1].name, "yas_saat": round(yas, 1), "adet": len(yed),
                      "sifreli": open(yed[-1], "rb").read(15) != b"SQLite format 3"}
        if yas > bek["yedek_saat"]:
            r.bulgu("yedek-eski", "yuksek", "yedek", "saglik", f"Son sunucu yedeği {int(yas)} saat önce alındı", yed[-1].name,
                    "/etc/cron.daily/council-hafiza-yedek'i elle çalıştır, hatasına bak.")
        if not v["yedek"]["sifreli"]:
            r.bulgu("yedek-sifresiz", "yuksek", "yedek", "acik", "Son yedek şifresiz", yed[-1].name)
    else:
        r.bulgu("yedek-yok", "kritik", "yedek", "saglik", "Sunucuda hiç yedek yok")
    iz = yd / ".mac-son-cekim"
    if iz.exists():
        yas = (now - iz.stat().st_mtime) / 3600
        v["mac_yedek_yas_saat"] = round(yas, 1)
        if yas > bek["mac_yedek_saat"]:
            r.bulgu("mac-yedek-eski", "orta", "yedek", "saglik", f"Mac son {int(yas)} saattir yedek çekmedi",
                    "Sunucu dışı yedek güncel değil.", "Mac'te istemci/yedek_cek.sh'yi çalıştır; launchd işi kurulu mu bak.")
    else:
        r.bulgu("mac-yedek-yok", "orta", "yedek", "acik", "Sunucu dışı yedek hiç alınmadı", "", "Mac'te istemci/yedek_cek.sh")
    r.veri["hafiza"] = v
    r.veri["araclar"] = araclar

    # cihazlar (Mac raporu)
    cihazlar = []
    rap = {c["cihaz"]: c for c in store.cihazlar()}
    for c in envanter["cihazlar"]:
        x = dict(c)
        if c["id"] in rap:
            x["rapor"] = rap[c["id"]]["bilgi"]
            x["rapor_zamani"] = rap[c["id"]]["ts"]
        cihazlar.append(x)
    r.veri["cihazlar"] = cihazlar
    mac = rap.get("mac")
    if mac and mac.get("tool") != "claude-code":
        r.bulgu("mac-rapor-kaynak", "yuksek", "mac", "acik", f"Mac raporu beklenmeyen bir araçtan geldi: {mac.get('tool')}",
                "Rapor yok sayıldı; sahte olabilir.", "Hangi aracın cihaz_bildir çağırdığını olay günlüğünden kontrol et.")
        mac = None
    if not mac:
        r.bulgu("mac-rapor-yok", "dusuk", "mac", "saglik", "Mac henüz durum raporu göndermedi",
                "Rapor, Claude Code oturumu açıldığında en çok 6 saatte bir gönderilir.")
    else:
        b = mac["bilgi"]
        if (now - mac["ts"]) / 3600 > bek["mac_rapor_saat"]:
            r.bulgu("mac-rapor-eski", "bilgi", "mac", "saglik", f"Mac raporu {int((now - mac['ts']) / 3600)} saat önce geldi")
        if b.get("filevault") is False:
            r.bulgu("filevault", "yuksek", "mac", "acik", "Mac'te FileVault (disk şifreleme) kapalı",
                    "Gizli dosyalar ve sunucu dışı yedek bu diskte.", "Sistem Ayarları → Gizlilik ve Güvenlik → FileVault")
        if str(b.get("gizli_dosya_izinleri", "tamam")) != "tamam":
            r.bulgu("mac-gizli-izin", "orta", "mac", "acik", "Mac'teki gizli dosyaların izinleri geniş", str(b.get("gizli_dosya_izinleri")), "chmod 600")
        if b.get("yedek_isi") == "yok":
            r.bulgu("mac-yedek-isi", "orta", "mac", "acik", "Mac'te günlük yedek çekme işi (launchd) kurulu değil",
                    "Sunucu dışı yedek yalnız elle çalıştırılınca alınıyor.", "istemci/com.council.yedek.plist'in başındaki komutla kur.")
        if b.get("anahtar_dosyasi") == "yok":
            r.bulgu("mac-anahtar-yok", "yuksek", "mac", "acik", "Veritabanı anahtarının Mac'te kopyası yok",
                    "Sunucu kaybolursa yedekler açılamaz.")
        hk = set(str(b.get("hooklar", "")).split(","))
        eksik = {"SessionStart", "Stop", "SessionEnd", "PreCompact"} - hk
        if eksik:
            r.bulgu("mac-hook", "orta", "mac", "celiski", "Claude Code'da COUNCIL hook'u eksik: " + ", ".join(sorted(eksik)))


# ------------------------------------------------------------------ hermes
def hermes(r: Rapor, store) -> None:
    v: dict = {}
    rc, out = _kos(["id", "hermes"])
    v["kullanici"] = rc == 0
    if rc == 0:
        gruplar = out.split("groups=")[-1]
        v["sudo"] = bool(re.search(r"\((sudo|admin|wheel)\)", gruplar))
        if v["sudo"]:
            r.bulgu("hermes-sudo", "yuksek", "hermes", "acik", "hermes kullanıcısı sudo grubunda",
                    "7/24 çalışan ve Telegram'dan mesaj alan ajan root olabilir.", "gpasswd -d hermes sudo")
        try:
            dbp = Path(store.path)
            st = dbp.stat()
            okunur = bool(st.st_mode & 0o004) or (st.st_gid != 0 and "council" in gruplar and st.st_mode & 0o040)
            v["db_okuyabilir"] = okunur
            if okunur:
                r.bulgu("hermes-db", "yuksek", "hermes", "acik", "hermes kullanıcısı hafıza veritabanını doğrudan okuyabiliyor")
        except OSError:
            pass
    tp = store.token_projeleri("hermes")
    v["token_projeleri"] = sorted(tp) if tp is not None else "*"
    if tp is None and store.q("SELECT 1 FROM static_tokens WHERE tool='hermes'"):
        r.bulgu("hermes-kapsam", "orta", "hermes", "acik", "Hermes token'ı bütün projelere açık",
                "Telegram'dan gelen talimatlarla çalışan ajan, COUNCIL projelerinin özel kayıtlarını görebilir.",
                "council-hafiza token-kapsam hermes genel,hermes")
    r.veri["hermes"] = v


# ------------------------------------------------------------------ model katmanı (isteğe bağlı)
def model_katmani(r: Rapor, store, istemci_yolu: Path) -> None:
    v = {"durum": "kapalı", "neden": ""}
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("ci", istemci_yolu)
        ci = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ci)
        ci.claude_bin()   # PATH, ~/.local/bin ve COUNCIL_CLAUDE_BIN'e bakar; yoksa RuntimeError
    except RuntimeError:
        v["neden"] = "sunucuda claude komutu yok"
        r.veri["model"] = v
        return
    except Exception as e:
        v.update(durum="hata", neden=str(e)[:300])
        r.veri["model"] = v
        return
    try:
        recs = [{"id": x["id"], "tarih": x["valid_from"] or "", "arac": x["tool"], "proje": x["project"], "tur": x["kind"],
                 "guven": x["trust"], "gorunurluk": x["visibility"], "baglam": x["context"], "metin": x["text"]}
                for x in store.q(f"SELECT * FROM records WHERE {store.CURRENT} ORDER BY created_at")]
        ops = ci.bakim_karar(recs, time.strftime("%Y-%m-%d"), ci.llm)
        ops, red = ci.bakim_dogrula(ops, recs, max_ops=40)
        v.update(durum="çalıştı", oneri=len(ops), reddedilen=len(red))
        for o in ops:
            tur = {"tekrar": "Tekrar kayıt", "tamamlandi": "Tamamlanmış ama açık görünen kayıt", "celiski": "Çelişen kayıtlar"}.get(o["tur"], o["tur"])
            r.bulgu(f"model-{o['tur']}-{o['id']}", "dusuk", "hafiza", "celiski", f"{tur}: {o['id']} ↔ {o['kanit']}", o["neden"][:300],
                    "Bakım ajanı bir sonraki çalışmasında bunu uygulayabilir; elle bakmak için iki kaydı karşılaştır.")
    except Exception as e:
        v.update(durum="hata", neden=str(e)[:300])
        if "logged in" in str(e).lower() or "/login" in str(e):
            r.bulgu("model-katmani", "dusuk", "hafiza", "saglik", "Model katmanı kapalı: sunucuda Claude girişi yapılmadı",
                    "Çelişki taraması için denetim ajanının Claude aboneliğine erişmesi gerekiyor.",
                    "Mac'te: ssh -t <sunucu> '/root/.local/bin/claude setup-token' — çıkan token'ı sunucuda "
                    "/etc/council-denetim.env dosyasına CLAUDE_CODE_OAUTH_TOKEN=... olarak yaz (chmod 600).")
        else:
            r.bulgu("model-katmani", "dusuk", "hafiza", "saglik", "Model katmanı çalışamadı", str(e)[:300])
    r.veri["model"] = v


# ------------------------------------------------------------------ ana akış
def calistir(out_dir: Path, envanter_yolu: Path, host: str, istemci_yolu: Path, store=None) -> dict:
    from .store import Store
    t0 = time.time()
    envanter = json.loads(Path(envanter_yolu).read_text(encoding="utf-8"))
    r = Rapor()
    db = os.environ.get("COUNCIL_DB", "/var/lib/council-hafiza/council.sqlite")
    store = store or Store(db)
    for ad, f in (("sunucu", lambda: sunucu(r, envanter["beklenen"], host)),
                  ("hafiza", lambda: hafiza(r, store, envanter, Path(db).parent)),
                  ("hermes", lambda: hermes(r, store)),
                  ("model", lambda: model_katmani(r, store, istemci_yolu))):
        try:
            f()
        except Exception as e:
            r.bulgu(f"denetim-{ad}", "orta", ad if ad != "model" else "hafiza", "saglik", f"{ad} denetimi tamamlanamadı", repr(e)[:300])
    for b in envanter.get("bilinen_aciklar", []):
        r.bulgu(b["id"], b["ciddiyet"], b["alan"], "acik", b["baslik"], b.get("ayrinti", ""), b.get("oneri", ""))
    # kullanıcının açık görevleri (hafızadan): ayrı bulgu değil, rapora eklenir
    sira = {c: i for i, c in enumerate(CIDDIYET)}
    r.bulgular.sort(key=lambda b: (sira[b["ciddiyet"]], b["alan"], b["id"]))
    rapor = {"zaman": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sure_sn": round(time.time() - t0, 1),
             "envanter": {"cihazlar": envanter["cihazlar"], "akislar": envanter["akislar"], "guncelleme": envanter.get("guncelleme")},
             **r.veri, "bulgular": r.bulgular,
             "ozet": {c: sum(1 for b in r.bulgular if b["ciddiyet"] == c) for c in CIDDIYET}}
    yaz_rapor(Path(out_dir), json.dumps(rapor, ensure_ascii=False, indent=1, default=str))
    return rapor


def _okuyucu_gid() -> int:
    """Raporu okuyacak grup (panel council kullanıcısıyla çalışır); yoksa root grubu."""
    try:
        import grp
        return grp.getgrnam("council").gr_gid
    except (KeyError, ImportError):
        return 0


def _guvenli_klasor(d: Path) -> None:
    """Root olarak yazarken klasör sembolik bağ olmamalı ve root'tan başkası yazamamalı (yetki yükseltmeye karşı)."""
    d.mkdir(mode=0o750, parents=True, exist_ok=True)
    if os.geteuid() == 0 and not os.path.islink(d):
        os.chown(d, 0, _okuyucu_gid()); os.chmod(d, 0o750)
    st = os.lstat(d)
    import stat as _st
    if _st.S_ISLNK(st.st_mode) or not _st.S_ISDIR(st.st_mode):
        raise RuntimeError(f"{d} klasör değil ya da sembolik bağ")
    if os.geteuid() == 0 and (st.st_uid != 0 or st.st_mode & 0o022):
        raise RuntimeError(f"{d} root'a ait değil ya da başkası yazabiliyor; rapor yazılmadı")


def _yaz(yol: Path, data: str) -> None:
    fd = os.open(yol, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o640)
    if os.geteuid() == 0:
        os.fchown(fd, 0, _okuyucu_gid())   # yalnız root ve panel (council) okur
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(data)


def yaz_rapor(out_dir: Path, data: str) -> None:
    _guvenli_klasor(out_dir)
    _guvenli_klasor(out_dir / "gecmis")
    tmp = out_dir / "son.json.yeni"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    _yaz(tmp, data)
    os.replace(tmp, out_dir / "son.json")
    g = out_dir / "gecmis" / (time.strftime("%Y-%m-%dT%H%M%S") + ".json")
    if not os.path.lexists(g):
        _yaz(g, data)
    for p in sorted((out_dir / "gecmis").glob("*.json"))[:-90]:   # son 30 gün (günde 3)
        os.unlink(p)
