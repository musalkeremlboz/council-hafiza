"""Tek kullanıcılı OAuth 2.1 yetkilendirme sunucusu + araç başına statik token.

- Claude sohbeti (claude.ai), ChatGPT, Gemini gibi web istemcileri: OAuth (DCR + PKCE). Yetki sırasında
  sunucunun kendi /giris sayfası açılır; sahibi yönetici parolasını girer (parola yalnızca scrypt özeti olarak saklanır).
- Claude Code, Hermes, Antigravity gibi CLI araçları: `council-hafiza token-olustur <arac>` ile üretilen statik token.
- Bütün token ve kodlar veritabanında yalnızca SHA-256 özetiyle tutulur.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets
import time

from mcp.server.auth.provider import (AccessToken, AuthorizationCode, AuthorizationParams, AuthorizeError,
                                      RefreshToken, TokenError, construct_redirect_uri)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from fastmcp.server.auth.auth import ClientRegistrationOptions, OAuthProvider, RevocationOptions

from .store import Store, sha

SCOPE = "hafiza"
CODE_TTL, ACCESS_TTL, REFRESH_TTL, PENDING_TTL = 300, 3600, 90 * 86400, 900
MAX_FAILS, FAIL_WINDOW = 5, 900


# ------------------------------------------------------------------ parola
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1)
        return hmac.compare_digest(got.hex(), h)
    except Exception:
        return False


def tool_slug(name: str | None) -> str:
    n = (name or "web-istemci").lower()
    for k, v in {"claude code": "claude-code", "claude": "claude-chat", "chatgpt": "chatgpt", "openai": "chatgpt",
                 "gemini": "gemini", "antigravity": "antigravity", "hermes": "hermes", "grok": "grok"}.items():
        if k in n:
            return v
    return "".join(c if c.isalnum() else "-" for c in n).strip("-")[:40] or "web-istemci"


class CouncilAuth(OAuthProvider):
    def __init__(self, store: Store, base_url: str, admin_hash: str | None):
        super().__init__(base_url=base_url,
                         client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]),
                         revocation_options=RevocationOptions(enabled=True),
                         required_scopes=[SCOPE])
        self.store = store
        self.admin_hash = admin_hash
        self.public_base = base_url.rstrip("/")

    # ------------------------------------------------------------- istemci
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        rows = self.store.q("SELECT data FROM oauth_clients WHERE client_id=?", (client_id,))
        return OAuthClientInformationFull.model_validate_json(rows[0]["data"]) if rows else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if client_info.client_id is None:
            raise ValueError("client_id gerekli")
        if client_info.scope and not set(client_info.scope.split()) <= {SCOPE}:
            raise ValueError("geçersiz kapsam")
        self.store.x("INSERT OR REPLACE INTO oauth_clients VALUES (?,?,?)", (client_info.client_id, client_info.model_dump_json(), time.time()))
        self.store.log(None, "oauth_istemci", None, {"client_id": client_info.client_id, "ad": client_info.client_name})

    def client_tool(self, client_id: str) -> str:
        if client_id.startswith("static:"):
            return client_id.split(":")[1]
        rows = self.store.q("SELECT data FROM oauth_clients WHERE client_id=?", (client_id,))
        name = json.loads(rows[0]["data"]).get("client_name") if rows else None
        return tool_slug(name)

    def client_projects(self, client_id: str) -> set[str] | None:
        """İstemcinin erişebildiği projeler (None = hepsi). Statik token'larda token'a bağlı; OAuth istemcileri (claude.ai) hepsi."""
        if client_id.startswith("static:"):
            parca = client_id.split(":")
            return self.store.token_kapsami(parca[2]) if len(parca) > 2 else self.store.token_projeleri(parca[1])
        return self.store.istemci_kapsami(self.client_tool(client_id))[1]   # OAuth: tanımlı değilse hepsi

    # -------------------------------------------------------------- yetki
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if not self.admin_hash:
            raise AuthorizeError(error="access_denied", error_description="Sunucuda yönetici parolası ayarlanmamış.")
        pid = secrets.token_urlsafe(24)
        self.store.x("INSERT INTO oauth_pending VALUES (?,?,?,?)", (pid, client.client_id, params.model_dump_json(), time.time() + PENDING_TTL))
        return f"{self.public_base}/giris?istek={pid}"

    def _fails_recent(self, ip: str = "") -> int:
        q = "SELECT COUNT(*) AS n FROM login_attempts WHERE ok=0 AND ts>?" + (" AND ip=?" if ip else "")
        return self.store.q(q, (time.time() - FAIL_WINDOW, ip) if ip else (time.time() - FAIL_WINDOW,))[0]["n"]

    def giris_engelli(self, ip: str) -> bool:
        """IP başına 15 dakikada 5 hatalı deneme; dağıtık denemelere karşı toplamda 50. Tek saldırgan sahibini kilitleyemez."""
        return self._fails_recent(ip) >= MAX_FAILS or self._fails_recent() >= MAX_FAILS * 10

    def giris_kaydet(self, ip: str, ok: bool) -> None:
        self.store.x("INSERT INTO login_attempts (ts, ok, ip) VALUES (?,?,?)", (time.time(), int(ok), ip))

    async def login_page(self, request: Request) -> Response:
        pid = request.query_params.get("istek") or ""
        if request.method == "POST":
            form = await request.form()
            pid = str(form.get("istek", ""))
        rows = self.store.q("SELECT * FROM oauth_pending WHERE id=? AND expires_at>?", (pid, time.time()))
        if not rows:
            return HTMLResponse(_page("Bu bağlantı geçersiz ya da süresi doldu. Bağlantıyı istemciden yeniden başlat.", None), status_code=400)
        pending = rows[0]
        client = await self.get_client(pending["client_id"])
        cname = (client.client_name if client else None) or pending["client_id"]
        if request.method == "GET":
            return HTMLResponse(_page(None, pid, cname))
        ip = istemci_ip(request)
        if self.giris_engelli(ip):
            return HTMLResponse(_page("Çok fazla hatalı deneme. 15 dakika sonra tekrar dene.", pid, cname), status_code=429)
        ok = check_password(str(form.get("parola", "")), self.admin_hash or "")
        self.giris_kaydet(ip, ok)
        if not ok:
            time.sleep(1.0)
            return HTMLResponse(_page("Parola yanlış.", pid, cname), status_code=401)
        params = AuthorizationParams.model_validate_json(pending["params"])
        code = secrets.token_urlsafe(32)
        ac = AuthorizationCode(code=code, client_id=pending["client_id"], redirect_uri=params.redirect_uri,
                               redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                               scopes=params.scopes or [SCOPE], expires_at=time.time() + CODE_TTL,
                               code_challenge=params.code_challenge, resource=getattr(params, "resource", None))
        self.store.x("INSERT INTO oauth_codes VALUES (?,?,?)", (sha(code), ac.model_dump_json(), ac.expires_at))
        self.store.x("DELETE FROM oauth_pending WHERE id=?", (pid,))
        self.store.log(None, "oauth_onay", None, {"client_id": pending["client_id"], "ad": cname})
        return RedirectResponse(construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state), status_code=302)

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> AuthorizationCode | None:
        rows = self.store.q("SELECT data FROM oauth_codes WHERE code_hash=? AND expires_at>?", (sha(authorization_code), time.time()))
        if not rows:
            return None
        ac = AuthorizationCode.model_validate_json(rows[0]["data"])
        return ac if ac.client_id == client.client_id else None

    def _issue(self, client_id: str, scopes: list[str]) -> OAuthToken:
        at, rt = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
        now = time.time()
        self.store.x("INSERT INTO oauth_tokens VALUES (?,?,?,?,?,?,?)", (sha(at), "access", client_id, " ".join(scopes), now + ACCESS_TTL, sha(rt), now))
        self.store.x("INSERT INTO oauth_tokens VALUES (?,?,?,?,?,?,?)", (sha(rt), "refresh", client_id, " ".join(scopes), now + REFRESH_TTL, sha(at), now))
        return OAuthToken(access_token=at, token_type="Bearer", expires_in=ACCESS_TTL, refresh_token=rt, scope=" ".join(scopes))

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        h = sha(authorization_code.code)
        if not self.store.q("SELECT 1 FROM oauth_codes WHERE code_hash=?", (h,)):
            raise TokenError("invalid_grant", "Kod bulunamadı ya da kullanıldı.")
        self.store.x("DELETE FROM oauth_codes WHERE code_hash=?", (h,))
        return self._issue(client.client_id, authorization_code.scopes)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        rows = self.store.q("SELECT * FROM oauth_tokens WHERE token_hash=? AND kind='refresh'", (sha(refresh_token),))
        if not rows or rows[0]["client_id"] != client.client_id or (rows[0]["expires_at"] and rows[0]["expires_at"] < time.time()):
            return None
        r = rows[0]
        return RefreshToken(token=refresh_token, client_id=r["client_id"], scopes=r["scopes"].split(), expires_at=int(r["expires_at"]) if r["expires_at"] else None)

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        if not set(scopes) <= set(refresh_token.scopes):
            raise TokenError("invalid_scope", "Kapsam aşıldı.")
        self._revoke_pair(sha(refresh_token.token))
        return self._issue(client.client_id, scopes or refresh_token.scopes)

    async def load_access_token(self, token: str) -> AccessToken | None:
        h = sha(token)
        rows = self.store.q("SELECT * FROM oauth_tokens WHERE token_hash=? AND kind='access'", (h,))
        if rows:
            r = rows[0]
            if r["expires_at"] and r["expires_at"] < time.time():
                return None
            return AccessToken(token=token, client_id=r["client_id"], scopes=r["scopes"].split(), expires_at=int(r["expires_at"]))
        rows = self.store.q("SELECT * FROM static_tokens WHERE token_hash=?", (h,))
        if rows:
            # kimlikte token özetinin başı da var: kapsam araç adına değil token'ın kendisine bağlı
            return AccessToken(token=token, client_id=f"static:{rows[0]['tool']}:{h[:16]}", scopes=[SCOPE], expires_at=None)
        return None

    async def verify_token(self, token: str) -> AccessToken | None:
        return await self.load_access_token(token)

    def _revoke_pair(self, token_hash: str) -> None:
        rows = self.store.q("SELECT pair_hash FROM oauth_tokens WHERE token_hash=?", (token_hash,))
        self.store.x("DELETE FROM oauth_tokens WHERE token_hash=?", (token_hash,))
        if rows and rows[0]["pair_hash"]:
            self.store.x("DELETE FROM oauth_tokens WHERE token_hash=?", (rows[0]["pair_hash"],))

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        self._revoke_pair(sha(token.token))


def istemci_ip(request) -> str:
    """Sunucu yalnız 127.0.0.1'de dinler, önünde Caddy var: istemci adresi X-Forwarded-For'un ilk değeridir."""
    xff = request.headers.get("x-forwarded-for", "")
    return (xff.split(",")[0].strip() if xff else (request.client.host if request.client else ""))[:64]


def new_static_token(store: Store, tool: str, label: str = "", projeler: str = "*") -> str:
    tok = "chz_" + secrets.token_urlsafe(32)
    store.x("INSERT INTO static_tokens (token_hash, tool, label, created_at, projeler) VALUES (?,?,?,?,?)",
            (sha(tok), tool, label, time.time(), projeler or "*"))
    store.log(None, "token_olustur", None, {"arac": tool, "etiket": label, "projeler": projeler or "*"})
    return tok


def _page(msg: str | None, pid: str | None, cname: str = "") -> str:
    body = f"<p class='m'>{html.escape(msg)}</p>" if msg else ""
    form = ""
    if pid:
        form = f"""<p><b>{html.escape(cname)}</b> COUNCIL hafızana erişmek istiyor. Onaylamak için yönetici parolanı gir.</p>
