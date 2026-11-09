"""Uçtan uca HTTP testi: OAuth (DCR + PKCE + giriş sayfası), statik token, yenileme, yetkisiz erişim."""
import base64
import hashlib
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture(scope="module")
def server():
    from council_hafiza.auth import hash_password
    port = _free_port()
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "COUNCIL_DB": os.path.join(tmp, "s.sqlite"), "COUNCIL_BASE_URL": f"http://127.0.0.1:{port}",
           "COUNCIL_ADMIN_HASH": hash_password("dogru-parola-123"), "COUNCIL_EMBED": "none", "COUNCIL_PORT": str(port),
           "PYTHONPATH": str(ROOT)}
    p = subprocess.Popen([sys.executable, "-m", "council_hafiza.server"], env=env, cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/saglik", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.2)
    else:
        p.kill(); raise RuntimeError(p.stdout.read().decode()[-3000:])
    yield base, env
    p.terminate(); p.wait(5)


def _mcp(base, token, method, params=None, id_=1):
    h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}
    return httpx.post(base + "/mcp", json=body, headers=h, timeout=10)


def test_yetkisiz_401(server):
    base, _ = server
    r = _mcp(base, None, "tools/list")
    assert r.status_code == 401
    assert "resource_metadata" in r.headers.get("www-authenticate", "")
    assert _mcp(base, "uydurma-token", "tools/list").status_code == 401


def test_oauth_akisi(server):
    base, env = server
    meta = httpx.get(base + "/.well-known/oauth-authorization-server").json()
    reg = httpx.post(meta["registration_endpoint"], json={"client_name": "Claude", "redirect_uris": ["http://127.0.0.1:9/geri"],
                                                          "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
                                                          "token_endpoint_auth_method": "none", "scope": "hafiza"}).json()
    cid = reg["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    q = {"response_type": "code", "client_id": cid, "redirect_uri": "http://127.0.0.1:9/geri", "code_challenge": challenge,
         "code_challenge_method": "S256", "state": "xyz", "scope": "hafiza", "resource": base + "/mcp"}
    r = httpx.get(meta["authorization_endpoint"], params=q, follow_redirects=False)
    assert r.status_code in (302, 307), r.text
    login = r.headers["location"]
    assert "/giris?istek=" in login
    pid = urllib.parse.parse_qs(urllib.parse.urlparse(login).query)["istek"][0]
    assert "Yönetici parolası" in httpx.get(login).text
    wrong = httpx.post(base + "/giris", data={"istek": pid, "parola": "yanlis"}, follow_redirects=False)
    assert wrong.status_code == 401
    ok = httpx.post(base + "/giris", data={"istek": pid, "parola": "dogru-parola-123"}, follow_redirects=False)
    assert ok.status_code == 302
    loc = urllib.parse.urlparse(ok.headers["location"])
    params = urllib.parse.parse_qs(loc.query)
    assert params["state"] == ["xyz"]
    tok = httpx.post(meta["token_endpoint"], data={"grant_type": "authorization_code", "code": params["code"][0], "client_id": cid,
                                                   "redirect_uri": "http://127.0.0.1:9/geri", "code_verifier": verifier,
                                                   "resource": base + "/mcp"}).json()
    assert "access_token" in tok, tok
    # aynı kod ikinci kez kullanılamaz
    again = httpx.post(meta["token_endpoint"], data={"grant_type": "authorization_code", "code": params["code"][0], "client_id": cid,
                                                     "redirect_uri": "http://127.0.0.1:9/geri", "code_verifier": verifier})
    assert again.status_code >= 400
    init = _mcp(base, tok["access_token"], "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                          "clientInfo": {"name": "test", "version": "1"}})
    assert init.status_code == 200, init.text
    # yenileme: eski yenileme token'ı ikinci kez çalışmaz
    new = httpx.post(meta["token_endpoint"], data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": cid}).json()
    assert "access_token" in new
    old = httpx.post(meta["token_endpoint"], data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": cid})
    assert old.status_code >= 400
    assert _mcp(base, tok["access_token"], "tools/list").status_code == 401   # eski erişim token'ı da iptal


def test_statik_token(server):
    base, env = server
    out = subprocess.run([sys.executable, "-m", "council_hafiza.cli", "token-olustur", "claude-code", "test"], env=env,
                         capture_output=True, text=True, check=True).stdout.strip()
    assert out.startswith("chz_")
    r = _mcp(base, out, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    assert r.status_code == 200, r.text
