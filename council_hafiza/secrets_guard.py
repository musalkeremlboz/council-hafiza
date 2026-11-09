"""Gizli bilgi bekçisi: şifre, API anahtarı, IBAN, kart ve TC kimlik numarası hafızaya yazılamaz."""
from __future__ import annotations

import re

_PATTERNS = [
    ("api-anahtari", re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghs|ghu|github_pat|chz|xox[abp])[-_][A-Za-z0-9_\-]{8,}")),
    ("aws-anahtari", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("iban", re.compile(r"\bTR\d{2}(?:[ ]?\d{4}){5}[ ]?\d{2}\b", re.I)),
    ("parola", re.compile(r"(?i)\b(?:api[_ -]?key|token|secret|[sşSŞ][iİı]fre(?:m|si)?|parola(?:m|s[ıi])?|password|passwd|pin(?:\s*kod\w*)?)\s*"
                          r"(?:[:=]|\bis\b|\b[sş]u\b\s*:?)\s*\S{4,}")),
    ("parola", re.compile(r"(?i)\b(?:[sşSŞ][iİı]fre\w*|parola\w*|password|passwd)\s+(?=\S*\d)\S{4,}")),
    ("uzun-anahtar", re.compile(r"\b(?=[A-Za-z0-9_\-]{28,}\b)(?=[^ ]*\d)(?=[^ ]*[A-Za-z])[A-Za-z0-9_\-]{28,}\b")),
    ("kart-guvenlik", re.compile(r"(?i)\b(?:cvv2?|cvc2?|pin(?:\s*kod\w*)?)\s*[:=]?\s*\d{3,6}\b")),
    ("ozel-anahtar", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]


def _luhn(num: str) -> bool:
    d = [int(c) for c in num][::-1]
    return (sum(d[0::2]) + sum(sum(divmod(2 * x, 10)) for x in d[1::2])) % 10 == 0


def _tc_ok(n: str) -> bool:
    if len(n) != 11 or n[0] == "0":
        return False
    d = list(map(int, n))
    return (sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10 == d[9] and sum(d[:10]) % 10 == d[10]


def find_secrets(text: str) -> list[str]:
    found = [name for name, p in _PATTERNS if p.search(text)]
    for m in re.finditer(r"\b\d(?:[ -]?\d){10,18}\b", text):
        raw = re.sub(r"[ -]", "", m.group(0))
        if 13 <= len(raw) <= 19 and _luhn(raw):
            found.append("kart-numarasi")
        elif _tc_ok(raw):
            found.append("tc-kimlik")
    return sorted(set(found))
