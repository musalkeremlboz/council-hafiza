"""COUNCIL hafıza deposu: tek SQLite dosyası.

- records : atomik hafıza kayıtları (silinmez; geçersiz kılınır veya arşivlenir)
- events  : her değişikliğin hash zincirli, yalnızca eklenen günlüğü
- identities : araç + proje kimlikleri (amaç ve kapsam)
- routing_obs : model yönlendirme gözlemleri (iş türü, model/effort, kalite, maliyet, görev gömmesi)
- oauth_* / static_tokens : kimlik doğrulama (token'lar yalnızca SHA-256 özetiyle saklanır)
"""
from __future__ import annotations

import hashlib
import contextlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS records (
  id TEXT PRIMARY KEY, text TEXT NOT NULL, context TEXT NOT NULL DEFAULT '', keys TEXT NOT NULL DEFAULT '[]',
  kind TEXT NOT NULL, visibility TEXT NOT NULL, trust TEXT NOT NULL,
  valid_from TEXT, valid_to TEXT, superseded_by TEXT, archived INTEGER NOT NULL DEFAULT 0, archive_reason TEXT,
  tool TEXT NOT NULL, project TEXT NOT NULL, client_id TEXT, created_at REAL NOT NULL,
  embedding BLOB, emb_model TEXT
);
CREATE INDEX IF NOT EXISTS rec_project ON records(project);
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, tool TEXT, project TEXT, action TEXT NOT NULL,
  record_id TEXT, payload TEXT, prev_hash TEXT, hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS identities (
  tool TEXT NOT NULL, project TEXT NOT NULL, purpose TEXT NOT NULL, scope TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY (tool, project)
);
CREATE TABLE IF NOT EXISTS routing_obs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, tool TEXT, project TEXT, tur TEXT NOT NULL, config TEXT NOT NULL,
  kalite REAL NOT NULL, maliyet REAL NOT NULL DEFAULT 0, ozet TEXT NOT NULL DEFAULT '', embedding BLOB,
  kaynak TEXT NOT NULL DEFAULT 'canli', degerlendiren TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS cihazlar (
  cihaz TEXT PRIMARY KEY, ts REAL NOT NULL, tool TEXT, bilgi TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS istemci_kapsam (
  tool TEXT PRIMARY KEY, projeler TEXT NOT NULL, ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_clients (client_id TEXT PRIMARY KEY, data TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_pending (id TEXT PRIMARY KEY, client_id TEXT NOT NULL, params TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_codes (code_hash TEXT PRIMARY KEY, data TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_tokens (
  token_hash TEXT PRIMARY KEY, kind TEXT NOT NULL, client_id TEXT NOT NULL, scopes TEXT NOT NULL,
  expires_at REAL, pair_hash TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS static_tokens (token_hash TEXT PRIMARY KEY, tool TEXT NOT NULL, label TEXT, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts (ts REAL NOT NULL, ok INTEGER NOT NULL);
"""

KINDS = ("fact", "event", "plan", "preference", "decision", "task", "procedure")
VISIBILITY = ("shared", "project")
TRUST = ("user", "agent", "external")


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


@dataclass
class Actor:
    tool: str
    project: str
    client_id: str | None = None


def anahtar_oku(dosya: str | None = None) -> str | None:
    """Veritabanı şifreleme anahtarı (64 hex karakter). COUNCIL_DB_ANAHTAR_DOSYASI yoksa şifreleme kapalıdır."""
    dosya = dosya or os.environ.get("COUNCIL_DB_ANAHTAR_DOSYASI")
    if not dosya:
        return None
    k = Path(dosya).read_text(encoding="utf-8-sig").strip()
    if len(k) != 64 or any(c not in "0123456789abcdef" for c in k.lower()):
        raise ValueError("şifreleme anahtarı 64 hex karakter olmalı")
    return k.lower()


def baglan(path: str | Path, anahtar: str | None):
    """SQLite ya da (anahtar varsa) SQLCipher bağlantısı. Yanlış anahtarda hemen hata verir."""
    if anahtar:
        import sqlcipher3.dbapi2 as drv
    else:
        drv = sqlite3
    db = drv.connect(str(path), check_same_thread=False, isolation_level=None, timeout=30)
    if anahtar:
        db.execute(f"PRAGMA key = \"x'{anahtar}'\"")
        db.execute("SELECT count(*) FROM sqlite_master").fetchone()
    db.row_factory = drv.Row
    return db


def sifreli_mi(path: str | Path) -> bool:
    with open(path, "rb") as f:
        return f.read(16) != b"SQLite format 3\x00"


class Store:
    def __init__(self, path: str | Path, anahtar: str | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        self.anahtar = anahtar if anahtar is not None else anahtar_oku()
        self.db = baglan(self.path, self.anahtar)
        self.lock = threading.RLock()
        self._derinlik = 0
        self.db.executescript(SCHEMA)
        self._gec()
        if new:
            os.chmod(self.path, 0o600)

    # ------------------------------------------------------------ yardımcı
    def _gec(self) -> None:
        """Eski veritabanlarını yeni şemaya taşır (sütun ekleme)."""
        def ekle(tablo: str, sutun: str, tanim: str) -> None:
            if sutun in {r[1] for r in self.db.execute(f"PRAGMA table_info({tablo})")}:
                return
            try:
                self.db.execute(f"ALTER TABLE {tablo} ADD COLUMN {sutun} {tanim}")
            except sqlite3.OperationalError as e:      # başka bir süreç aynı anda eklediyse
                if "duplicate column" not in str(e).lower():
                    raise
        ekle("static_tokens", "projeler", "TEXT NOT NULL DEFAULT '*'")   # token başına erişilebilir projeler
        ekle("login_attempts", "ip", "TEXT NOT NULL DEFAULT ''")         # IP başına giriş kilidi

    def yedekle(self, hedef: str | Path) -> None:
        """Tutarlı bir kopya yazar; şifreli veritabanının yedeği aynı anahtarla şifreli olur."""
        hedef = Path(hedef)
        gecici = hedef.with_name(hedef.name + ".yeni")   # yarım kalan yedek son adla görünmesin
        if gecici.exists():
            gecici.unlink()
        with self.lock:
            if self.anahtar:
                yol = str(gecici).replace("'", "''")
                self.db.execute(f"ATTACH DATABASE '{yol}' AS yedek KEY \"x'{self.anahtar}'\"")
                self.db.execute("SELECT sqlcipher_export('yedek')")
                self.db.execute("DETACH DATABASE yedek")
            else:
                out = sqlite3.connect(gecici)
                self.db.backup(out)
                out.close()
        os.chmod(gecici, 0o600)
        kontrol = baglan(gecici, self.anahtar)
        try:
            if kontrol.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("yedek bütünlük denetiminden geçmedi")
        finally:
            kontrol.close()
        os.replace(gecici, hedef)

    def cihaz_yaz(self, actor: Actor, cihaz: str, bilgi: dict) -> None:
        with self.yaz():
            self.db.execute("INSERT INTO cihazlar VALUES (?,?,?,?) ON CONFLICT(cihaz) DO UPDATE SET ts=excluded.ts, tool=excluded.tool,"
                            " bilgi=excluded.bilgi", (cihaz, time.time(), actor.tool, json.dumps(bilgi, ensure_ascii=False)))
            self.log(actor, "cihaz", None, {"cihaz": cihaz, "anahtarlar": sorted(bilgi)})

    def cihazlar(self) -> list[dict]:
        return [dict(r, bilgi=json.loads(r["bilgi"] or "{}")) for r in self.q("SELECT * FROM cihazlar ORDER BY cihaz")]

    @staticmethod
    def _projeler(v: str | None) -> set[str] | None:
        v = (v or "*").strip()
        return None if v == "*" else {x.strip() for x in v.split(",") if x.strip()}

    def token_kapsami(self, onek: str) -> set[str] | None:
        """Tek bir statik token'ın (özetinin ilk 16 karakteri) erişebildiği projeler; None = hepsi."""
        rows = self.q("SELECT projeler FROM static_tokens WHERE substr(token_hash, 1, 16)=?", (onek,))
        return self._projeler(rows[0]["projeler"]) if rows else set()

    def istemci_kapsami(self, tool: str) -> tuple[bool, set[str] | None]:
        """OAuth istemcisinin (araç adına göre) açıkça tanımlanmış kapsamı: (tanımlı mı, projeler; None = hepsi)."""
        rows = self.q("SELECT projeler FROM istemci_kapsam WHERE tool=?", (tool,))
        return (True, self._projeler(rows[0]["projeler"])) if rows else (False, None)

    def token_projeleri(self, tool: str) -> set[str] | None:
        """Aracın statik token'larının erişebildiği projeler; None = hepsi."""
        rows = self.q("SELECT projeler FROM static_tokens WHERE tool=?", (tool,))
        out: set[str] = set()
        for r in rows:
            v = (r["projeler"] or "*").strip()
            if v == "*":
                return None
            out |= {x.strip() for x in v.split(",") if x.strip()}
        return out if rows else None

    @contextlib.contextmanager
    def yaz(self):
        """Yazma işlemi: süreçler arası tek seferde bir yazar (BEGIN IMMEDIATE). İç içe çağrılar tek işlem olur.
        Okuma-sonra-yazma adımları (kayıt numarası, günlük zinciri) başka bir süreçle karışmaz; yerel sürümde
        MCP sunucusu ve kâtip aynı veritabanına ayrı süreçlerden yazar."""
        with self.lock:
            dis = self._derinlik == 0
            if dis:
                self.db.execute("BEGIN IMMEDIATE")
            self._derinlik += 1
            try:
                yield
            except BaseException:
                self._derinlik -= 1
                if dis:
                    self.db.execute("ROLLBACK")
                raise
            self._derinlik -= 1
            if dis:
                self.db.execute("COMMIT")

    def q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def x(self, sql: str, args: tuple = ()) -> None:
        with self.yaz():
            self.db.execute(sql, args)

    # --------------------------------------------------------------- günlük
    def log(self, actor: Actor | None, action: str, record_id: str | None, payload: dict) -> None:
        with self.yaz():
            prev = self.db.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            prev_hash = prev["hash"] if prev else ""
            ts = time.time()
            body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            h = sha(f"{prev_hash}|{ts}|{actor.tool if actor else ''}|{action}|{record_id}|{body}")
            self.db.execute("INSERT INTO events (ts, tool, project, action, record_id, payload, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?)",
                            (ts, actor.tool if actor else None, actor.project if actor else None, action, record_id, body, prev_hash, h))

    def verify_chain(self) -> bool:
        prev = ""
        for r in self.q("SELECT * FROM events ORDER BY seq"):
            h = sha(f"{prev}|{r['ts']}|{r['tool'] or ''}|{r['action']}|{r['record_id']}|{r['payload']}")
            if r["prev_hash"] != prev or r["hash"] != h:
                return False
            prev = r["hash"]
        return True

    # -------------------------------------------------------------- kayıtlar
    def next_id(self) -> str:
        row = self.q("SELECT COUNT(*) AS n FROM records")[0]
        return f"R{row['n'] + 1:05d}"

    def add_record(self, actor: Actor, rec: dict) -> str:
        with self.yaz():
            rid = self.next_id()
            self.db.execute(
                "INSERT INTO records (id, text, context, keys, kind, visibility, trust, valid_from, tool, project, client_id, created_at, embedding, emb_model)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, rec["text"], rec.get("context", ""), json.dumps(rec.get("keys", []), ensure_ascii=False), rec["kind"],
                 rec["visibility"], rec["trust"], rec.get("valid_from"), actor.tool, actor.project, actor.client_id, time.time(),
                 rec.get("embedding"), rec.get("emb_model")))
            self.log(actor, "kaydet", rid, {k: v for k, v in rec.items() if k != "embedding"})
        return rid

    def get(self, rid: str) -> dict | None:
        rows = self.q("SELECT * FROM records WHERE id=?", (rid,))
        return dict(rows[0]) if rows else None

    CURRENT = "archived=0 AND COALESCE(superseded_by,'')='' AND COALESCE(valid_to,'')=''"

    def is_current(self, rid: str) -> bool:
        return bool(self.q(f"SELECT 1 FROM records WHERE id=? AND {self.CURRENT}", (rid,)))

    def supersede(self, actor: Actor, old_id: str, new_id: str | None, reason: str) -> bool:
        """Yalnız hâlâ güncel olan kaydı geçersiz kılar; kayıt bu arada değiştiyse False döner (eşzamanlı yazımlara karşı)."""
        with self.yaz():
            new = self.get(new_id) if new_id else None
            valid_to = (new or {}).get("valid_from") or time.strftime("%Y-%m-%d")
            cur = self.db.execute(f"UPDATE records SET superseded_by=?, valid_to=? WHERE id=? AND {self.CURRENT}",
                                  (new_id or "", valid_to, old_id))
            if cur.rowcount == 0:
                return False
            self.log(actor, "gecersiz_kil", old_id, {"yerine": new_id, "neden": reason})
            return True

    def archive(self, actor: Actor, rid: str, reason: str) -> bool:
        with self.yaz():
            cur = self.db.execute("UPDATE records SET archived=1, archive_reason=? WHERE id=? AND archived=0", (reason, rid))
            if cur.rowcount == 0:
                return False
            self.log(actor, "arsivle", rid, {"neden": reason})
            return True

    def unarchive(self, actor: Actor, rid: str, reason: str) -> bool:
        """Arşivdeki kaydı geri getirir (Gezgin). Kayıt arşivde değilse False."""
        with self.yaz():
            cur = self.db.execute("UPDATE records SET archived=0, archive_reason=NULL WHERE id=? AND archived=1", (rid,))
            if cur.rowcount == 0:
                return False
            self.log(actor, "arsivden_cikar", rid, {"neden": reason})
            return True

    def replace_records(self, actor: Actor, old_ids: list[str], rec: dict, reason: str, action: str) -> str:
        """Yeni bir kayıt yazar ve eskilerin HEPSİNİ onunla geçersiz kılar; tek işlemde, ya hep ya hiç (Gezgin'in düzelt ve
        birleştir işlemleri). Eski kayıtlardan biri bu arada değiştiyse ValueError atar ve hiçbir şey yazılmaz."""
        with self.yaz():
            for o in old_ids:
                if not self.is_current(o):
                    raise ValueError(f"{o} artık güncel değil (başka biri değiştirmiş olabilir)")
            rid = self.add_record(actor, rec)
            for o in old_ids:
                if not self.supersede(actor, o, rid, reason):
                    raise ValueError(f"{o} geçersiz kılınamadı")
            self.log(actor, action, rid, {"kaynaklar": list(old_ids), "neden": reason})
        return rid

    def list_records(self, with_embedding: bool = False) -> list[dict]:
        """Bütün kayıtlar (yönetici görünümü; görünürlük süzgeci yok). Vektör sütunu yalnız istenirse okunur."""
        cols = "*" if with_embedding else ("id, text, context, keys, kind, visibility, trust, valid_from, valid_to, superseded_by, "
                                           "archived, archive_reason, tool, project, client_id, created_at")
        return [dict(r) for r in self.q(f"SELECT {cols} FROM records")]

    def record_history(self, rid: str) -> list[dict]:
        """Bir kayda dokunan bütün olaylar (kaydet, geçersiz kıl, arşivle, birleştir...) eskiden yeniye."""
        rows = self.q("SELECT seq, ts, tool, project, action, record_id, payload FROM events WHERE record_id=? ORDER BY seq", (rid,))
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d["payload"] or "{}")
            except ValueError:
                d["payload"] = {}
            out.append(d)
        return out

    def visible_records(self, project: str, include_archived: bool = False) -> list[dict]:
        sql = "SELECT * FROM records WHERE (visibility='shared' OR project=?)"
        if not include_archived:
            sql += " AND archived=0"
        return [dict(r) for r in self.q(sql, (project,))]

    def set_embedding(self, rid: str, emb: bytes, model: str) -> None:
        self.x("UPDATE records SET embedding=?, emb_model=? WHERE id=?", (emb, model, rid))

    # ------------------------------------------------------------- kimlikler
    def identity(self, tool: str, project: str) -> dict | None:
        """Projeye özel kimlik, yoksa aracın tüm projeler için tanımı (project='*')."""
        rows = self.q("SELECT * FROM identities WHERE tool=? AND project IN (?, '*') ORDER BY project='*'", (tool, project))
        return dict(rows[0]) if rows else None

    def identities(self) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM identities ORDER BY tool, project")]

    def set_identity(self, actor: Actor, purpose: str, scope: str) -> None:
        now = time.time()
        with self.yaz():
            self.db.execute("INSERT INTO identities VALUES (?,?,?,?,?,?) ON CONFLICT(tool, project) DO UPDATE SET purpose=excluded.purpose,"
                            " scope=excluded.scope, updated_at=excluded.updated_at", (actor.tool, actor.project, purpose, scope, now, now))
            self.log(actor, "kimlik", None, {"amac": purpose, "kapsam": scope})

    # ------------------------------------------------------------- yönlendirme gözlemleri
    def add_routing(self, actor: Actor | None, tur: str, config: str, kalite: float, maliyet: float, ozet: str,
                    embedding: bytes | None, kaynak: str = "canli", degerlendiren: str = "", log: bool = True) -> int:
        with self.yaz():
            cur = self.db.execute("INSERT INTO routing_obs (ts, tool, project, tur, config, kalite, maliyet, ozet, embedding, kaynak, degerlendiren)"
                                  " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                  (time.time(), actor.tool if actor else None, actor.project if actor else None, tur, config,
                                   float(kalite), float(maliyet), ozet, embedding, kaynak, degerlendiren))
            rid = int(cur.lastrowid)
            if log:
                self.log(actor, "yonlendirme", None, {"id": rid, "tur": tur, "config": config, "kalite": kalite, "kaynak": kaynak})
            self.routing_version = getattr(self, "routing_version", 0) + 1
        return rid

    def routing_rows(self) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM routing_obs ORDER BY id")]

    def set_tool_identity(self, actor: Actor, purpose: str, scope: str) -> list[str]:
        """Aracın tüm projelerdeki kimliğini tek tanımla değiştirir; projeye özel eski tanımları kaldırır."""
        now = time.time()
        with self.yaz():
            old = [r["project"] for r in self.q("SELECT project FROM identities WHERE tool=? AND project!='*'", (actor.tool,))]
            self.db.execute("DELETE FROM identities WHERE tool=? AND project!='*'", (actor.tool,))
            self.db.execute("INSERT INTO identities VALUES (?,?,?,?,?,?) ON CONFLICT(tool, project) DO UPDATE SET purpose=excluded.purpose,"
                            " scope=excluded.scope, updated_at=excluded.updated_at", (actor.tool, "*", purpose, scope, now, now))
            self.log(actor, "kimlik", None, {"amac": purpose, "kapsam": scope, "tum_projeler": True, "kaldirilan": old})
        return old