<form method="post"><input type="hidden" name="istek" value="{html.escape(pid)}">
<label for="parola">Yönetici parolası</label><input id="parola" name="parola" type="password" autocomplete="current-password" autofocus required>
<button type="submit">Erişime izin ver</button></form>"""
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>COUNCIL hafıza girişi</title><style>
body{{font-family:system-ui,sans-serif;background:#f4f5f7;color:#1d2330;display:grid;place-items:center;min-height:100vh;margin:0;padding:16px}}
main{{background:#fff;border:1px solid #dde1e8;border-radius:10px;padding:28px;max-width:26rem;width:100%;box-sizing:border-box}}
h1{{font-size:1.25rem;margin:0 0 12px}} label{{display:block;margin:16px 0 6px;font-size:.9rem}}
input{{width:100%;box-sizing:border-box;padding:10px;border:1px solid #c5cbd6;border-radius:6px;font-size:1rem}}
button{{margin-top:16px;width:100%;padding:11px;border:0;border-radius:6px;background:#2b4a8b;color:#fff;font-size:1rem;cursor:pointer}}
.m{{color:#a33;}} @media (prefers-color-scheme: dark){{body{{background:#14171c;color:#e6e8ec}}main{{background:#1d2128;border-color:#2e333d}}input{{background:#14171c;color:#e6e8ec;border-color:#3a404b}}}}
</style></head><body><main><h1>COUNCIL hafıza</h1>{body}{form}</main></body></html>"""
