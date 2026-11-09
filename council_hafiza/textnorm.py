"""Türkçe/İngilizce metin normalleştirme, sözcük ayırma, kök bulma ve cevap eşleştirme."""
from __future__ import annotations

import re

_FOLD = str.maketrans("çğıöşüâîûÇĞÖŞÜÂÎÛ", "cgiosuaiuCGOSUAIU")


def tr_lower(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def fold(s: str) -> str:
    """Küçük harf + Türkçe karakter katlama + noktalama temizliği (ç→c, ı→i ...)."""
    s = tr_lower(s).translate(_FOLD)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


STOP = set(fold(w) for w in """
ve ile de da ki bu şu o bir için mi mı mu mü ne neden nasıl hangi ben sen biz siz onlar ama fakat çok daha en gibi
olarak olan oldu olur var yok mı benim senin bizim ise ya veya hem diye kadar sonra önce şey şimdi zaman ne zaman
the a an and or of to in on at for is are was were be been my your it this that what when which who how do did does
""".split())


def tokens(s: str) -> list[str]:
    return [t for t in fold(s).split() if t not in STOP]


def stem(tok: str, n: int = 5) -> str:
    """F5 kök bulma: Türkçe bilgi erişiminde ilk 5 harf etkili ve aksan hatasına dayanıklı."""
    return tok if tok.isdigit() else tok[:n]


def stems(s: str) -> list[str]:
    return [stem(t) for t in tokens(s)]


# ---------------------------------------------------------------- tarih/sayı
_MONTHS = {
    **{m: i for i, m in enumerate("ocak subat mart nisan mayis haziran temmuz agustos eylul ekim kasim aralik".split(), 1)},
    **{m: i for i, m in enumerate("january february march april may june july august september october november december".split(), 1)},
    **{m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)},
}


def dates_in(s: str) -> set[tuple[int, int, int | None]]:
    f = fold(s)
    out: set[tuple[int, int, int | None]] = set()
    for y, m, d in re.findall(r"\b(20\d\d) (\d{1,2}) (\d{1,2})\b", f):          # 2026-11-14
        out.add((int(d), int(m), int(y)))
    for d, m, y in re.findall(r"\b(\d{1,2}) (\d{1,2}) (20\d\d)\b", f):          # 14.11.2026
        out.add((int(d), int(m), int(y)))
    mon = "|".join(sorted(_MONTHS, key=len, reverse=True))
    for d, m, y in re.findall(rf"\b(\d{{1,2}}) ({mon})[a-z]*(?: (20\d\d))?", f):  # 14 kasim 2026
        out.add((int(d), _MONTHS[m], int(y) if y else None))
    for m, d, y in re.findall(rf"\b({mon})[a-z]* (\d{{1,2}})(?: (20\d\d))?\b", f):  # november 14 2026
        out.add((int(d), _MONTHS[m], int(y) if y else None))
    return {x for x in out if 1 <= x[0] <= 31 and 1 <= x[1] <= 12}


def numbers_in(s: str) -> set[float]:
    s2 = re.sub(r"(?<=\d)[.](?=\d{3}\b)", "", s)          # 1.250 -> 1250
    s2 = re.sub(r"(?<=\d),(?=\d{1,2}\b)", ".", s2)         # 12,5 -> 12.5
    s2 = s2.replace(",", "")
    return {float(x) for x in re.findall(r"\d+(?:\.\d+)?", s2)}


def _date_match(a: set, g: set) -> bool:
    for (d1, m1, y1) in a:
        for (d2, m2, y2) in g:
            if d1 == d2 and m1 == m2 and (y1 is None or y2 is None or y1 == y2):
                return True
    return False


def answer_matches(answer: str, gold: str, aliases: list[str], kind: str) -> bool:
    """Kurala dayalı eşleşme. Yanlış pozitiften kaçınmak için kısa cevap varsayar."""
    A = " " + fold(answer) + " "
    cands = [gold] + list(aliases or [])
    if kind == "date":
        gd = set().union(*(dates_in(c) for c in cands))
        if gd and _date_match(dates_in(answer), gd):
            return True
    if kind == "number":
        gn = set().union(*(numbers_in(c) for c in cands))
        an = numbers_in(answer)
        if gn and an and (gn & an):
            return True
    for c in cands:
        fc = fold(c)
        if fc and len(fc) >= 2 and (" " + fc + " ") in A:
            return True
    return False


_ABSTAIN_RE = re.compile(r"bilmiyorum|bilgi (yok|bulunm)|hafiza(mda|da) (yok|bulunm)|kayit (yok|bulunm)|"
                         r"don ?t know|no (record|information)|not (in|found)|cannot find|paylasamam|veremem", re.I)


def looks_like_abstain(answer: str) -> bool:
    return bool(_ABSTAIN_RE.search(fold(answer)))
