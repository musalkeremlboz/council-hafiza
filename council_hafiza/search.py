"""Hibrit arama: BM25 (F5 kök, Türkçe katlama) + isteğe bağlı yoğun vektör (BGE-M3), RRF ile birleştirme.

Testlerde seçilen v0.1 ayarı: BM25 + BGE-M3, k=20, kapsam filtresi. Vektör modeli kurulu değilse
yalnızca BM25 ile çalışır (testte yalnız BM25 farkı anlamsızdı: %90,9'a karşı %91,5).
"""
from __future__ import annotations

import json
import math
import os
from collections import Counter

import numpy as np

from .textnorm import stems

EMBED_MODEL = os.environ.get("COUNCIL_EMBED", "none")       # "bge-m3" | "none"
EMBED_PATH = os.environ.get("COUNCIL_EMBED_PATH", "")       # yerel model klasörü (boşsa HuggingFace adı)
_model = None


def embed_enabled() -> bool:
    return EMBED_MODEL != "none"


def _load():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBED_PATH or "BAAI/bge-m3", device="cpu")
    return _model


def embed(texts: list[str]) -> np.ndarray:
    return np.asarray(_load().encode(texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False), dtype=np.float32)


def doc_text(r: dict) -> str:
    keys = r["keys"] if isinstance(r["keys"], list) else json.loads(r["keys"] or "[]")
    return f"{r.get('context', '')}\n{r['text']}\n{' '.join(keys)}"


def bm25_scores(docs: list[str], query: str, k1: float = 1.2, b: float = 0.75) -> np.ndarray:
    toks = [stems(d) for d in docs]
    N = len(docs)
    if N == 0:
        return np.zeros(0)
    avg = sum(map(len, toks)) / N
    df = Counter(t for ts in toks for t in set(ts))
    tfs = [Counter(ts) for ts in toks]
    out = np.zeros(N)
    for t in set(stems(query)):
        if t not in df:
            continue
        idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
        for i, tf in enumerate(tfs):
            f = tf.get(t)
            if f:
                out[i] += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(toks[i]) / max(avg, 1e-9)))
    return out


def rrf(*lists: np.ndarray, k: int = 60) -> np.ndarray:
    out = np.zeros(len(lists[0]))
    for s in lists:
        ranks = np.empty(len(s), dtype=int)
        ranks[np.argsort(-s)] = np.arange(len(s))
        out += 1.0 / (k + ranks + 1)
    return out


def rank(records: list[dict], query: str) -> list[dict]:
    if not records:
        return []
    docs = [doc_text(r) for r in records]
    parts = [bm25_scores(docs, query)]
    if embed_enabled():
        have = [i for i, r in enumerate(records) if r.get("embedding")]
        if have:
            try:
                q = embed([query])[0]
            except Exception:        # model yüklenemedi: yalnız BM25 (arama hiç bozulmasın)
                q = None
            if q is not None:
                dense = np.full(len(records), -1.0)
                for i in have:
                    e = np.frombuffer(records[i]["embedding"], dtype=np.float32)
                    if e.shape == q.shape:
                        dense[i] = float(e @ q)
                parts.append(dense)
    sc = rrf(*parts) if len(parts) > 1 else parts[0]
    order = np.argsort(-sc)
    if len(parts) == 1:                                  # yalnız BM25: hiç eşleşmeyenleri at
        order = [i for i in order if sc[i] > 0]
    return [records[i] for i in order]
