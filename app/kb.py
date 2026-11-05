"""RAG-ассистент (MVP2 BR-48…50): ретрив по базе знаний стандарта + извлекающий ответ.

Контракт готов к замене на корпоративный AI-Buddy: функция answer() возвращает
извлекающий ответ из релевантных чанков + цитаты (pageId, title, url).
Асистент работает в advisory-режиме: только отвечает, ничего не меняет.
"""
import math
import re
from .kb_data import PAGES

_CHUNK = 900


def _split_sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 30]


def _chunks():
    out = []
    for p in PAGES:
        text = p["text"]
        # режем по абзацам, склеивая до ~_CHUNK символов
        paras = [t.strip() for t in text.split("\n\n") if t.strip()]
        cur = ""
        for para in paras:
            if cur and len(cur) + len(para) > _CHUNK:
                out.append({**p, "chunk": cur}); cur = ""
            cur = (cur + "\n\n" + para).strip()
        if cur:
            out.append({**p, "chunk": cur})
    return out


CHUNKS = _chunks()
_VOCAB: dict[str, int] = {}


def _tokenize(text):
    return [t for t in re.findall(r"\w{3,}", text.lower())]


def _vector(tokens):
    tf = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    return tf


def _build():
    global _IDF
    df = {}
    for c in CHUNKS:
        for t in set(_tokenize(c["chunk"])):
            df[t] = df.get(t, 0) + 1
    n = len(CHUNKS)
    _IDF = {t: math.log(n / (1 + k)) + 1.0 for t, k in df.items()}


_build()


def _score(query_tokens, chunk):
    vec = _vector(_tokenize(chunk["chunk"]))
    s = 0.0
    for t in query_tokens:
        if t in vec and t in _IDF:
            s += (1 + math.log(vec[t])) * _IDF[t]
    return s


def retrieve(question: str, k: int = 3):
    q = _tokenize(question)
    scored = sorted(((_score(q, c), i) for i, c in enumerate(CHUNKS)), reverse=True)
    hits = [(s, i) for s, i in scored if s > 0][:k]
    return [CHUNKS[i] for _, i in hits]


def answer(question: str, k: int = 3) -> dict:
    """Возвращает извлекающий ответ (лучшие предложения релевантных чанков) + цитаты."""
    hits = retrieve(question, k)
    if not hits:
        return {"answer": "В базе знаний стандарта нет релевантного раздела. "
                          "Уточните вопрос или откройте стандарт напрямую.",
                "citations": [], "confidence": 0.0}
    q = set(_tokenize(question))
    best = []
    for c in hits:
        sentences = sorted(_split_sentences(c["chunk"]),
                           key=lambda s: len(q & set(_tokenize(s))), reverse=True)
        if sentences and len(q & set(_tokenize(sentences[0]))) > 0:
            best.append((len(q & set(_tokenize(sentences[0]))), c, sentences[0]))
    best.sort(key=lambda x: -x[0])
    top = best[:3] if best else [(0, hits[0], _split_sentences(hits[0]["chunk"])[0])]
    answer_text = "\n\n".join(f"· {s}" for _, _, s in top)
    seen, citations = set(), []
    for _, c, _ in top:
        if c["page_id"] not in seen:
            seen.add(c["page_id"])
            citations.append({"page_id": c["page_id"], "title": c["title"], "url": c["url"]})
    confidence = round(min(1.0, top[0][0] / max(3, len(q))), 2)
    return {"answer": answer_text, "citations": citations, "confidence": confidence}
